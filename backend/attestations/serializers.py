"""Serializers for evidence packages. Explicit field lists everywhere: a
`__all__` here would publish the forensic storage path."""
from rest_framework import serializers

from .models import EvidencePackage, PackageControl, PackageEvidence, PackageGrant, PackageSample


class PackageSampleSerializer(serializers.ModelSerializer):
    result_display = serializers.CharField(source="get_result_display", read_only=True)
    control_ref = serializers.CharField(source="package_control.control_ref", read_only=True)

    class Meta:
        model = PackageSample
        fields = [
            "id", "package_control", "control_ref", "ordinal", "identifier", "description",
            "population_ref", "evidence", "evidence_name", "sealed_in",
            "selected_by_name", "selected_at",
            "result", "result_display", "exception_note", "tested_by_name", "tested_at",
            "created_at",
        ]
        read_only_fields = [
            "ordinal", "evidence_name", "sealed_in", "selected_by_name", "selected_at",
            "tested_by_name", "tested_at", "created_at",
        ]

    def validate_identifier(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("Name the item that was sampled.")
        return value

    def validate(self, attrs):
        """An exception has to say what the exception was; a bare 'fail' is
        useless to the person reading the workpaper next year."""
        merged = {
            "result": getattr(self.instance, "result", PackageSample.Result.PENDING),
            "exception_note": getattr(self.instance, "exception_note", ""),
            **attrs,
        }
        if merged["result"] == PackageSample.Result.FAIL and not (merged["exception_note"] or "").strip():
            raise serializers.ValidationError({"exception_note": "Say what the exception was."})
        return attrs


class PackageEvidenceSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()
    integrity = serializers.SerializerMethodField()

    class Meta:
        model = PackageEvidence
        # storage_name / storage_path are deliberately absent: they are the
        # unauthenticated route to the bytes.
        fields = [
            "id", "package_control", "document", "ordinal", "document_name",
            "pinned_version", "size_bytes", "hash_algorithm", "content_sha256",
            "doc_status", "doc_status_display", "last_reviewed", "next_review_date",
            "covers_from", "covers_to", "is_population", "evidence_note",
            "linked_by_name", "evidence_linked_at", "pinned_by_name", "snapshot_at",
            "member_path", "download_url", "integrity",
        ]
        read_only_fields = [
            "document_name", "pinned_version", "size_bytes", "hash_algorithm",
            "content_sha256", "doc_status", "doc_status_display", "last_reviewed",
            "next_review_date", "linked_by_name", "evidence_linked_at",
            "pinned_by_name", "snapshot_at", "member_path", "ordinal",
        ]

    def get_download_url(self, obj):
        return f"/package-evidence/{obj.pk}/file/"

    def get_integrity(self, obj):
        """Cheap check: does the live document still carry the pinned version?

        A full re-hash happens at seal and at export; doing it on every list
        response would read every file on every page load.
        """
        if obj.document_id is None:
            return "detached"
        return "current" if obj.document.version == obj.pinned_version else "superseded"


class PackageControlSerializer(serializers.ModelSerializer):
    evidence = PackageEvidenceSerializer(many=True, read_only=True)
    samples = PackageSampleSerializer(many=True, read_only=True)
    sample_summary = serializers.SerializerMethodField()
    sampling_method_display = serializers.CharField(source="get_sampling_method_display", read_only=True)

    class Meta:
        model = PackageControl
        fields = [
            "id", "package", "control", "ordinal", "framework_key", "framework_name",
            "framework_version", "category_key", "category_name", "control_ref",
            "title", "objective", "mgmt_status", "mgmt_status_display", "owner_name",
            "note", "included_by_name", "snapshot_at",
            "design_conclusion", "operating_conclusion", "not_tested_reason",
            "auditor_note", "concluded_by_name", "concluded_at",
            "management_response", "responded_by_name", "responded_at",
            "population_size", "population_source", "sampling_method", "sampling_method_display",
            "sampling_note", "sample_summary", "samples",
            "risk", "evidence",
        ]
        read_only_fields = [
            "package", "control", "ordinal", "framework_key", "framework_name",
            "framework_version", "category_key", "category_name", "control_ref",
            "title", "objective", "mgmt_status", "mgmt_status_display", "owner_name",
            "included_by_name", "snapshot_at", "concluded_by_name", "concluded_at",
            "responded_by_name", "responded_at", "risk",
        ]

    def get_sample_summary(self, obj):
        counts = {"total": 0, "pass": 0, "fail": 0, "not_tested": 0, "pending": 0}
        for s in obj.samples.all():
            counts["total"] += 1
            counts[s.result] = counts.get(s.result, 0) + 1
        return counts

    def validate(self, attrs):
        """A "not tested" conclusion has to say why. An auditor reading this
        package next year cannot ask."""
        merged = {**{
            "design_conclusion": getattr(self.instance, "design_conclusion", ""),
            "operating_conclusion": getattr(self.instance, "operating_conclusion", ""),
            "not_tested_reason": getattr(self.instance, "not_tested_reason", ""),
        }, **attrs}
        not_tested = PackageControl.Conclusion.NOT_TESTED
        if not_tested in (merged["design_conclusion"], merged["operating_conclusion"]) \
                and not (merged["not_tested_reason"] or "").strip():
            raise serializers.ValidationError(
                {"not_tested_reason": "Say why this control was not tested."}
            )
        return attrs


class PackageGrantSerializer(serializers.ModelSerializer):
    is_live = serializers.BooleanField(read_only=True)

    class Meta:
        model = PackageGrant
        fields = [
            "id", "package", "user", "username", "full_name", "email",
            "granted_by_name", "granted_at", "expires_at", "revoked_at",
            "note", "last_accessed_at", "access_count", "is_live",
        ]
        read_only_fields = [
            "username", "full_name", "email", "granted_by_name", "granted_at",
            "revoked_at", "last_accessed_at", "access_count",
        ]


class EvidencePackageSerializer(serializers.ModelSerializer):
    framework_name = serializers.CharField(source="framework.name", read_only=True, default="")
    assurance_type_display = serializers.CharField(source="get_assurance_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    control_count = serializers.SerializerMethodField()
    evidence_count = serializers.SerializerMethodField()
    live_grants = serializers.SerializerMethodField()

    class Meta:
        model = EvidencePackage
        fields = [
            "id", "name", "engagement", "audit_firm", "framework", "framework_name",
            "scope", "assurance_type", "assurance_type_display",
            "period_start", "period_end", "scope_note",
            "status", "status_display",
            "assertion", "asserted_by_name", "asserted_at",
            "sealed_by_name", "sealed_at", "manifest_sha256", "manifest_version",
            "manifest_algorithm", "generator",
            "withdrawn_at", "withdrawn_reason",
            "created_by_name", "created_at", "updated_at",
            "control_count", "evidence_count", "live_grants",
        ]
        read_only_fields = [
            "status", "asserted_by_name", "asserted_at", "sealed_by_name", "sealed_at",
            "manifest_sha256", "manifest_version", "manifest_algorithm", "generator",
            "withdrawn_at", "withdrawn_reason", "created_by_name",
        ]

    def get_control_count(self, obj):
        return obj.controls.count()

    def get_evidence_count(self, obj):
        return PackageEvidence.objects.filter(package_control__package=obj).count()

    def get_live_grants(self, obj):
        return [
            {"username": g.username, "full_name": g.full_name, "expires_at": g.expires_at}
            for g in obj.grants.all() if g.is_live
        ]
