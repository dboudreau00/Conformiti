"""
The questionnaire sent to the vendor: tokens, links, drafts, submission.

The organisation keeps its side (``VendorViewSet`` actions, the invite
viewset); the vendor's side is three unauthenticated endpoints keyed by the
token in the link. Everything the vendor can do is bounded: read the
questions and their own draft, save answers that pass the same validation the
organisation's own screen uses, submit once. A submission creates the
assessment and emails the vendor's owner; nothing else in the product is
reachable from the link.
"""
import hashlib
import logging
import secrets

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from accounts import tenancy
from audit.middleware import _client_ip
from audit.models import AuditLog

from .models import DEFAULT_QUESTIONNAIRE, QuestionnaireInvite, VendorAssessment

logger = logging.getLogger(__name__)

QUESTION_IDS = {q["id"] for q in DEFAULT_QUESTIONNAIRE}
ANSWER_VALUES = ("yes", "no", "partial", "n/a", None)


class QuestionnaireError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def validate_answers(value):
    """The one validation both sides use. Raises ValueError with a message."""
    if not isinstance(value, dict):
        raise ValueError("Answers must be an object keyed by question id.")
    unknown = set(value) - QUESTION_IDS
    if unknown:
        raise ValueError(f"Unknown question id(s): {', '.join(sorted(unknown))}")
    for qid, entry in value.items():
        if not isinstance(entry, dict) or entry.get("answer") not in ANSWER_VALUES:
            raise ValueError(f"{qid}: answer must be one of yes, no, partial, n/a.")
        if len(str(entry.get("note", ""))) > 1000:
            raise ValueError(f"{qid}: note is too long.")
    return {
        qid: {"answer": entry.get("answer"), "note": str(entry.get("note") or "")[:1000]}
        for qid, entry in value.items()
    }


# --------------------------------------------------------------------------- #
# Tokens and links
# --------------------------------------------------------------------------- #
def _hash(token):
    return hashlib.sha256(str(token or "")[:256].encode("utf-8")).hexdigest()


def public_base(request):
    """Where the vendor will open the link: PUBLIC_URL, else the origin the
    SPA sent the request from (the ``Origin`` header a browser attaches to a
    POST -- right behind the shipped nginx AND behind a dev proxy that
    rewrites Host), else the origin the request arrived on."""
    configured = getattr(settings, "PUBLIC_URL", "") or ""
    if configured:
        return configured.rstrip("/")
    if request is None:
        return ""
    origin = (request.headers.get("Origin") or "").strip().rstrip("/")
    if origin.startswith(("http://", "https://")) and "/" not in origin.split("://", 1)[1]:
        return origin
    return request.build_absolute_uri("/").rstrip("/")


def public_link(request, token):
    return f"{public_base(request)}/questionnaire/{token}"


def find(token):
    """The invite behind a token, or None. Live or not: the public page tells
    the vendor whether the link has expired or was already used."""
    if not token or len(token) > 256:
        return None
    return QuestionnaireInvite.objects.select_related("vendor", "sent_by").filter(
        token_hash=_hash(token)).first()


def _audit(request, invite, action, detail):
    try:
        AuditLog.objects.create(
            user=(request.user if request is not None and getattr(request, "user", None)
                  and request.user.is_authenticated else None),
            action=action, object_type="vendor-questionnaire", object_id=str(invite.pk),
            detail=str(detail)[:255], ip_address=_client_ip(request) if request is not None else None,
        )
    except Exception:
        logger.exception("Failed to record a questionnaire event")


# --------------------------------------------------------------------------- #
# The organisation's side
# --------------------------------------------------------------------------- #
def create_invite(vendor, request, email, days=None, message=""):
    """Issue a link and email it. Returns ``(invite, link)``; the link is
    returned exactly once, so the sender can paste it into their own mail if
    the automatic one does not arrive."""
    try:
        days = QuestionnaireInvite.DEFAULT_DAYS if days in (None, "") else int(days)
    except (TypeError, ValueError):
        raise QuestionnaireError("days", "Days must be a whole number.")
    if days < 1 or days > QuestionnaireInvite.MAX_DAYS:
        raise QuestionnaireError("days", f"Give the vendor between 1 and {QuestionnaireInvite.MAX_DAYS} days.")
    email = (email or "").strip()
    if not email or "@" not in email:
        raise QuestionnaireError("email", "Say who at the vendor should receive the questionnaire.")
    token = secrets.token_urlsafe(32)
    user = request.user
    with transaction.atomic():
        # One live link per vendor: a second send supersedes the first, so a
        # forwarded old link cannot be answered alongside the new one.
        QuestionnaireInvite.objects.filter(
            vendor=vendor, submitted_at__isnull=True, revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
        ).update(revoked_at=timezone.now(), revoked_by=user)
        invite = QuestionnaireInvite.objects.create(
            vendor=vendor, token_hash=_hash(token), sent_to=email[:254],
            message=str(message or "")[:2000], sent_by=user,
            sent_by_name=(user.get_full_name() or user.get_username())[:200],
            expires_at=timezone.now() + timezone.timedelta(days=days),
        )
    link = public_link(request, token)
    invite.email_sent = _send_invite(invite, link)
    invite.save(update_fields=["email_sent"])
    _audit(request, invite, "create",
           f"questionnaire sent to {email} for {vendor.name}, {days} day(s)"
           f"{'' if invite.email_sent else ' (email not sent)'}")
    return invite, link


def _send_invite(invite, link):
    from notifications.email_service import send_templated_email

    org = tenancy.organisation_name()
    subject = f"Security questionnaire from {org or invite.sent_by_name} for {invite.vendor.name}"
    context = {
        "invite": invite, "vendor": invite.vendor, "link": link, "organisation": org,
        "sender": invite.sent_by_name, "deadline": timezone.localtime(invite.expires_at).date(),
        "questions": DEFAULT_QUESTIONNAIRE, "message": invite.message,
    }
    try:
        return bool(send_templated_email(subject, "questionnaire_invite", context, [invite.sent_to]))
    except Exception:
        logger.exception("Questionnaire email to %s failed", invite.sent_to)
        return False


def revoke(invite, request):
    if invite.submitted_at:
        raise QuestionnaireError("state", "This questionnaire was already submitted.")
    if invite.revoked_at:
        return invite
    invite.revoked_at = timezone.now()
    invite.revoked_by = request.user
    invite.save(update_fields=["revoked_at", "revoked_by"])
    _audit(request, invite, "delete", f"questionnaire link for {invite.vendor.name} revoked")
    return invite


# --------------------------------------------------------------------------- #
# The vendor's side
# --------------------------------------------------------------------------- #
def public_state(invite, request=None):
    """What the public page shows. Never the vendor's other data."""
    if invite.status == "open" and invite.opened_at is None:
        invite.opened_at = timezone.now()
        invite.save(update_fields=["opened_at"])
    org = tenancy.organisation_name()
    return {
        "status": invite.status,
        "vendor": invite.vendor.name,
        "organisation": org,
        "sender": invite.sent_by_name,
        "sent_to": invite.sent_to,
        "message": invite.message,
        "expires_at": invite.expires_at,
        "submitted_at": invite.submitted_at,
        "respondent_name": invite.respondent_name,
        "questions": DEFAULT_QUESTIONNAIRE,
        "answers": invite.draft if invite.status == "open" else {},
        "saved_at": invite.saved_at,
    }


def _require_live(invite):
    if invite is None:
        raise QuestionnaireError("unknown", "This questionnaire link is not valid.")
    if invite.status == "submitted":
        raise QuestionnaireError("submitted", "This questionnaire was already submitted. Thank you.")
    if invite.status == "revoked":
        raise QuestionnaireError("revoked", "This questionnaire link was withdrawn. Ask your contact for a new one.")
    if invite.status == "expired":
        raise QuestionnaireError("expired", "This questionnaire link has expired. Ask your contact for a new one.")


def save_draft(invite, answers, request=None):
    _require_live(invite)
    try:
        clean = validate_answers(answers)
    except ValueError as exc:
        raise QuestionnaireError("answers", str(exc))
    invite.draft = clean
    invite.saved_at = timezone.now()
    invite.save(update_fields=["draft", "saved_at"])
    return invite


def submit(invite, answers, respondent_name, respondent_title="", request=None):
    """Turn the answers into a pending assessment. Once."""
    _require_live(invite)
    name = str(respondent_name or "").strip()[:160]
    if not name:
        raise QuestionnaireError("name", "Give your name so we know who answered.")
    try:
        clean = validate_answers(answers)
    except ValueError as exc:
        raise QuestionnaireError("answers", str(exc))
    answered = sum(1 for a in clean.values() if a.get("answer"))
    if answered == 0:
        raise QuestionnaireError("answers", "Answer at least one question before submitting.")
    now = timezone.now()
    with transaction.atomic():
        # Re-read under a lock: two submits of the same link race to one row.
        locked = QuestionnaireInvite.objects.select_for_update().get(pk=invite.pk)
        _require_live(locked)
        assessment = VendorAssessment.objects.create(
            vendor=locked.vendor, kind=VendorAssessment.Kind.QUESTIONNAIRE,
            title=f"Questionnaire answered by {locked.vendor.name}"[:200],
            issued_at=timezone.localdate(), result=VendorAssessment.Result.PENDING,
            answers=clean,
            findings=(f"Answered by {name}{' (' + str(respondent_title).strip()[:160] + ')' if respondent_title else ''} "
                      f"<{locked.sent_to}> on {timezone.localdate().isoformat()} through the emailed "
                      f"questionnaire; {answered} of {len(DEFAULT_QUESTIONNAIRE)} answered. Pending review."),
        )
        locked.draft = clean
        locked.saved_at = now
        locked.submitted_at = now
        locked.respondent_name = name
        locked.respondent_title = str(respondent_title or "").strip()[:160]
        locked.assessment = assessment
        locked.save(update_fields=["draft", "saved_at", "submitted_at", "respondent_name",
                                   "respondent_title", "assessment"])
    invite.refresh_from_db()
    _audit(request, invite, "create",
           f"questionnaire for {invite.vendor.name} submitted by {name} <{invite.sent_to}>: "
           f"{answered} answered -> assessment {assessment.pk}")
    _notify_returned(invite, assessment, answered)
    from notifications import webhooks
    webhooks.post_event(
        "questionnaire.returned", f"Questionnaire returned by {invite.vendor.name}",
        f"{name} answered {answered} of {len(DEFAULT_QUESTIONNAIRE)} questions; filed as a pending "
        "assessment for review.",
        facts=[("Vendor tier", invite.vendor.get_tier_display()),
               ("Answered 'No'", sum(1 for a in clean.values() if a.get("answer") == "no"))],
        path=f"/vendors?vendor={invite.vendor_id}&tab=questionnaire", severity="medium")
    return assessment


def _notify_returned(invite, assessment, answered):
    from notifications.email_service import send_templated_email

    vendor = invite.vendor
    recipients = []
    if vendor.owner and vendor.owner.email:
        recipients.append(vendor.owner.email)
    if invite.sent_by and invite.sent_by.email:
        recipients.append(invite.sent_by.email)
    recipients.append(settings.COMPLIANCE_TEAM_EMAIL)
    context = {
        "vendor": vendor, "invite": invite, "assessment": assessment, "answered": answered,
        "total": len(DEFAULT_QUESTIONNAIRE),
        "owner_name": vendor.owner.get_full_name() if vendor.owner else "team",
        "noes": sum(1 for a in assessment.answers.values() if a.get("answer") == "no"),
    }
    try:
        send_templated_email(f"[Review] {vendor.name} returned their security questionnaire",
                             "questionnaire_returned", context, recipients)
    except Exception:
        logger.exception("Questionnaire-returned email for vendor %s failed", vendor.pk)
