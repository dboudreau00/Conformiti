"""
Evidence packages: what was disclosed to an auditor, when, and by whom.

The audit ritual this replaces is a folder grant. Someone gives the external
auditor VIEW on a framework root, the auditor reads whatever lands there for
the next six months, and somebody is supposed to remember to take it away. The
package is the narrow version of that: a named person gets a fixed, sealed,
time-boxed list of artefacts, every read is recorded, and withdrawal is one
click rather than an act of memory.

Everything an auditor is shown is a SNAPSHOT taken when the item was pinned.
Controls get renamed, documents get new versions, people leave. None of that may
change what a sealed package says was handed over — so each row carries its own
copy of the values, exactly as ``governance.AccessReviewItem`` already does.
"""
from django.conf import settings
from django.db import models


class EvidencePackage(models.Model):
    """One disclosure: a scope, an assertion, a seal and a set of recipients."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SEALED = "sealed", "Sealed"
        WITHDRAWN = "withdrawn", "Withdrawn"

    class Assurance(models.TextChoices):
        READINESS = "readiness", "Readiness assessment"
        TYPE_I = "type_i", "SOC 2 Type I"
        TYPE_II = "type_ii", "SOC 2 Type II"
        ISO_STAGE_1 = "iso_stage_1", "ISO 27001 Stage 1"
        ISO_STAGE_2 = "iso_stage_2", "ISO 27001 Stage 2"
        ISO_SURVEILLANCE = "iso_surveillance", "ISO 27001 surveillance"
        PCI_ROC = "pci_roc", "PCI DSS Report on Compliance"
        INTERNAL = "internal", "Internal audit"

    name = models.CharField(max_length=160)
    engagement = models.CharField(max_length=160, blank=True)
    audit_firm = models.CharField(max_length=160, blank=True)
    framework = models.ForeignKey(
        "compliance.Framework", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="evidence_packages",
    )
    # The scope statement an auditor reads first. Reuses the categories the
    # frameworks already model (CC1..CC9, A.5..A.8, Req 1..12).
    scope = models.ManyToManyField(
        "compliance.ControlCategory", blank=True, related_name="evidence_packages",
    )
    assurance_type = models.CharField(
        max_length=20, choices=Assurance.choices, default=Assurance.READINESS,
        help_text="What kind of engagement this package supports. Shown on the cover.",
    )
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    scope_note = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)

    # --- management assertion (required to seal) ---
    assertion = models.TextField(blank=True)
    asserted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="packages_asserted",
    )
    asserted_by_name = models.CharField(max_length=200, blank=True)
    asserted_at = models.DateTimeField(null=True, blank=True)

    # --- seal ---
    sealed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="packages_sealed",
    )
    sealed_by_name = models.CharField(max_length=200, blank=True)
    sealed_at = models.DateTimeField(null=True, blank=True)
    manifest_version = models.PositiveSmallIntegerField(default=0)
    manifest_algorithm = models.CharField(max_length=16, blank=True)
    manifest_sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    # Stored verbatim so an archived package stays verifiable without this code.
    manifest_json = models.TextField(blank=True)
    generator = models.CharField(max_length=60, blank=True)

    # --- withdrawal ---
    withdrawn_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="packages_withdrawn",
    )
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawn_reason = models.CharField(max_length=255, blank=True)

    # Year-over-year roll-forward is a 0.3.1 feature, but the column ships now:
    # retrofitting it means a second migration against tables people already hold.
    prior_package = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="successors",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="packages_created",
    )
    created_by_name = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    @property
    def is_open(self):
        """Draft packages accept changes; sealed and withdrawn ones never do."""
        return self.status == self.Status.DRAFT

    @property
    def evidence_count(self):
        return PackageEvidence.objects.filter(package_control__package=self).count()


class PackageControl(models.Model):
    """One control's workpaper row.

    A control with no evidence still gets a row — that row is often the most
    audit-relevant thing in the package.
    """

    class Conclusion(models.TextChoices):
        PENDING = "pending", "Not concluded"
        NO_EXCEPTIONS = "no_exceptions", "No exceptions noted"
        EXCEPTIONS = "exceptions", "Exceptions noted"
        NOT_TESTED = "not_tested", "Not tested"

    package = models.ForeignKey(EvidencePackage, on_delete=models.CASCADE, related_name="controls")
    control = models.ForeignKey(
        "compliance.Control", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="package_rows",
    )
    ordinal = models.PositiveIntegerField(default=0)

    # --- snapshot, taken when the control was added ---
    framework_key = models.CharField(max_length=40, blank=True)
    framework_name = models.CharField(max_length=120, blank=True)
    framework_version = models.CharField(max_length=60, blank=True)
    category_key = models.CharField(max_length=40, blank=True)
    category_name = models.CharField(max_length=200, blank=True)
    control_ref = models.CharField(max_length=40)
    title = models.CharField(max_length=255)
    objective = models.TextField(blank=True)
    mgmt_status = models.CharField(max_length=20, blank=True)
    mgmt_status_display = models.CharField(max_length=40, blank=True)
    owner_name = models.CharField(max_length=200, blank=True)
    note = models.CharField(max_length=255, blank=True)
    included_by_name = models.CharField(max_length=200, blank=True)
    snapshot_at = models.DateTimeField(auto_now_add=True)

    # --- the auditor's conclusions. Two axes, because a Type I is design only
    # and "designed effectively, operated with exceptions" is the commonest
    # Type II outcome. Writable ONLY by a live grantee.
    design_conclusion = models.CharField(
        max_length=16, choices=Conclusion.choices, default=Conclusion.PENDING)
    operating_conclusion = models.CharField(
        max_length=16, choices=Conclusion.choices, default=Conclusion.PENDING)
    not_tested_reason = models.CharField(max_length=300, blank=True)
    auditor_note = models.TextField(blank=True)
    concluded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="package_conclusions",
    )
    concluded_by_name = models.CharField(max_length=200, blank=True)
    concluded_at = models.DateTimeField(null=True, blank=True)

    # --- the client's answer, so a disagreement lands inside the record
    # rather than in an email thread nobody keeps.
    management_response = models.TextField(blank=True)
    responded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="package_responses",
    )
    responded_by_name = models.CharField(max_length=200, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    # Set when an exception is promoted into the risk register.
    risk = models.ForeignKey(
        "governance.Risk", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="package_findings",
    )

    # --- the population, stated by the organisation while the package is a
    # draft and sealed with it: what the auditor samples FROM. The sampling
    # note is the auditor's, written after sealing like a conclusion.
    class Sampling(models.TextChoices):
        RANDOM = "random", "Random"
        HAPHAZARD = "haphazard", "Haphazard"
        JUDGMENTAL = "judgmental", "Judgmental"
        COMPLETE = "complete", "Complete population"

    population_size = models.PositiveIntegerField(null=True, blank=True)
    population_source = models.CharField(
        max_length=255, blank=True,
        help_text="Where the population came from, e.g. 'HR termination report, FY26'.")
    sampling_method = models.CharField(max_length=12, blank=True, choices=Sampling.choices)
    sampling_note = models.TextField(blank=True)

    class Meta:
        ordering = ["ordinal", "control_ref"]
        unique_together = ("package", "control")

    def __str__(self):
        return f"{self.control_ref} in {self.package_id}"


class PackageSample(models.Model):
    """One sampled item on a control's workpaper row: the unit a Type II
    operating-effectiveness test is actually performed on.

    Items listed while the package is a draft are sealed into the manifest
    (identifier, what it is, where in the population it came from, which
    pinned artefact supports it). After sealing only the issued auditor adds
    items — their own selections — and records the result per item. The
    result is workpaper data, mutable by the auditor alone, exactly like a
    conclusion; the organisation never touches it.
    """

    class Result(models.TextChoices):
        PENDING = "pending", "Not yet tested"
        PASS = "pass", "Pass"
        FAIL = "fail", "Exception"
        NOT_TESTED = "not_tested", "Not tested"

    package_control = models.ForeignKey(
        PackageControl, on_delete=models.CASCADE, related_name="samples")
    ordinal = models.PositiveIntegerField(default=0)
    identifier = models.CharField(
        max_length=120, help_text="The item sampled: a ticket, a user, a change number, a date.")
    description = models.CharField(max_length=255, blank=True)
    population_ref = models.CharField(
        max_length=255, blank=True,
        help_text="Where this item sits in the population, e.g. 'row 17 of the export'.")
    evidence = models.ForeignKey(
        "attestations.PackageEvidence", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="samples",
    )
    evidence_name = models.CharField(max_length=255, blank=True)
    # True for items that were part of the sealed manifest; an auditor's own
    # selections after sealing are not, and the bundle says which is which.
    sealed_in = models.BooleanField(default=False)
    selected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="samples_selected",
    )
    selected_by_name = models.CharField(max_length=200, blank=True)
    selected_at = models.DateTimeField(null=True, blank=True)

    result = models.CharField(max_length=12, choices=Result.choices, default=Result.PENDING)
    exception_note = models.TextField(blank=True)
    tested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="samples_tested",
    )
    tested_by_name = models.CharField(max_length=200, blank=True)
    tested_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["ordinal", "identifier", "pk"]
        unique_together = ("package_control", "identifier")

    def __str__(self):
        return f"{self.identifier} on {self.package_control_id}"


class PackageEvidence(models.Model):
    """The chain of custody for one artefact: what it was, which version, how
    big, its digest, and who asserted on what date that it evidences this
    control."""

    package_control = models.ForeignKey(
        PackageControl, on_delete=models.CASCADE, related_name="evidence")
    document = models.ForeignKey(
        "documents.Document", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="package_pins",
    )
    ordinal = models.PositiveIntegerField(default=0)

    # --- snapshot, taken when the document was pinned ---
    document_name = models.CharField(max_length=255)
    pinned_version = models.PositiveIntegerField(default=1)
    # Forensic only: superuser-visible, never serialized to anyone else, never
    # in a manifest, a CSV or a bundle. Publishing it would hand back the
    # unauthenticated storage path the 0.3.0 media work just closed.
    storage_name = models.CharField(max_length=255, blank=True)
    storage_path = models.CharField(max_length=500, blank=True)
    size_bytes = models.BigIntegerField(default=0)
    hash_algorithm = models.CharField(max_length=16, default="sha256")
    content_sha256 = models.CharField(max_length=64, blank=True)
    doc_status = models.CharField(max_length=12, blank=True)
    doc_status_display = models.CharField(max_length=40, blank=True)
    last_reviewed = models.DateField(null=True, blank=True)
    next_review_date = models.DateField(null=True, blank=True)
    # Period of coverage: what span of time this artefact evidences.
    covers_from = models.DateField(null=True, blank=True)
    covers_to = models.DateField(null=True, blank=True)
    is_population = models.BooleanField(
        default=False, help_text="This artefact is the population the auditor samples from.")
    evidence_note = models.CharField(max_length=255, blank=True)
    linked_by_name = models.CharField(max_length=200, blank=True)
    evidence_linked_at = models.DateTimeField(null=True, blank=True)
    pinned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="evidence_pinned",
    )
    pinned_by_name = models.CharField(max_length=200, blank=True)
    snapshot_at = models.DateTimeField(auto_now_add=True)
    # Assigned at seal, so the manifest can name the file before the bundle exists.
    member_path = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["ordinal", "document_name"]
        unique_together = ("package_control", "document")
        verbose_name_plural = "package evidence"

    def __str__(self):
        return f"{self.document_name} (v{self.pinned_version})"


class PackageGrant(models.Model):
    """The entire folder-permission bypass is scoped by this row.

    Per user, never per role: the Auditor role must not silently pick up every
    package that is ever sealed. ``SET_NULL`` plus the name snapshots because
    deleting the auditor's account must not erase the record of who was given
    access, by whom, and when — the same discipline ``AccessReviewItem`` applies.
    Withdrawal sets ``revoked_at`` rather than deleting: it is a fact, not an
    absence.
    """

    package = models.ForeignKey(EvidencePackage, on_delete=models.CASCADE, related_name="grants")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="package_grants",
    )
    username = models.CharField(max_length=150, blank=True)
    full_name = models.CharField(max_length=200, blank=True)
    email = models.EmailField(blank=True)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="package_grants_made",
    )
    granted_by_name = models.CharField(max_length=200, blank=True)
    granted_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="package_grants_revoked",
    )
    note = models.CharField(max_length=255, blank=True)
    last_accessed_at = models.DateTimeField(null=True, blank=True)
    access_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-granted_at"]
        unique_together = ("package", "user")

    def __str__(self):
        return f"{self.username} -> {self.package_id}"

    @property
    def is_live(self):
        from django.utils import timezone
        return self.revoked_at is None and self.expires_at > timezone.now()


class PbcRequest(models.Model):
    """One line of the auditor's request list ("prepared by client").

    The package is what the organisation hands over; the request list is what
    the auditor asks for, before and during fieldwork, and the other half of
    the same workflow. Either side may raise a line: the issued auditor from
    inside the package, or the organisation transcribing the list the auditor
    emailed. The organisation assigns it, chases it (reminders go to the
    assignee), and answers it by attaching documents; the auditor accepts the
    answer or returns it with a note. Nothing here changes the sealed
    manifest -- a request answered after sealing is a supplementary
    disclosure, read under the same grant and recorded the same way.
    """

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        PROVIDED = "provided", "Provided"
        ACCEPTED = "accepted", "Accepted"
        RETURNED = "returned", "Returned"
        WITHDRAWN = "withdrawn", "Withdrawn"

    class Priority(models.TextChoices):
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"

    class Side(models.TextChoices):
        AUDITOR = "auditor", "Auditor"
        ORGANISATION = "organisation", "Organisation"

    # The statuses that are still the organisation's to act on.
    ACTIONABLE = ("open", "returned")

    package = models.ForeignKey(EvidencePackage, on_delete=models.CASCADE, related_name="pbc_requests")
    ordinal = models.PositiveIntegerField()
    reference = models.CharField(max_length=20)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    package_control = models.ForeignKey(
        PackageControl, null=True, blank=True, on_delete=models.SET_NULL, related_name="pbc_requests")
    control_ref = models.CharField(max_length=40, blank=True)
    priority = models.CharField(max_length=8, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    due_date = models.DateField(null=True, blank=True)
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="pbc_requests_assigned",
    )
    assignee_name = models.CharField(max_length=200, blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="pbc_requests_raised",
    )
    requested_by_name = models.CharField(max_length=200, blank=True)
    requested_by_side = models.CharField(max_length=12, choices=Side.choices, default=Side.ORGANISATION)
    response_note = models.TextField(blank=True)
    provided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="pbc_requests_provided",
    )
    provided_by_name = models.CharField(max_length=200, blank=True)
    provided_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="pbc_requests_accepted",
    )
    accepted_by_name = models.CharField(max_length=200, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    returned_note = models.TextField(blank=True)
    returned_at = models.DateTimeField(null=True, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    # Lead-time windows already emailed, like Document.reminders_sent.
    reminders_sent = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["package", "ordinal"]
        unique_together = ("package", "ordinal")

    def __str__(self):
        return f"{self.reference}: {self.title}"

    @property
    def is_actionable(self):
        return self.status in self.ACTIONABLE

    @property
    def is_overdue(self):
        from django.utils import timezone
        return bool(self.is_actionable and self.due_date and self.due_date < timezone.localdate())


class PbcItem(models.Model):
    """A document attached in answer to a request, snapshotted as it stood
    (name, version, digest) exactly like pinned package evidence, so the
    answer stays a record even if the document moves on."""

    request = models.ForeignKey(PbcRequest, on_delete=models.CASCADE, related_name="items")
    document = models.ForeignKey(
        "documents.Document", null=True, blank=True, on_delete=models.SET_NULL, related_name="pbc_items")
    document_name = models.CharField(max_length=255)
    version = models.PositiveIntegerField(default=1)
    size_bytes = models.BigIntegerField(default=0)
    content_sha256 = models.CharField(max_length=64, blank=True)
    note = models.CharField(max_length=255, blank=True)
    attached_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="pbc_items_attached",
    )
    attached_by_name = models.CharField(max_length=200, blank=True)
    attached_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["attached_at", "pk"]
        unique_together = ("request", "document")

    def __str__(self):
        return f"{self.document_name} on {self.request_id}"
