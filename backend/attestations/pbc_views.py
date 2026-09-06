"""
The PBC request list: what the auditor asked for, who owes it, and what came back.

Who may do what, in one place:

* raise a request: the organisation (frameworks capability) on any package
  that is not withdrawn; the issued auditor (live grant) on a sealed one;
* edit the line (title, due date, assignee, control): the organisation, or
  the auditor for lines they raised while still open;
* answer it (attach documents, mark provided): the organisation, or the
  assignee -- who may be a control owner with no package access at all, and
  who therefore sees exactly their own lines and nothing else of the package;
* accept or return an answer: the issued auditor, or the organisation when it
  is closing a line it transcribed from the auditor's email;
* read an attached document: anyone who can read the package, plus the
  assignee. For the auditor this is the second folder-permission bypass in
  the product, and ``access.py`` holds it beside the first.
"""
import csv

from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from audit.events import record_package_event
from documents import monitor
from documents.access import accessible_folder_ids
from documents.downloads import serve_stored_file
from notifications import webhooks

from . import access
from .models import EvidencePackage, PackageGrant, PbcItem, PbcRequest
from .serializers import PbcItemSerializer, PbcRequestSerializer
from .snapshot import digest_and_size, stamp


def _name(user):
    return (user.get_full_name() or user.get_username())[:200]


def _side(user, package):
    """Which side of the table the caller sits on for this package."""
    if access.live_grant(user, package) is not None:
        return PbcRequest.Side.AUDITOR
    if access.can_assemble(user):
        return PbcRequest.Side.ORGANISATION
    return None


class PbcRequestViewSet(viewsets.ModelViewSet):
    serializer_class = PbcRequestSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["package", "status", "assignee", "priority"]
    search_fields = ["reference", "title", "description", "control_ref"]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = access.readable_pbc_requests(self.request.user)
        if self.request.query_params.get("mine") in ("1", "true"):
            qs = qs.filter(assignee=self.request.user)
        return qs.select_related("package", "assignee", "package_control").prefetch_related("items")

    # ------------------------------------------------------------- create
    def perform_create(self, serializer):
        user = self.request.user
        data = serializer.validated_data
        package = data["package"]
        if package not in access.readable_packages(user):
            raise PermissionDenied("Unknown package.")
        if package.status == EvidencePackage.Status.WITHDRAWN:
            raise ValidationError({"detail": "This package is withdrawn; its request list is closed."})
        side = _side(user, package)
        if side is None:
            raise PermissionDenied("You need the frameworks capability, or a live grant on this "
                                   "package, to raise a request.")
        row = data.get("package_control")
        if row is not None and row.package_id != package.pk:
            raise ValidationError({"package_control": "Pick a control in this package."})
        assignee = data.get("assignee")
        for attempt in range(3):
            ordinal = (package.pbc_requests.order_by("-ordinal").values_list("ordinal", flat=True).first() or 0) + 1
            try:
                with transaction.atomic():
                    req = serializer.save(
                        ordinal=ordinal, reference=f"PBC-{ordinal:02d}",
                        control_ref=row.control_ref if row else "",
                        assignee_name=_name(assignee) if assignee else "",
                        requested_by=user, requested_by_name=_name(user), requested_by_side=side,
                    )
                break
            except IntegrityError:
                if attempt == 2:
                    raise
        record_package_event(self.request, package, "create",
                             f"{req.reference} raised by the {side}: {req.title[:120]}")
        if side == PbcRequest.Side.AUDITOR:
            webhooks.post_event(
                "pbc.raised", f"Auditor request {req.reference}: {req.title}",
                f"Raised by {req.requested_by_name} in {package.name}."
                f"{' Due ' + req.due_date.isoformat() + '.' if req.due_date else ''}",
                facts=[("Assigned to", req.assignee_name or "nobody yet"), ("Control", req.control_ref or "—")],
                path="/packages", severity="medium")

    # ------------------------------------------------------------- update
    EDITABLE = {"title", "description", "package_control", "priority", "due_date", "assignee"}

    def perform_update(self, serializer):
        req = self.get_object()
        user = self.request.user
        data = serializer.validated_data
        touched = set(data) & self.EDITABLE
        # Read-only fields would be dropped silently by the serializer; say so
        # instead, so a client that PATCHes `status` learns to use the actions.
        stray = set(getattr(self.request.data, "keys", lambda: [])()) - self.EDITABLE
        if stray:
            raise ValidationError({"detail": "Only the line itself can be edited here "
                                             f"({', '.join(sorted(stray))} cannot be set); use the "
                                             "actions to provide, accept, return or withdraw."})
        if req.package.status == EvidencePackage.Status.WITHDRAWN:
            raise ValidationError({"detail": "This package is withdrawn; its request list is closed."})
        if not self._may_edit(user, req):
            raise PermissionDenied("You cannot change this request.")
        extra = {}
        if "package_control" in data:
            row = data.get("package_control")
            if row is not None and row.package_id != req.package_id:
                raise ValidationError({"package_control": "Pick a control in this package."})
            extra["control_ref"] = row.control_ref if row else ""
        if "assignee" in data:
            extra["assignee_name"] = _name(data["assignee"]) if data.get("assignee") else ""
        if "due_date" in data and data.get("due_date") != req.due_date:
            extra["reminders_sent"] = []      # a new date is a new clock
        serializer.save(**extra)
        if touched:
            record_package_event(self.request, req.package, "update",
                                 f"{req.reference} edited: {', '.join(sorted(touched))}")

    @staticmethod
    def _may_edit(user, req):
        if access.can_assemble(user):
            return True
        grant = access.live_grant(user, req.package)
        return (grant is not None and req.requested_by_id == user.pk
                and req.status in (PbcRequest.Status.OPEN, PbcRequest.Status.RETURNED))

    def perform_destroy(self, instance):
        raise ValidationError({"detail": "Requests are withdrawn, not deleted; the list is a record."})

    # ------------------------------------------------------------- actions
    @action(detail=True, methods=["post"])
    def provide(self, request, pk=None):
        """Mark the answer given. Needs at least one attached document or a
        note saying why there is none."""
        req = self.get_object()
        user = request.user
        if not (access.can_assemble(user) or req.assignee_id == user.pk):
            raise PermissionDenied("Only the organisation, or the person this request is assigned to, "
                                   "can answer it.")
        if not req.is_actionable:
            raise ValidationError({"detail": f"This request is {req.get_status_display().lower()}."})
        note = str(request.data.get("response_note") or "").strip()[:4000]
        if not note and not req.items.exists():
            raise ValidationError({"response_note": "Attach a document, or say why nothing is attached."})
        req.response_note = note
        req.status = PbcRequest.Status.PROVIDED
        stamp(req, user, "provided")
        req.save()
        record_package_event(request, req.package, "update",
                             f"{req.reference} provided by {_name(user)} ({req.items.count()} item(s))")
        return Response(self.get_serializer(req).data)

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        req = self.get_object()
        if not self._may_judge(request.user, req):
            raise PermissionDenied("Only the issued auditor, or the organisation closing a transcribed "
                                   "request, can accept an answer.")
        if req.status != PbcRequest.Status.PROVIDED:
            raise ValidationError({"detail": "Only a provided request can be accepted."})
        req.status = PbcRequest.Status.ACCEPTED
        stamp(req, request.user, "accepted")
        req.save()
        record_package_event(request, req.package, "update",
                             f"{req.reference} accepted by {_name(request.user)}")
        return Response(self.get_serializer(req).data)

    @action(detail=True, methods=["post"], url_path="return")
    def return_(self, request, pk=None):
        req = self.get_object()
        if not self._may_judge(request.user, req):
            raise PermissionDenied("Only the issued auditor, or the organisation, can return an answer.")
        if req.status != PbcRequest.Status.PROVIDED:
            raise ValidationError({"detail": "Only a provided request can be returned."})
        note = str(request.data.get("returned_note") or "").strip()[:4000]
        if not note:
            raise ValidationError({"returned_note": "Say what is missing or wrong."})
        req.returned_note = note
        req.returned_at = timezone.now()
        req.status = PbcRequest.Status.RETURNED
        req.reminders_sent = []
        req.save()
        record_package_event(request, req.package, "update",
                             f"{req.reference} returned by {_name(request.user)}: {note[:100]}")
        webhooks.post_event(
            "pbc.returned", f"Returned by the auditor: {req.reference} {req.title}",
            f"{_name(request.user)} returned the answer in {req.package.name}: {note[:300]}",
            facts=[("Assigned to", req.assignee_name or "nobody yet")],
            path="/packages", severity="high")
        return Response(self.get_serializer(req).data)

    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        req = self.get_object()
        user = request.user
        own = access.live_grant(user, req.package) is not None and req.requested_by_id == user.pk
        if not (access.can_assemble(user) or own):
            raise PermissionDenied("Only the organisation, or the auditor who raised it, can withdraw a request.")
        if req.status in (PbcRequest.Status.ACCEPTED, PbcRequest.Status.WITHDRAWN):
            raise ValidationError({"detail": f"This request is already {req.get_status_display().lower()}."})
        req.status = PbcRequest.Status.WITHDRAWN
        req.withdrawn_at = timezone.now()
        req.save(update_fields=["status", "withdrawn_at", "updated_at"])
        record_package_event(request, req.package, "update",
                             f"{req.reference} withdrawn by {_name(user)}")
        return Response(self.get_serializer(req).data)

    @staticmethod
    def _may_judge(user, req):
        return access.live_grant(user, req.package) is not None or access.can_assemble(user)

    @action(detail=False, methods=["get"])
    def export(self, request):
        """The list as CSV, for the auditor's own tracker."""
        from config.csvsafe import csv_safe

        rows = self.filter_queryset(self.get_queryset())
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="pbc-requests.csv"'
        writer = csv.writer(response)
        writer.writerow(["Package", "Reference", "Title", "Control", "Priority", "Status", "Due",
                         "Assignee", "Raised by", "Side", "Provided", "Items", "Accepted", "Note"])
        for r in rows:
            writer.writerow(csv_safe([
                r.package.name, r.reference, r.title, r.control_ref, r.get_priority_display(),
                r.get_status_display(), r.due_date or "", r.assignee_name, r.requested_by_name,
                r.get_requested_by_side_display(), r.provided_at.date() if r.provided_at else "",
                "; ".join(i.document_name for i in r.items.all()),
                r.accepted_at.date() if r.accepted_at else "",
                r.returned_note if r.status == "returned" else r.response_note,
            ]))
        return response


class PbcItemViewSet(viewsets.ModelViewSet):
    """Documents attached in answer to a request."""
    serializer_class = PbcItemSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["request"]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        return PbcItem.objects.filter(
            request__in=access.readable_pbc_requests(self.request.user)
        ).select_related("request__package", "document")

    @staticmethod
    def _may_answer(user, req):
        return access.can_assemble(user) or req.assignee_id == user.pk

    def perform_create(self, serializer):
        user = self.request.user
        req = serializer.validated_data["request"]
        document = serializer.validated_data.get("document")
        if req not in access.readable_pbc_requests(user):
            raise PermissionDenied("Unknown request.")
        if not self._may_answer(user, req):
            raise PermissionDenied("Only the organisation, or the person this request is assigned to, "
                                   "can attach documents to it.")
        if req.package.status == EvidencePackage.Status.WITHDRAWN:
            raise ValidationError({"detail": "This package is withdrawn; its request list is closed."})
        if req.status in (PbcRequest.Status.ACCEPTED, PbcRequest.Status.WITHDRAWN):
            raise ValidationError({"detail": f"This request is {req.get_status_display().lower()}."})
        if document is None:
            raise ValidationError({"document": "A document is required."})
        # You cannot hand over what you cannot see -- the same rule as pinning.
        if document.folder_id not in accessible_folder_ids(user):
            raise PermissionDenied("You can only attach documents from folders you can already see.")
        if req.items.filter(document=document).exists():
            raise ValidationError({"document": "Already attached to this request."})
        sha, size = digest_and_size(document.file)
        item = serializer.save(
            document_name=document.name[:255], version=document.version, size_bytes=size,
            content_sha256=sha or "", attached_by=user, attached_by_name=_name(user),
        )
        record_package_event(self.request, req.package, "update",
                             f"{req.reference}: attached '{item.document_name}' v{item.version}")

    def perform_destroy(self, instance):
        req = instance.request
        if not self._may_answer(self.request.user, req):
            raise PermissionDenied("You cannot change this request's answer.")
        if req.status in (PbcRequest.Status.ACCEPTED, PbcRequest.Status.WITHDRAWN):
            raise ValidationError({"detail": f"This request is {req.get_status_display().lower()}."})
        record_package_event(self.request, req.package, "update",
                             f"{req.reference}: detached '{instance.document_name}'")
        instance.delete()

    def _touch_grant(self, request, package):
        grant = access.live_grant(request.user, package)
        if grant is not None:
            PackageGrant.objects.filter(pk=grant.pk).update(
                last_accessed_at=timezone.now(), access_count=grant.access_count + 1)

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        from documents.views import preview_response

        item = self.get_object()
        if item.document is None or not item.document.file:
            raise ValidationError({"detail": "This file is no longer available."})
        monitor.refuse_if_quarantined(item.document)
        package = item.request.package
        self._touch_grant(request, package)
        record_package_event(request, package, "read",
                             f"previewed '{item.document_name}' from {item.request.reference} in package {package.pk}")
        return preview_response(request, item.document.file, item.document_name, item.document)

    @action(detail=True, methods=["get"])
    def file(self, request, pk=None):
        item = self.get_object()
        if item.document is None or not item.document.file:
            raise ValidationError({"detail": "This file is no longer available."})
        monitor.refuse_if_quarantined(item.document)
        package = item.request.package
        self._touch_grant(request, package)
        record_package_event(request, package, "read",
                             f"read '{item.document_name}' from {item.request.reference} in package {package.pk}")
        return serve_stored_file(item.document.file, item.document_name)
