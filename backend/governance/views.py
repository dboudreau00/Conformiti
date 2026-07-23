"""Views for access reviews (with CSV export), meeting cadence, and groups."""
import csv

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.response import Response

from documents.models import FolderPermission

from .models import (
    AccessReview,
    AccessReviewItem,
    ChampionGroup,
    GroupMember,
    MeetingMinute,
    MeetingSeries,
)
from .serializers import (
    AccessReviewItemSerializer,
    AccessReviewSerializer,
    ChampionGroupSerializer,
    GroupMemberSerializer,
    MeetingMinuteSerializer,
    MeetingSeriesSerializer,
)


# --------------------------------------------------------------------------- #
# Permissions
# --------------------------------------------------------------------------- #
class AccessAuditPermission(BasePermission):
    """Access reviews contain account data: managers run them, auditors may read."""

    def has_permission(self, request, view):
        u = request.user
        if not (u and u.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return u.can_manage_users or u.is_auditor
        return u.can_manage_users


class ManageDocumentsOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        u = request.user
        if not (u and u.is_authenticated):
            return False
        return True if request.method in SAFE_METHODS else u.can_manage_documents


class ManageUsersOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        u = request.user
        if not (u and u.is_authenticated):
            return False
        return True if request.method in SAFE_METHODS else u.can_manage_users


# --------------------------------------------------------------------------- #
# Access reviews
# --------------------------------------------------------------------------- #
CAP_FLAGS = [
    ("can_manage_users", "users"),
    ("can_manage_frameworks", "frameworks"),
    ("can_manage_documents", "documents"),
    ("can_manage_folders", "folders"),
    ("can_view_all", "view-all"),
    ("is_auditor", "auditor"),
]

# Characters a spreadsheet may interpret as the start of a formula. Snapshot
# fields (names, job titles, notes) are user-controlled, so any value beginning
# with one of these is prefixed with a quote to neutralise CSV/formula injection.
_CSV_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(row):
    out = []
    for value in row:
        if isinstance(value, str) and value and value[0] in _CSV_DANGEROUS:
            value = "'" + value
        out.append(value)
    return out


def _snapshot_items(review):
    """Create one grid row per user account with a stable point-in-time snapshot."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    rows = []
    for u in User.objects.select_related("role").order_by("username"):
        caps = ", ".join(label for attr, label in CAP_FLAGS if getattr(u, attr))
        grants = FolderPermission.objects.filter(user=u).count()
        if u.role_id:
            grants += FolderPermission.objects.filter(role_id=u.role_id).count()
        rows.append(AccessReviewItem(
            review=review, user=u,
            username=u.username, full_name=u.get_full_name(), email=u.email,
            job_title=getattr(u, "job_title", "") or "",
            role_name=u.role.name if u.role_id else "",
            is_active=u.is_active, last_login=u.last_login,
            folder_grants=grants, capabilities=caps,
        ))
    AccessReviewItem.objects.bulk_create(rows)


class AccessReviewViewSet(viewsets.ModelViewSet):
    queryset = AccessReview.objects.all()
    serializer_class = AccessReviewSerializer
    permission_classes = [AccessAuditPermission]

    def perform_create(self, serializer):
        review = serializer.save(created_by=self.request.user)
        _snapshot_items(review)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        review = self.get_object()
        if review.status == AccessReview.Status.COMPLETED:
            return Response({"detail": "Already completed."}, status=status.HTTP_400_BAD_REQUEST)
        pending = review.items.filter(decision=AccessReviewItem.Decision.PENDING).count()
        if pending:
            return Response(
                {"detail": f"{pending} row(s) still pending a decision."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        review.status = AccessReview.Status.COMPLETED
        review.completed_at = timezone.now()
        review.save(update_fields=["status", "completed_at"])
        return Response(AccessReviewSerializer(review).data)

    @action(detail=True, methods=["get"])
    def export(self, request, pk=None):
        """Download the review grid as CSV — the audit evidence artifact."""
        review = self.get_object()
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="access-review-{review.id}.csv"'
        )
        writer = csv.writer(response)
        writer.writerow([
            "Username", "Full name", "Email", "Job title", "Role", "Active",
            "Last login", "Folder grants", "Capabilities",
            "Decision", "Notes", "Decided by", "Decided at",
        ])
        for it in review.items.all():
            writer.writerow(_csv_safe([
                it.username, it.full_name, it.email, it.job_title, it.role_name,
                "yes" if it.is_active else "no",
                it.last_login.isoformat() if it.last_login else "",
                it.folder_grants, it.capabilities,
                it.get_decision_display(), it.decision_notes,
                it.decided_by.get_full_name() if it.decided_by else "",
                it.decided_at.isoformat() if it.decided_at else "",
            ]))
        return response


class AccessReviewItemViewSet(viewsets.ModelViewSet):
    """Rows are created by the snapshot, edited (decision/notes) via PATCH.

    Pagination is disabled: a review's rows (one per user account) are a bounded
    set the grid needs in full to compute decided/total and show every account.
    Default 50-row pagination would silently truncate the audit grid for orgs
    with more than 50 users."""
    queryset = AccessReviewItem.objects.select_related("review", "decided_by")
    serializer_class = AccessReviewItemSerializer
    permission_classes = [AccessAuditPermission]
    pagination_class = None
    filterset_fields = ["review", "decision"]
    http_method_names = ["get", "patch", "head", "options"]


# --------------------------------------------------------------------------- #
# Meetings
# --------------------------------------------------------------------------- #
class MeetingSeriesViewSet(viewsets.ModelViewSet):
    queryset = MeetingSeries.objects.select_related("owner")
    serializer_class = MeetingSeriesSerializer
    permission_classes = [ManageDocumentsOrReadOnly]
    filterset_fields = ["active"]
    search_fields = ["name"]


class MeetingMinuteViewSet(viewsets.ModelViewSet):
    queryset = MeetingMinute.objects.select_related("series", "created_by")
    serializer_class = MeetingMinuteSerializer
    permission_classes = [ManageDocumentsOrReadOnly]
    filterset_fields = ["series"]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


# --------------------------------------------------------------------------- #
# Champion groups
# --------------------------------------------------------------------------- #
class ChampionGroupViewSet(viewsets.ModelViewSet):
    queryset = ChampionGroup.objects.select_related("owner")
    serializer_class = ChampionGroupSerializer
    permission_classes = [ManageUsersOrReadOnly]
    search_fields = ["name"]


class GroupMemberViewSet(viewsets.ModelViewSet):
    queryset = GroupMember.objects.select_related("group", "user")
    serializer_class = GroupMemberSerializer
    permission_classes = [ManageUsersOrReadOnly]
    filterset_fields = ["group"]


# ==========================================================================
# Risk register
# ==========================================================================
from django.db import transaction
from django.db.models import Count
from rest_framework.exceptions import PermissionDenied, ValidationError

from accounts.models import User
from compliance.models import Control

from .models import Risk, RiskNote
from .risk_import import MAX_FILE_BYTES, normalize, parse_upload
from .serializers import RiskNoteSerializer, RiskSerializer


class RiskPermission(BasePermission):
    """Read: any authenticated user (the register is program-wide context).
    Create / delete / import: framework managers.
    Update: framework managers, or the risk's owner driving their remediation."""

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        if view.action in ("create", "import_file"):
            return user.can_manage_frameworks
        return True  # PATCH/DELETE decided per-object below

    def has_object_permission(self, request, view, obj):
        user = request.user
        if request.method in SAFE_METHODS:
            return True
        if request.method == "DELETE":
            return user.can_manage_frameworks
        return user.can_manage_frameworks or obj.owner_id == user.id


class RiskViewSet(viewsets.ModelViewSet):
    serializer_class = RiskSerializer
    permission_classes = [RiskPermission]
    filterset_fields = ["status", "risk_type", "owner", "control", "treatment"]
    search_fields = ["title", "description", "jira_key"]

    def get_queryset(self):
        return (
            Risk.objects.select_related(
                "owner", "created_by",
                "control", "control__category", "control__category__framework",
            )
            .annotate(note_count=Count("notes", distinct=True))
        )

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    # ---- register-level summary (page header / dashboards) -----------------
    @action(detail=False, methods=["get"])
    def summary(self, request):
        today = timezone.localdate()
        live = Risk.objects.filter(status__in=[Risk.Status.OPEN, Risk.Status.MITIGATING])
        by_rating = {"low": 0, "moderate": 0, "high": 0, "critical": 0}
        for risk in live.only("likelihood", "impact"):
            by_rating[risk.rating] += 1
        return Response({
            "open": live.filter(status=Risk.Status.OPEN).count(),
            "mitigating": live.filter(status=Risk.Status.MITIGATING).count(),
            "overdue": live.filter(due_date__lt=today).count(),
            "accepted": Risk.objects.filter(status=Risk.Status.ACCEPTED).count(),
            "closed": Risk.objects.filter(status=Risk.Status.CLOSED).count(),
            "by_rating": by_rating,
        })

    # ---- CSV export (audit evidence) ---------------------------------------
    @action(detail=False, methods=["get"])
    def export(self, request):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="risk-register.csv"'
        writer = csv.writer(response)
        writer.writerow([
            "Title", "Type", "Status", "Treatment", "Likelihood", "Impact",
            "Score", "Rating", "Owner", "Due date", "Identified", "Control",
            "Jira", "Mitigation plan", "Description", "Created", "Closed",
        ])
        for r in self.get_queryset().order_by("status", "-created_at"):
            writer.writerow(_csv_safe([
                r.title, r.get_risk_type_display(), r.get_status_display(),
                r.get_treatment_display(), r.likelihood, r.impact,
                r.score, r.rating,
                r.owner.get_full_name() if r.owner else "",
                r.due_date.isoformat() if r.due_date else "",
                r.identified_on.isoformat() if r.identified_on else "",
                r.control.control_id if r.control else "",
                r.jira_key, r.mitigation_plan, r.description,
                r.created_at.date().isoformat(),
                r.closed_at.date().isoformat() if r.closed_at else "",
            ]))
        return response

    # ---- CSV / XLSX import --------------------------------------------------
    @action(detail=False, methods=["post"], url_path="import")
    def import_file(self, request):
        """Ingest a register from .csv or .xlsx. Creates new risks, skips rows
        whose title already exists, and reports per-row warnings. Parsing is
        dependency-free — see governance/risk_import.py."""
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": "Attach a .csv or .xlsx file."})
        if upload.size > MAX_FILE_BYTES:
            raise ValidationError({"file": "File is larger than the 2 MB import limit."})
        try:
            rows = parse_upload(upload.name, upload.read())
        except ValueError as exc:
            raise ValidationError({"file": str(exc)})
        records, issues, fatal = normalize(rows)
        if fatal:
            raise ValidationError({"file": fatal})

        # Resolve owners by username, email, or full name (case-insensitive).
        owner_lookup = {}
        for u in User.objects.all():
            owner_lookup[u.username.lower()] = u
            if u.email:
                owner_lookup[u.email.lower()] = u
            full = u.get_full_name().strip().lower()
            if full:
                owner_lookup.setdefault(full, u)

        # Resolve controls by control_id, or "framework_key:control_id".
        control_lookup = {}
        for c in Control.objects.select_related("category__framework"):
            control_lookup.setdefault(c.control_id.lower(), []).append(c)
            control_lookup.setdefault(
                f"{c.category.framework.key.lower()}:{c.control_id.lower()}", [c]
            )

        existing_titles = {t.lower() for t in Risk.objects.values_list("title", flat=True)}
        created, skipped = [], []
        with transaction.atomic():
            for rec in records:
                if rec["title"].lower() in existing_titles:
                    skipped.append({"row": rec["row"], "title": rec["title"],
                                    "reason": "a risk with this title already exists"})
                    continue
                owner = None
                if rec["owner"]:
                    owner = owner_lookup.get(rec["owner"].lower())
                    if owner is None:
                        issues.append({"row": rec["row"], "field": "owner",
                                       "message": f"Owner {rec['owner']!r} not found — left unassigned"})
                control = None
                if rec["control"]:
                    matches = control_lookup.get(rec["control"].lower(), [])
                    if len(matches) == 1:
                        control = matches[0]
                    else:
                        reason = "not found" if not matches else "ambiguous — prefix with framework key like soc2:CC6.1"
                        issues.append({"row": rec["row"], "field": "control",
                                       "message": f"Control {rec['control']!r} {reason}"})
                risk = Risk.objects.create(
                    title=rec["title"],
                    description=rec["description"],
                    status=rec["status"],
                    risk_type=rec["risk_type"],
                    treatment=rec["treatment"],
                    likelihood=rec["likelihood"] or 3,
                    impact=rec["impact"] or 3,
                    owner=owner,
                    control=control,
                    due_date=rec["due_date"],
                    identified_on=rec["identified_on"] or timezone.localdate(),
                    jira_key=rec["jira_key"],
                    mitigation_plan=rec["mitigation_plan"],
                    created_by=request.user,
                    closed_at=timezone.now() if rec["status"] == Risk.Status.CLOSED else None,
                )
                if rec["note"]:
                    RiskNote.objects.create(risk=risk, author=request.user, text=rec["note"])
                existing_titles.add(rec["title"].lower())
                created.append(risk.id)

        return Response({
            "created": len(created),
            "skipped": skipped,
            "warnings": issues,
        })


class RiskNoteViewSet(viewsets.ModelViewSet):
    """Progress notes on a risk. Anyone authenticated may read and add to the
    thread; a note can be deleted by its author or a framework manager."""
    serializer_class = RiskNoteSerializer
    http_method_names = ["get", "post", "delete", "head", "options"]
    filterset_fields = ["risk"]

    def get_queryset(self):
        return RiskNote.objects.select_related("author").all()

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

    def perform_destroy(self, instance):
        user = self.request.user
        if not (user.can_manage_frameworks or instance.author_id == user.id):
            raise PermissionDenied("Only the note's author or a framework manager can delete it.")
        instance.delete()
