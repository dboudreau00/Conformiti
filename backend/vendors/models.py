"""
Third-party vendor risk management.

A vendor is any outside party the organisation relies on for a control — the
cloud provider that owns physical security, the payroll processor that holds
PII, the pen-test firm whose report is evidence. What an auditor asks about
each one is the same every time: how critical is it, what data does it touch,
what assurance do we hold over it, and has that assurance expired.

Assurance is modelled as ``VendorAssessment`` rows: a SOC 2 report, an ISO
certificate, a penetration test, a signed DPA, a completed questionnaire —
each with a validity window, an outcome, and optionally the document that
evidences it. The register's risk view is derived from those, never typed in.
"""
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

# The questionnaire the product ships. Deliberately short: every question maps
# to something an auditor will ask about the vendor, and a 200-question sheet
# nobody finishes is worse than twelve everyone does. Answers are stored on the
# assessment as JSON keyed by ``id``.
DEFAULT_QUESTIONNAIRE = [
    {"id": "soc2", "text": "Does the vendor hold a current SOC 2 Type II report (or equivalent)?", "area": "assurance"},
    {"id": "iso", "text": "Is the vendor certified to ISO/IEC 27001, and is the certificate current?", "area": "assurance"},
    {"id": "pentest", "text": "Has an independent penetration test been performed in the last 12 months?", "area": "assurance"},
    {"id": "data_location", "text": "Where is our data stored and processed, and can it leave that region?", "area": "data"},
    {"id": "encryption", "text": "Is our data encrypted in transit and at rest, and who holds the keys?", "area": "data"},
    {"id": "subprocessors", "text": "Which sub-processors handle our data, and are we told when that list changes?", "area": "data"},
    {"id": "access", "text": "Is access to our data limited by role, reviewed periodically, and protected by MFA?", "area": "access"},
    {"id": "incident", "text": "What is the incident notification commitment, in hours, and how is it delivered?", "area": "resilience"},
    {"id": "bcp", "text": "Is there a tested business-continuity plan, and what are the recovery objectives?", "area": "resilience"},
    {"id": "dpa", "text": "Is a data-processing agreement in place, and does it cover breach notification?", "area": "contract"},
    {"id": "exit", "text": "On termination, how and when is our data returned and deleted?", "area": "contract"},
    {"id": "insurance", "text": "Does the vendor carry cyber-liability insurance, and to what limit?", "area": "contract"},
]


class Vendor(models.Model):
    class Tier(models.TextChoices):
        CRITICAL = "critical", "Critical"
        HIGH = "high", "High"
        MEDIUM = "medium", "Medium"
        LOW = "low", "Low"

    class Status(models.TextChoices):
        PROSPECTIVE = "prospective", "Prospective"
        ACTIVE = "active", "Active"
        OFFBOARDING = "offboarding", "Offboarding"
        OFFBOARDED = "offboarded", "Offboarded"

    class Cadence(models.TextChoices):
        QUARTERLY = "quarterly", "Quarterly"
        SEMIANNUAL = "semiannual", "Every 6 months"
        ANNUAL = "annual", "Annual"
        BIENNIAL = "biennial", "Every 2 years"

    CADENCE_DAYS = {"quarterly": 91, "semiannual": 182, "annual": 365, "biennial": 730}

    name = models.CharField(max_length=160, unique=True)
    # The column layout of the last matrix file they sent us, so the matrix
    # can go back to them in their own shape: {"columns": [{"name", "role"}],
    # "file", "framework", "saved_at"}.
    matrix_layout = models.JSONField(null=True, blank=True)
    category = models.CharField(
        max_length=80, blank=True,
        help_text="What they do for us: cloud hosting, payroll, identity, security testing…",
    )
    website = models.URLField(blank=True)
    contact_name = models.CharField(max_length=160, blank=True)
    contact_email = models.EmailField(blank=True)
    tier = models.CharField(max_length=10, choices=Tier.choices, default=Tier.MEDIUM,
                            help_text="How much we depend on them and how bad a failure would be.")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    # Free text on purpose: classification schemes differ between organisations.
    data_handled = models.CharField(
        max_length=255, blank=True,
        help_text="What of ours they touch, e.g. 'customer PII, cardholder data'.",
    )
    services = models.TextField(blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="owned_vendors",
        help_text="The relationship owner accountable for this vendor.",
    )
    review_cadence = models.CharField(max_length=12, choices=Cadence.choices, default=Cadence.ANNUAL)
    last_reviewed = models.DateField(null=True, blank=True)
    next_review_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="created_vendors",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def compute_next_review(self):
        """Next review counts from the last one, or from onboarding when there
        has never been one -- never from "now", or a vendor that keeps being
        edited would keep being pushed out of the overdue list."""
        base = self.last_reviewed or (self.created_at.date() if self.created_at else timezone.localdate())
        self.next_review_date = base + timedelta(days=self.CADENCE_DAYS[self.review_cadence])
        return self.next_review_date

    @property
    def is_live(self):
        return self.status in (self.Status.ACTIVE, self.Status.OFFBOARDING)

    def assurance(self):
        """The current state of what we hold over this vendor.

        Returns a dict the register and the notifications feed both use, so
        the two never disagree: which assessments are current, which have
        expired, and a single posture word.
        """
        today = timezone.localdate()
        rows = list(self.assessments.all())
        current, expired, missing_result = [], [], []
        for a in rows:
            if a.expires_at and a.expires_at < today:
                expired.append(a)
            elif a.result == VendorAssessment.Result.UNSATISFACTORY:
                missing_result.append(a)
            else:
                current.append(a)
        if not rows:
            posture = "none"
        elif missing_result:
            posture = "unsatisfactory"
        elif expired and not current:
            posture = "expired"
        elif expired:
            posture = "partial"
        else:
            posture = "current"
        return {
            "posture": posture,
            "current": len(current),
            "expired": len(expired),
            "unsatisfactory": len(missing_result),
            "review_overdue": bool(self.next_review_date and self.next_review_date < today),
        }

    def risk_rating(self):
        """Tier crossed with assurance posture. A critical vendor with expired
        assurance is the case this exists to surface."""
        posture = self.assurance()["posture"]
        tier_rank = {"critical": 3, "high": 2, "medium": 1, "low": 0}[self.tier]
        posture_rank = {"none": 3, "unsatisfactory": 3, "expired": 2, "partial": 1, "current": 0}[posture]
        score = tier_rank + posture_rank
        if score >= 5:
            return "critical"
        if score >= 3:
            return "high"
        if score >= 2:
            return "moderate"
        return "low"


class VendorAssessment(models.Model):
    """One piece of assurance we hold over a vendor, with its validity window."""

    class Kind(models.TextChoices):
        SOC2_TYPE1 = "soc2_type1", "SOC 2 Type I"
        SOC2_TYPE2 = "soc2_type2", "SOC 2 Type II"
        ISO27001 = "iso27001", "ISO/IEC 27001 certificate"
        PCI_AOC = "pci_aoc", "PCI DSS AOC"
        PENTEST = "pentest", "Penetration test"
        QUESTIONNAIRE = "questionnaire", "Security questionnaire"
        DPA = "dpa", "Data-processing agreement"
        CONTRACT = "contract", "Contract / MSA"
        RESP_MATRIX = "resp_matrix", "Responsibility matrix (their document)"
        BRIDGE_LETTER = "bridge_letter", "Bridge letter"
        OTHER = "other", "Other"

    # The kinds a bridge letter bridges: a SOC report whose period has ended
    # while the next one is still being written.
    BRIDGEABLE = ("soc2_type1", "soc2_type2")

    class Result(models.TextChoices):
        SATISFACTORY = "satisfactory", "Satisfactory"
        EXCEPTIONS = "exceptions", "Exceptions noted"
        UNSATISFACTORY = "unsatisfactory", "Unsatisfactory"
        PENDING = "pending", "Pending review"

    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name="assessments")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    title = models.CharField(max_length=200, blank=True)
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    issued_at = models.DateField(null=True, blank=True)
    expires_at = models.DateField(null=True, blank=True,
                                  help_text="When this stops being acceptable evidence.")
    result = models.CharField(max_length=16, choices=Result.choices, default=Result.PENDING)
    # The report itself lives in the evidence library, so it can be pinned into
    # an audit package like any other document.
    document = models.ForeignKey(
        "documents.Document", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="vendor_assessments",
    )
    # Questionnaire answers keyed by question id: {"soc2": {"answer": "yes", "note": "..."}}.
    answers = models.JSONField(default=dict, blank=True)
    findings = models.TextField(blank=True, help_text="Exceptions, CUECs, anything to follow up.")
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="vendor_assessments_reviewed",
    )
    # When the bridge-letter reminder for this lapsed report went out: one
    # email per lapse, never one per day.
    bridge_reminded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-issued_at", "-created_at"]

    def __str__(self):
        return f"{self.vendor} · {self.get_kind_display()}"

    @property
    def is_expired(self):
        return bool(self.expires_at and self.expires_at < timezone.localdate())


class SharedResponsibility(models.Model):
    """One control's split between us and a vendor, with a statement each way.

    This is the PCI DSS "responsibility matrix" (v4 Req 12.8.5 / TPSP guidance)
    generalised to every framework: for each control, does the provider do it,
    do we, or is it shared -- and what, concretely, does each side do. An
    auditor reads this before anything else about the vendor, because it tells
    them which controls' evidence to expect from whom.

    Kept as its own structure rather than a document: the vendor's PDF is filed
    as a ``VendorAssessment`` of kind ``resp_matrix``; this is the machine-
    readable version we can cross-check against the control register, prompt
    people to complete, and export.
    """

    class Responsibility(models.TextChoices):
        PROVIDER = "provider", "Provider"
        CUSTOMER = "customer", "Customer (us)"
        SHARED = "shared", "Shared"
        NOT_APPLICABLE = "not_applicable", "Not applicable"

    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name="shared_responsibilities")
    control = models.ForeignKey(
        "compliance.Control", on_delete=models.CASCADE, related_name="shared_responsibilities")
    responsibility = models.CharField(max_length=16, choices=Responsibility.choices)
    provider_statement = models.TextField(
        blank=True, help_text="What the provider does for this control.")
    customer_statement = models.TextField(
        blank=True, help_text="What remains ours to do (CUECs, configuration, monitoring).")
    source = models.CharField(
        max_length=16, default="manual",
        help_text="manual | import -- how this row came to exist.")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="shared_responsibilities_edited",
    )
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["control"]
        unique_together = ("vendor", "control")
        verbose_name_plural = "shared responsibilities"

    def __str__(self):
        return f"{self.vendor}: {self.control.control_id} = {self.responsibility}"


class QuestionnaireInvite(models.Model):
    """The questionnaire, sent to the vendor to answer themselves.

    A time-boxed link, like an audit package grant but for someone with no
    account: the vendor's contact gets an email with a URL carrying a random
    token, answers the shipped questions in the browser, saves a draft as
    often as they like, and submits once. The submission lands as a
    ``VendorAssessment`` of kind ``questionnaire`` with ``result=pending`` for
    the organisation to review. Only the token's hash is stored; the link is
    shown once to the person who sent it and travels in the email.
    """
    DEFAULT_DAYS = 14
    MAX_DAYS = 90

    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name="questionnaire_invites")
    token_hash = models.CharField(max_length=64, unique=True)
    sent_to = models.EmailField()
    message = models.TextField(blank=True, help_text="A note to the vendor, included in the email.")
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="questionnaire_invites_sent",
    )
    sent_by_name = models.CharField(max_length=200, blank=True)
    sent_at = models.DateTimeField(auto_now_add=True)
    email_sent = models.BooleanField(default=False)
    expires_at = models.DateTimeField()
    opened_at = models.DateTimeField(null=True, blank=True)
    saved_at = models.DateTimeField(null=True, blank=True)
    draft = models.JSONField(default=dict, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    respondent_name = models.CharField(max_length=160, blank=True)
    respondent_title = models.CharField(max_length=160, blank=True)
    assessment = models.ForeignKey(
        VendorAssessment, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="invites",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="questionnaire_invites_revoked",
    )

    class Meta:
        ordering = ["-sent_at"]

    def __str__(self):
        return f"Questionnaire for {self.vendor} -> {self.sent_to}"

    @property
    def status(self):
        if self.submitted_at:
            return "submitted"
        if self.revoked_at:
            return "revoked"
        if self.expires_at <= timezone.now():
            return "expired"
        return "open"

    @property
    def is_live(self):
        return self.status == "open"
