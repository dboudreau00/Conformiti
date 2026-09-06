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

from accounts import tenancy
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
        parser.add_argument("--roles-only", action="store_true",
                            help="Seed the built-in roles and nothing else.")
        tenancy.workspace_option(parser)

    @transaction.atomic
    def handle(self, *args, **opts):
        workspace = tenancy.from_option(opts)
        self.stdout.write(f"Workspace: {workspace.name} ({workspace.slug})")
        with tenancy.scoped(workspace):
            self._seed_roles()
            if opts["roles_only"]:
                self.stdout.write(self.style.SUCCESS("Roles seeded."))
                return
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
                    # Identify the control by (framework, control_id), not by
                    # (category, control_id): a control that moves to another
                    # category must be *updated*, not duplicated as a second row
                    # that keeps the old owner, status and evidence links.
                    existing = Control.objects.filter(
                        category__framework=fw, control_id=control["control_id"]
                    ).first()
                    if existing:
                        existing.category = category
                        existing.title = control["title"]
                        existing.objective = control.get("objective", "")
                        existing.save(update_fields=["category", "title", "objective"])
                    else:
                        Control.objects.create(
                            category=category, control_id=control["control_id"],
                            title=control["title"],
                            objective=control.get("objective", ""),
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
    # Windows' default MAX_PATH is 260 characters and uploads are stored under
    # media/documents/<framework>/<category>/<control>/<filename>, so the control
    # segment is capped to leave room for a real filename.
    CONTROL_FOLDER_MAX = 70

    @staticmethod
    def _safe_segment(name, limit):
        """A folder name that is safe as a single path segment: no separators or
        other characters Windows rejects, no trailing dot/space, length-capped."""
        cleaned = "".join("-" if ch in '/\\:*?"<>|' else ch for ch in name)
        cleaned = cleaned.strip().rstrip(". ")
        if len(cleaned) > limit:
            cleaned = cleaned[:limit].rstrip(". ")
        return cleaned or "unnamed"

    def _sync_folder(self, folder, name, parent, **fields):
        """Rename/re-parent an existing folder instead of creating a duplicate."""
        changed = []
        if folder.name != name:
            folder.name = name
            changed.append("name")
        if folder.parent_id != (parent.id if parent else None):
            folder.parent = parent
            changed.append("parent")
        for k, v in fields.items():
            if getattr(folder, k) != v:
                setattr(folder, k, v)
                changed.append(k)
        if changed:
            folder.save(update_fields=changed)
        return folder

    def _seed_folders(self):
        # Imported lazily so the command still loads if documents app changes.
        from documents.models import Folder

        created = 0
        for fw in Framework.objects.all():
            fw_name = self._safe_segment(str(fw), 80)
            # Look the root up by its Framework FK. Fall back to the legacy
            # name match once, so installs seeded before the FK existed adopt
            # their existing tree instead of growing a second one.
            fw_folder = Folder.objects.filter(framework=fw).first()
            if fw_folder is None:
                fw_folder = Folder.objects.filter(
                    parent=None, is_framework_root=True, name=fw_name
                ).first() or Folder.objects.filter(parent=None, name=str(fw)).first()
            if fw_folder is None:
                fw_folder = Folder.objects.create(
                    name=fw_name, parent=None, is_framework_root=True, framework=fw
                )
                created += 1
            else:
                self._sync_folder(fw_folder, fw_name, None,
                                  is_framework_root=True, framework=fw)

            for cat in fw.categories.all():
                cat_name = self._safe_segment(cat.name, 80)
                cat_folder = Folder.objects.filter(category=cat).first()
                if cat_folder is None:
                    cat_folder = Folder.objects.filter(parent=fw_folder, name=cat_name).first() \
                        or Folder.objects.filter(parent=fw_folder, name=cat.name).first()
                if cat_folder is None:
                    cat_folder = Folder.objects.create(
                        name=cat_name, parent=fw_folder, category=cat
                    )
                    created += 1
                else:
                    self._sync_folder(cat_folder, cat_name, fw_folder, category=cat)

                for control in cat.controls.all():
                    ctl_name = self._safe_segment(
                        f"{control.control_id} - {control.title}", self.CONTROL_FOLDER_MAX
                    )
                    ctl_folder = Folder.objects.filter(control=control).first()
                    if ctl_folder is None:
                        ctl_folder = Folder.objects.filter(
                            parent=cat_folder, name=ctl_name
                        ).first()
                    if ctl_folder is None:
                        Folder.objects.create(
                            name=ctl_name, parent=cat_folder, control=control
                        )
                        created += 1
                    else:
                        self._sync_folder(ctl_folder, ctl_name, cat_folder, control=control)
        self.stdout.write(f"  App folders created: {created}")
