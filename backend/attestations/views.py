"""
The evidence-package API.

Two rules run through everything here:

* every read of a package, its rows or its bytes goes through
  ``access.readable_packages`` — there is no second path;
* every write is refused unless the package is still a draft, checked at the
  *view*, not in a serializer. ``AccessReviewItemSerializer`` guards its
  read-only rule in ``validate()``, which ``@action`` endpoints skip entirely;
  this app does not copy that.
"""
import tempfile

from django.db import transaction
from django.http import FileResponse
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from audit.events import record_package_event
from compliance.models import Control
from documents import monitor
from documents.downloads import serve_stored_file
from documents.models import Document

from . import access, bundle, rollforward
from .manifest import canonical_bytes, sha256_hex
from .models import EvidencePackage, PackageControl, PackageEvidence, PackageGrant, PackageSample
from .serializers import (
    EvidencePackageSerializer,
    PackageControlSerializer,
    PackageEvidenceSerializer,
    PackageGrantSerializer,
    PackageSampleSerializer,
)
from .snapshot import pin_document, snapshot_control, stamp, verify_pins

MIN_ASSERTION = 40


class CanAssemble(BasePermission):
    """Write access to packages. Reads are filtered by the queryset instead, so
    a user with no packages gets an empty 200 rather than a 403 -- the sidebar
    shows the nav item to everyone."""

    def has_permission(self, request, view):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return bool(request.user and request.user.is_authenticated)
        return access.can_assemble(request.user)


def assert_open(package):
    """Sealed and withdrawn packages never change again."""
    if not package.is_open:
        raise ValidationError(
            {"detail": f"This package is {package.get_status_display().lower()} and is now read-only."}
        )


class PackageWorkThrottle(ScopedRateThrottle):
    scope = "package_work"


class EvidencePackageViewSet(viewsets.ModelViewSet):
    serializer_class = EvidencePackageSerializer
    permission_classes = [IsAuthenticated, CanAssemble]
    filterset_fields = ["status", "framework", "assurance_type"]
    search_fields = ["name", "engagement", "audit_firm"]

    def get_queryset(self):
        return access.readable_packages(self.request.user) \
            .select_related("framework").prefetch_related("grants", "scope")

    def _check_prior(self, prior, package=None):
        """A predecessor must be one the caller can read, no longer a draft,
        and not lead back to this package."""
        if prior is None:
            return
        if prior not in access.readable_packages(self.request.user):
            raise ValidationError({"prior_package": "Unknown package."})
        if prior.status == EvidencePackage.Status.DRAFT:
            raise ValidationError({"prior_package": "Roll forward from a sealed package, not a draft."})
        if package is not None and rollforward.would_cycle(package, prior):
            raise ValidationError({"prior_package": "That would make the package its own predecessor."})

    def perform_create(self, serializer):
        user = self.request.user
        self._check_prior(serializer.validated_data.get("prior_package"))
        package = serializer.save(
            created_by=user,
            created_by_name=(user.get_full_name() or user.get_username())[:200],
        )
        record_package_event(self.request, package, "create",
                             f"opened evidence package {package.pk}: {package.name}")

    def perform_update(self, serializer):
        package = self.get_object()
        assert_open(package)
        if "prior_package" in serializer.validated_data:
            self._check_prior(serializer.validated_data.get("prior_package"), package)
        serializer.save()

    # ------------------------------------------------------------ roll-forward
    @action(detail=True, methods=["post"])
    def roll_forward(self, request, pk=None):
        """Open next year's draft from this sealed package: the same controls
        re-snapshotted today, today's visible evidence pinned, and this package
        recorded as the predecessor. Conclusions and samples are not copied."""
        prior = self.get_object()
        if not access.can_assemble(request.user):
            raise PermissionDenied("You need the frameworks capability to roll a package forward.")
        try:
            package, skipped = rollforward.roll_forward(
                prior, request.user, name=str(request.data.get("name") or "").strip() or None,
                engagement=request.data.get("engagement"))
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)})
        record_package_event(request, package, "create",
                             f"rolled package {prior.pk} forward into {package.pk}: {package.name}")
        data = EvidencePackageSerializer(package, context={"request": request}).data
        data["skipped"] = skipped
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def diff(self, request, pk=None):
        """The year-over-year comparison with the predecessor, from the two
        packages' own snapshots."""
        package = self.get_object()
        result = rollforward.diff(package)
        if result is None:
            raise ValidationError({"detail": "This package has no predecessor."})
        if package.prior_package not in access.readable_packages(request.user):
            raise PermissionDenied("You cannot read the predecessor package.")
        return Response(result)

    def perform_destroy(self, instance):
        # A sealed package is a record of a disclosure. Withdraw it instead.
        assert_open(instance)
        record_package_event(self.request, instance, "delete",
                             f"deleted draft evidence package {instance.pk}: {instance.name}")
        instance.delete()

    # ---------------------------------------------------------------- assemble
    @action(detail=True, methods=["post"])
    def add_controls(self, request, pk=None):
        """Add controls to a draft, optionally pinning the evidence already
        linked to each one.

        Evidence the caller cannot see is skipped and reported, never silently
        dropped and never pinned.
        """
        package = self.get_object()
        assert_open(package)
        if not access.can_assemble(request.user):
            raise PermissionDenied("You need the frameworks capability to assemble a package.")

        ids = request.data.get("controls") or []
        if not isinstance(ids, list) or not ids:
            raise ValidationError({"controls": "Give a list of control ids."})
        with_evidence = bool(request.data.get("with_evidence", True))

        controls = Control.objects.filter(pk__in=ids).select_related("category__framework")
        existing = set(package.controls.values_list("control_id", flat=True))
        added, skipped = [], []

        from documents.access import accessible_folder_ids
        visible = accessible_folder_ids(request.user)

        with transaction.atomic():
            for control in controls:
                if control.pk in existing:
                    continue
                row = snapshot_control(package, control, request.user)
                added.append(row.pk)
                if not with_evidence:
                    continue
                links = control.evidence_links.select_related("document", "linked_by").all()
                for link in links:
                    document = link.document
                    if document.folder_id not in visible:
                        skipped.append({
                            "control": control.control_id,
                            "document": document.name,
                            "reason": "not visible to you",
                        })
                        continue
                    pin_document(row, document, request.user, link=link)

        record_package_event(request, package, "update",
                             f"added {len(added)} control(s) to package {package.pk}")
        return Response({"added": len(added), "skipped": skipped},
                        status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def seal(self, request, pk=None):
        """Freeze the package and compute its manifest digest."""
        package = self.get_object()
        assert_open(package)
        if not access.can_assemble(request.user):
            raise PermissionDenied("You need the frameworks capability to seal a package.")

        assertion = str(request.data.get("assertion") or package.assertion or "").strip()
        if len(assertion) < MIN_ASSERTION:
            raise ValidationError({"assertion": (
                f"Write a management assertion of at least {MIN_ASSERTION} characters. "
                "It is the statement the auditor relies on."
            )})
        if not package.controls.exists():
            raise ValidationError({"detail": "Add at least one control before sealing."})

        drifted = verify_pins(package)
        if drifted:
            return Response(
                {"detail": "Some pinned evidence no longer matches what was pinned. "
                           "Refresh or unpin it, then seal.",
                 "drifted": drifted},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            package.assertion = assertion
            stamp(package, request.user, "asserted")
            stamp(package, request.user, "sealed")
            package.status = EvidencePackage.Status.SEALED
            package.generator = bundle.GENERATOR
            package.save()
            bundle.assign_paths(package)
            package.refresh_from_db()
            payload = bundle.build_manifest(package)
            raw = canonical_bytes(payload)
            package.manifest_json = raw.decode("utf-8")
            package.manifest_sha256 = sha256_hex(raw)
            package.manifest_version = payload["manifest_version"]
            package.manifest_algorithm = payload["hash_algorithm"]
            package.save(update_fields=[
                "manifest_json", "manifest_sha256", "manifest_version", "manifest_algorithm",
            ])

        # Digest first: AuditLog.detail is capped at 255 characters and the
        # digest is the only thing in the row that binds it to these bytes.
        record_package_event(
            request, package, "seal",
            f"sha256={package.manifest_sha256} sealed package {package.pk} "
            f"with {package.evidence_count} item(s): {package.name[:60]}",
        )
        return Response(EvidencePackageSerializer(package).data)

    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        """Revoke every grant and close the package. The record remains."""
        package = self.get_object()
        if not access.can_assemble(request.user):
            raise PermissionDenied("You need the frameworks capability to withdraw a package.")
        if package.status == EvidencePackage.Status.WITHDRAWN:
            raise ValidationError({"detail": "Already withdrawn."})

        now = timezone.now()
        revoked = package.grants.filter(revoked_at__isnull=True).update(
            revoked_at=now, revoked_by=request.user)
        package.status = EvidencePackage.Status.WITHDRAWN
        package.withdrawn_reason = str(request.data.get("reason", ""))[:255]
        stamp(package, request.user, "withdrawn")
        package.save()
        record_package_event(request, package, "withdraw",
                             f"withdrew package {package.pk}, revoking {revoked} grant(s)")
        return Response(EvidencePackageSerializer(package).data)

    # ------------------------------------------------------------------ verify
    @action(detail=True, methods=["get"])
    def verify(self, request, pk=None):
        """Re-hash the live files and compare with what was sealed."""
        package = self.get_object()
        drifted = verify_pins(package)
        return Response({
            "package": package.pk,
            "status": package.status,
            "manifest_sha256": package.manifest_sha256,
            "items": package.evidence_count,
            "ok": not drifted,
            "discrepancies": drifted,
        })

    @action(detail=True, methods=["get"])
    def manifest(self, request, pk=None):
        """The sealed manifest, byte-for-byte."""
        package = self.get_object()
        if not package.manifest_json:
            raise ValidationError({"detail": "This package has not been sealed."})
        from django.http import HttpResponse
        response = HttpResponse(package.manifest_json, content_type="application/json")
        response["Content-Disposition"] = f'attachment; filename="manifest-{package.pk}.json"'
        return response

    @action(detail=True, methods=["get"], throttle_classes=[PackageWorkThrottle])
    def export(self, request, pk=None):
        """The whole package as one self-verifying ZIP."""
        package = self.get_object()
        if package.status == EvidencePackage.Status.DRAFT:
            raise ValidationError({"detail": "Seal the package before exporting it."})

        handle = tempfile.TemporaryFile()
        try:
            summary = bundle.write_bundle(package, handle)
            handle.seek(0)
        except Exception:
            handle.close()
            raise

        record_package_event(
            request, package, "export",
            f"exported package {package.pk} ({summary['items']} item(s), "
            f"{summary['altered']} altered, {summary['missing']} missing)",
        )
        slug = "".join(ch if ch.isalnum() else "-" for ch in package.name).strip("-")[:60]
        response = FileResponse(handle, as_attachment=True,
                                filename=f"{slug or 'evidence-package'}-{package.pk}.zip")
        response["X-Conformiti-Integrity"] = (
            "ok" if not (summary["altered"] or summary["missing"])
            else f"discrepancies={summary['altered'] + summary['missing']}"
        )
        return response


class PackageControlViewSet(viewsets.ModelViewSet):
    """The workpaper rows. Conclusions are writable only by a live grantee;
    the management response only by the organisation."""
    serializer_class = PackageControlSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["package", "design_conclusion", "operating_conclusion"]
    # POST is here only for the `promote` action; there is no create route.
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return PackageControl.objects.filter(
            package__in=access.readable_packages(self.request.user)
        ).select_related("package").prefetch_related("evidence", "samples")

    def create(self, request, *args, **kwargs):
        from rest_framework.exceptions import MethodNotAllowed
        raise MethodNotAllowed(
            "POST", detail="Add controls with POST /evidence-packages/{id}/add_controls/."
        )

    def perform_update(self, serializer):
        row = self.get_object()
        user = self.request.user
        data = serializer.validated_data
        auditor_fields = {"design_conclusion", "operating_conclusion",
                          "not_tested_reason", "auditor_note", "sampling_note"}
        touching_conclusions = bool(auditor_fields & set(data))
        touching_response = "management_response" in data

        if touching_conclusions:
            grant = access.live_grant(user, row.package)
            if grant is None:
                raise PermissionDenied(
                    "Only the auditor this package was issued to can record a conclusion."
                )
            stamp(row, user, "concluded")
            serializer.save(concluded_by=row.concluded_by,
                            concluded_by_name=row.concluded_by_name,
                            concluded_at=row.concluded_at)
        if touching_response:
            if not access.can_assemble(user):
                raise PermissionDenied(
                    "The management response is written by the assessed organisation."
                )
            stamp(row, user, "responded")
            serializer.save(responded_by=row.responded_by,
                            responded_by_name=row.responded_by_name,
                            responded_at=row.responded_at)
        if not (touching_conclusions or touching_response):
            if not access.can_assemble(user):
                raise PermissionDenied("You cannot change this row.")
            assert_open(row.package)
            serializer.save()

    def perform_destroy(self, instance):
        if not access.can_assemble(self.request.user):
            raise PermissionDenied("You cannot change this package.")
        assert_open(instance.package)
        instance.delete()

    @action(detail=True, methods=["post"])
    def promote(self, request, pk=None):
        """Turn an exception into a tracked risk.

        Makes ``Risk.Type.AUDIT_FINDING`` reachable from the product for the
        first time, and is the one action here that removes work rather than
        recording it.
        """
        from governance.models import Risk

        row = self.get_object()
        if not access.can_assemble(request.user):
            raise PermissionDenied("You need the frameworks capability to raise a risk.")
        if row.risk_id:
            raise ValidationError({"detail": "This finding is already tracked as a risk."})
        if PackageControl.Conclusion.EXCEPTIONS not in (
            row.design_conclusion, row.operating_conclusion
        ):
            raise ValidationError(
                {"detail": "Only a control with exceptions noted can be raised as a finding."}
            )
        risk = Risk.objects.create(
            title=f"Audit finding: {row.control_ref} {row.title}"[:200],
            description=(row.auditor_note or "Exception noted during the audit.")[:2000],
            risk_type=Risk.Type.AUDIT_FINDING,
            control=row.control,
            owner=row.package.created_by,
            created_by=request.user,
        )
        row.risk = risk
        row.save(update_fields=["risk"])
        record_package_event(request, row.package, "update",
                             f"raised risk {risk.pk} from finding on {row.control_ref}")
        return Response(PackageControlSerializer(row).data, status=status.HTTP_201_CREATED)


class PackageSampleViewSet(viewsets.ModelViewSet):
    """Sampled items on a workpaper row.

    Two writers, never at the same time: the organisation lists items while
    the package is a draft (they are sealed into the manifest); the issued
    auditor adds their own selections and records every result after sealing.
    Results are the auditor's alone, like conclusions.
    """
    serializer_class = PackageSampleSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["package_control", "result", "sealed_in"]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    ITEM_FIELDS = {"identifier", "description", "population_ref", "evidence"}
    RESULT_FIELDS = {"result", "exception_note"}

    def get_queryset(self):
        return PackageSample.objects.filter(
            package_control__package__in=access.readable_packages(self.request.user)
        ).select_related("package_control__package", "evidence")

    @staticmethod
    def _check_evidence(row, evidence):
        if evidence is not None and evidence.package_control_id != row.pk:
            raise ValidationError({"evidence": "Pick an artefact pinned to this control."})

    def perform_create(self, serializer):
        user = self.request.user
        data = serializer.validated_data
        row = data["package_control"]
        package = row.package
        if package not in access.readable_packages(user):
            raise PermissionDenied("Unknown package.")
        self._check_evidence(row, data.get("evidence"))
        extra = {"evidence_name": data["evidence"].document_name if data.get("evidence") else ""}
        if package.is_open:
            if not access.can_assemble(user):
                raise PermissionDenied("You need the frameworks capability to list sample items.")
            if data.get("result", PackageSample.Result.PENDING) != PackageSample.Result.PENDING:
                raise ValidationError({"result": "Results are recorded by the auditor after sealing."})
        elif package.status == EvidencePackage.Status.SEALED:
            if access.live_grant(user, package) is None:
                raise PermissionDenied(
                    "After sealing, only the auditor this package was issued to can add sample items.")
            if data.get("result", PackageSample.Result.PENDING) != PackageSample.Result.PENDING:
                now = timezone.now()
                extra.update(tested_by=user, tested_at=now,
                             tested_by_name=(user.get_full_name() or user.get_username())[:200])
        else:
            assert_open(package)
        sample = serializer.save(
            selected_by=user, selected_at=timezone.now(),
            selected_by_name=(user.get_full_name() or user.get_username())[:200], **extra)
        record_package_event(self.request, package, "update",
                             f"listed sample item '{sample.identifier}' on {row.control_ref} "
                             f"in package {package.pk}")

    def perform_update(self, serializer):
        sample = self.get_object()
        user = self.request.user
        row = sample.package_control
        package = row.package
        data = serializer.validated_data
        touching_result = bool(self.RESULT_FIELDS & set(data))
        touching_item = bool(self.ITEM_FIELDS & set(data))
        if package.status == EvidencePackage.Status.WITHDRAWN:
            assert_open(package)
        extra = {}
        if touching_result:
            if access.live_grant(user, package) is None:
                raise PermissionDenied(
                    "Only the auditor this package was issued to can record a sample result.")
            stamp(sample, user, "tested")
            extra.update(tested_by=sample.tested_by, tested_by_name=sample.tested_by_name,
                         tested_at=sample.tested_at)
        if touching_item:
            if package.is_open:
                if not access.can_assemble(user):
                    raise PermissionDenied("You cannot change this package.")
            else:
                # Sealed: the manifest's items are fixed; an auditor may still
                # correct the selections they added themselves.
                if sample.sealed_in or access.live_grant(user, package) is None:
                    raise PermissionDenied("Sample items in the sealed manifest cannot be changed.")
            if "evidence" in data:
                self._check_evidence(row, data.get("evidence"))
                extra["evidence_name"] = data["evidence"].document_name if data.get("evidence") else ""
        serializer.save(**extra)
        if touching_result:
            record_package_event(self.request, package, "update",
                                 f"sample '{sample.identifier}' on {row.control_ref}: "
                                 f"{serializer.instance.get_result_display()}")

    def perform_destroy(self, instance):
        user = self.request.user
        package = instance.package_control.package
        if package.is_open:
            if not access.can_assemble(user):
                raise PermissionDenied("You cannot change this package.")
        elif package.status == EvidencePackage.Status.SEALED:
            if instance.sealed_in or access.live_grant(user, package) is None:
                raise PermissionDenied("Sample items in the sealed manifest cannot be removed.")
        else:
            assert_open(package)
        instance.delete()


class PackageEvidenceViewSet(viewsets.ModelViewSet):
    serializer_class = PackageEvidenceSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["package_control"]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return PackageEvidence.objects.filter(
            package_control__package__in=access.readable_packages(self.request.user)
        ).select_related("package_control__package", "document")

    def perform_create(self, serializer):
        row = serializer.validated_data["package_control"]
        document = serializer.validated_data.get("document")
        if row.package not in access.readable_packages(self.request.user):
            raise PermissionDenied("Unknown package.")
        assert_open(row.package)
        if document is None:
            raise ValidationError({"document": "A document is required."})
        access.assert_pinnable(self.request.user, document)
        pinned = pin_document(row, document, self.request.user,
                              link=document.control_links.filter(control=row.control).first(),
                              **{k: serializer.validated_data.get(k) for k in
                                 ("covers_from", "covers_to", "is_population", "evidence_note")})
        serializer.instance = pinned

    def perform_update(self, serializer):
        row = self.get_object()
        if not access.can_assemble(self.request.user):
            raise PermissionDenied("You cannot change this package.")
        assert_open(row.package_control.package)
        serializer.save()

    def perform_destroy(self, instance):
        if not access.can_assemble(self.request.user):
            raise PermissionDenied("You cannot change this package.")
        assert_open(instance.package_control.package)
        instance.delete()

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        """Preview a pinned artefact under the same grant rule as /file/."""
        from documents.views import preview_response

        row = self.get_object()
        if row.document is None or not row.document.file:
            raise ValidationError({"detail": "This evidence file is no longer available."})
        monitor.refuse_if_quarantined(row.document)
        package = row.package_control.package
        grant = access.live_grant(request.user, package)
        if grant is not None:
            PackageGrant.objects.filter(pk=grant.pk).update(
                last_accessed_at=timezone.now(), access_count=grant.access_count + 1)
        record_package_event(
            request, package, "read",
            f"previewed evidence '{row.document_name}' from package {package.pk}",
        )
        return preview_response(request, row.document.file, row.document_name, row.document)

    @action(detail=True, methods=["get"])
    def file(self, request, pk=None):
        """The pinned bytes.

        This is the folder-permission bypass, and the only one. get_queryset()
        has already established that the caller may read this package, which
        for an external auditor means a live grant on a sealed package.
        """
        row = self.get_object()
        if row.document is None or not row.document.file:
            raise ValidationError({"detail": "This evidence file is no longer available."})
        monitor.refuse_if_quarantined(row.document)
        package = row.package_control.package
        grant = access.live_grant(request.user, package)
        if grant is not None:
            PackageGrant.objects.filter(pk=grant.pk).update(
                last_accessed_at=timezone.now(), access_count=grant.access_count + 1)
        record_package_event(
            request, package, "read",
            f"read evidence '{row.document_name}' from package {package.pk}",
        )
        return serve_stored_file(row.document.file, row.document_name)


class PackageGrantViewSet(viewsets.ModelViewSet):
    """Who a package was issued to. Per user, never per role."""
    serializer_class = PackageGrantSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["package"]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        readable = access.readable_packages(user)
        queryset = PackageGrant.objects.filter(package__in=readable).select_related("package")
        if not access.can_assemble(user):
            # A grantee sees their own row, not the rest of the recipient list.
            queryset = queryset.filter(user=user)
        return queryset

    def perform_create(self, serializer):
        from django.conf import settings

        if not access.can_assemble(self.request.user):
            raise PermissionDenied("You need the frameworks capability to issue a package.")
        package = serializer.validated_data["package"]
        if package not in access.readable_packages(self.request.user):
            raise PermissionDenied("Unknown package.")
        if package.status != EvidencePackage.Status.SEALED:
            raise ValidationError(
                {"detail": "Seal the package before issuing it. A grant on a draft would "
                           "widen silently as rows were added."}
            )
        recipient = serializer.validated_data.get("user")
        if recipient is None:
            raise ValidationError({"user": "Name the person this package is issued to."})
        if not recipient.is_active or not recipient.is_auditor:
            raise ValidationError(
                {"user": "Evidence packages can only be issued to an active account "
                         "holding the Auditor role."}
            )
        expires = serializer.validated_data.get("expires_at")
        default_days = getattr(settings, "ATTESTATION_GRANT_DAYS", 45)
        max_days = getattr(settings, "ATTESTATION_GRANT_MAX_DAYS", 180)
        latest = timezone.now() + timezone.timedelta(days=max_days)
        if expires is None:
            expires = timezone.now() + timezone.timedelta(days=default_days)
        if expires <= timezone.now():
            raise ValidationError({"expires_at": "Choose a date in the future."})
        if expires > latest:
            raise ValidationError(
                {"expires_at": f"Access cannot be granted for more than {max_days} days."}
            )
        grant = serializer.save(
            expires_at=expires,
            username=recipient.get_username(),
            full_name=(recipient.get_full_name() or recipient.get_username())[:200],
            email=recipient.email,
            granted_by=self.request.user,
            granted_by_name=(self.request.user.get_full_name()
                             or self.request.user.get_username())[:200],
        )
        record_package_event(self.request, package, "create",
                             f"issued package {package.pk} to {grant.username} "
                             f"until {expires.date().isoformat()}")

    def perform_destroy(self, instance):
        """Revoking is a fact, not an absence: the row stays, marked revoked."""
        if not access.can_assemble(self.request.user):
            raise PermissionDenied("You need the frameworks capability to revoke access.")
        instance.revoked_at = timezone.now()
        instance.revoked_by = self.request.user
        instance.save(update_fields=["revoked_at", "revoked_by"])
        record_package_event(self.request, instance.package, "delete",
                             f"revoked {instance.username}'s access to package {instance.package_id}")
