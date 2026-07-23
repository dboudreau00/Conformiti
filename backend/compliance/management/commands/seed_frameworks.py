"""
Seed frameworks, controls, the cross-framework crosswalk, and built-in roles.

    python manage.py seed_frameworks                # idempotent import
    python manage.py seed_frameworks --with-folders # also mirror the control
                                                    # tree into app folders
"""
import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import Role
from compliance.models import Control, ControlCategory, ControlMapping, Framework

DATA_DIR = os.path.join(settings.BASE_DIR, "compliance", "data")

DATA_FILES = ["soc2.json", "iso27001.json", "pci_dss_v4.json"]

# Built-in roles and their capability flags.
BUILTIN_ROLES = [
    ("Administrator", "Full platform administration.",
     dict(can_manage_users=True, can_manage_frameworks=True, can_manage_documents=True,
          can_manage_folders=True, can_view_all=True)),
    ("Compliance Manager", "Manages frameworks, documents and folders across the org.",
     dict(can_manage_frameworks=True, can_manage_documents=True,
          can_manage_folders=True, can_view_all=True)),
    ("Control Owner", "Owns controls and maintains their evidence.",
     dict(can_manage_documents=True)),
    ("Auditor", "Read-only external auditor; sees only granted folders.",
     dict(is_auditor=True)),
    ("Viewer", "Read-only access to granted folders.", dict()),
]


class Command(BaseCommand):
    help = "Seed frameworks, controls, crosswalk and built-in roles."

    def add_arguments(self, parser):
        parser.add_argument("--with-folders", action="store_true",
                            help="Also create app folders mirroring the control tree.")

    @transaction.atomic
    def handle(self, *args, **opts):
        self._seed_roles()
        self._seed_frameworks()
        self._seed_crosswalk()
        if opts["with_folders"]:
            self._seed_folders()
        self.stdout.write(self.style.SUCCESS("Seeding complete."))

    # ------------------------------------------------------------------ roles
    def _seed_roles(self):
        for name, desc, flags in BUILTIN_ROLES:
            Role.objects.update_or_create(
                name=name, defaults=dict(description=desc, is_system=True, **flags)
            )
        self.stdout.write(f"  Roles: {Role.objects.count()}")

    # ------------------------------------------------------------- frameworks
    def _seed_frameworks(self):
        for fname in DATA_FILES:
            path = os.path.join(DATA_DIR, fname)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)

            fw, _ = Framework.objects.update_or_create(
                key=data["key"],
                defaults=dict(
                    name=data["name"], version=data["version"],
                    authority=data.get("authority", ""),
                    description=data.get("description", ""),
                ),
            )
            ncat = nctrl = 0
            for order, cat in enumerate(data["categories"]):
                category, _ = ControlCategory.objects.update_or_create(
                    framework=fw, key=cat["key"],
                    defaults=dict(name=cat["name"], order=order),
                )
                ncat += 1
                for control in cat["controls"]:
                    Control.objects.update_or_create(
                        category=category, control_id=control["control_id"],
                        defaults=dict(title=control["title"],
                                      objective=control.get("objective", "")),
                    )
                    nctrl += 1
            self.stdout.write(f"  {fw.name} {fw.version}: {ncat} categories, {nctrl} controls")

    # -------------------------------------------------------------- crosswalk
    def _seed_crosswalk(self):
        path = os.path.join(DATA_DIR, "crosswalk.json")
        if not os.path.exists(path):
            return
        with open(path, encoding="utf-8") as f:
            mappings = json.load(f)["mappings"]

        for m in mappings:
            mapping, _ = ControlMapping.objects.get_or_create(theme=m["theme"])
            control_ids = m.get("soc2", []) + m.get("iso27001", []) + m.get("pci_dss_v4", [])
            controls = Control.objects.filter(control_id__in=control_ids)
            mapping.controls.set(controls)
        self.stdout.write(f"  Crosswalk: {ControlMapping.objects.count()} themes")

    # ---------------------------------------------------------------- folders
    def _seed_folders(self):
        # Imported lazily so the command still loads if documents app changes.
        from documents.models import Folder

        created = 0
        for fw in Framework.objects.all():
            fw_folder, made = Folder.objects.get_or_create(
                name=str(fw), parent=None, defaults={"is_framework_root": True}
            )
            created += made
            for cat in fw.categories.all():
                cat_folder, made = Folder.objects.get_or_create(name=cat.name, parent=fw_folder)
                created += made
                for control in cat.controls.all():
                    _, made = Folder.objects.get_or_create(
                        name=f"{control.control_id} - {control.title}",
                        parent=cat_folder, defaults={"control": control},
                    )
                    created += made
        self.stdout.write(f"  App folders created: {created}")
