"""
Responsibility matrices: who is Responsible, Accountable, Consulted and
Informed for each control — including when "who" is a vendor.

Two things this settles that a control's single ``owner`` field cannot:

* **Shared responsibility.** Under SOC 2 or PCI DSS a control like physical
  security is *Responsible*: the cloud provider, *Accountable*: us. An auditor
  asks for exactly that split, and the answer has to name the vendor and point
  at the assurance we hold over them.
* **One Accountable.** RACI's only hard rule. The API refuses a second
  Accountable party on a control rather than letting the matrix drift into
  "everyone and no one".
"""
import csv

from django.db.models import Prefetch
from django.http import HttpResponse
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from accounts.permissions import CanManageFrameworks

from .models import Control, Responsibility

ROLES = ["responsible", "accountable", "consulted", "informed"]


class ResponsibilitySerializer(serializers.ModelSerializer):
    party_name = serializers.SerializerMethodField()
    party_kind = serializers.SerializerMethodField()
    control_label = serializers.CharField(source="control.control_id", read_only=True)
    control_title = serializers.CharField(source="control.title", read_only=True)
    framework_key = serializers.CharField(source="control.category.framework.key", read_only=True)
    role_display = serializers.CharField(source="get_role_display", read_only=True)

    class Meta:
        model = Responsibility
        fields = [
            "id", "control", "control_label", "control_title", "framework_key",
            "user", "vendor", "party_kind", "party_name", "role", "role_display",
            "note", "created_at",
        ]

    def get_party_kind(self, obj):
        return "vendor" if obj.vendor_id else "user"

    def get_party_name(self, obj):
        if obj.vendor_id:
            return obj.vendor.name
        return obj.user.get_full_name() or obj.user.get_username() if obj.user_id else ""

    def validate(self, attrs):
        # On a PATCH the party is usually not re-sent; judge the merged row,
        # so a note-only edit passes and a switch of party kind that would
        # leave both set is refused here rather than by the database.
        inst = self.instance
        user = attrs["user"] if "user" in attrs else (inst.user if inst is not None else None)
        vendor = attrs["vendor"] if "vendor" in attrs else (inst.vendor if inst is not None else None)
        if bool(user) == bool(vendor):
            raise ValidationError({"party": "Name exactly one of user or vendor "
                                            "(clear the other when switching)."})
        control = attrs.get("control") or getattr(self.instance, "control", None)
        role = attrs.get("role") or getattr(self.instance, "role", None)
        if role == Responsibility.Role.ACCOUNTABLE and control is not None:
            clash = Responsibility.objects.filter(
                control=control, role=Responsibility.Role.ACCOUNTABLE)
            if self.instance is not None:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise ValidationError({"role": (
                    "This control already has an Accountable party. RACI allows exactly "
                    "one; reassign it rather than adding a second."
                )})
        return attrs


class ResponsibilityViewSet(viewsets.ModelViewSet):
    queryset = Responsibility.objects.select_related(
        "control__category__framework", "user", "vendor")
    serializer_class = ResponsibilitySerializer
    permission_classes = [CanManageFrameworks]
    filterset_fields = ["control", "user", "vendor", "role", "control__category__framework__key"]

    @action(detail=False, methods=["get"])
    def matrix(self, request):
        """The grid: one row per control, one cell per RACI role.

        The control's ``owner`` is shown as Accountable when no explicit
        Accountable row exists, so a register that predates matrices is not
        suddenly empty in the A column.
        """
        controls = Control.objects.select_related("category__framework", "owner")
        framework = request.query_params.get("framework")
        if framework:
            controls = controls.filter(category__framework__key=framework)
        search = request.query_params.get("search")
        if search:
            controls = controls.filter(control_id__icontains=search) | controls.filter(title__icontains=search)
        from vendors.models import SharedResponsibility
        controls = controls.prefetch_related(
            Prefetch("responsibilities",
                     queryset=Responsibility.objects.select_related("user", "vendor")),
            Prefetch("shared_responsibilities",
                     queryset=SharedResponsibility.objects.filter(
                         responsibility__in=("provider", "shared")
                     ).select_related("vendor")),
        ).order_by("category__framework__name", "category__order", "control_id")

        rows = []
        gaps = {"no_accountable": 0, "no_responsible": 0}
        for c in controls:
            cells = {role: [] for role in ROLES}
            for r in c.responsibilities.all():
                cells[r.role].append({
                    "id": r.pk,
                    "kind": "vendor" if r.vendor_id else "user",
                    "party_id": r.vendor_id or r.user_id,
                    "name": r.vendor.name if r.vendor_id else (r.user.get_full_name() or r.user.get_username()),
                    "note": r.note,
                })
            # A vendor that states it does (or shares) this control is
            # Responsible for it, whether or not anyone typed a RACI row.
            already = {(x["kind"], x["party_id"]) for x in cells["responsible"]}
            for sr in c.shared_responsibilities.all():
                if ("vendor", sr.vendor_id) in already:
                    continue
                cells["responsible"].append({
                    "id": None, "kind": "vendor", "party_id": sr.vendor_id,
                    "name": sr.vendor.name,
                    "note": "shared responsibility matrix" if sr.responsibility == "shared"
                            else "provider responsibility", "implicit": True,
                })
            implicit_owner = None
            if not cells["accountable"] and c.owner_id:
                implicit_owner = {
                    "id": None, "kind": "user", "party_id": c.owner_id,
                    "name": c.owner.get_full_name() or c.owner.get_username(),
                    "note": "control owner", "implicit": True,
                }
                cells["accountable"].append(implicit_owner)
            if not cells["accountable"]:
                gaps["no_accountable"] += 1
            if not cells["responsible"]:
                gaps["no_responsible"] += 1
            rows.append({
                "control": c.pk, "control_id": c.control_id, "title": c.title,
                "framework": c.category.framework.key,
                "category": c.category.name, "status": c.status,
                "shared": any(x["kind"] == "vendor" for x in cells["responsible"]),
                **cells,
            })
        return Response({"rows": rows, "count": len(rows), "gaps": gaps})

    @action(detail=False, methods=["get"])
    def export(self, request):
        from config.csvsafe import csv_safe

        data = self.matrix(request).data
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="responsibility-matrix.csv"'
        writer = csv.writer(response)
        writer.writerow(["Framework", "Control ID", "Title", "Status", "Shared with vendor",
                         "Responsible", "Accountable", "Consulted", "Informed"])
        for row in data["rows"]:
            names = lambda role: "; ".join(
                f"{x['name']} (vendor)" if x["kind"] == "vendor" else x["name"] for x in row[role])
            writer.writerow(csv_safe([
                row["framework"], row["control_id"], row["title"], row["status"],
                "yes" if row["shared"] else "no",
                names("responsible"), names("accountable"), names("consulted"), names("informed"),
            ]))
        return response
