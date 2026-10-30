import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from accounts import tenancy
from accounts.models import Role
from compliance.models import Control, ControlCategory, ControlMapping, Framework

DATA_DIR = os.path.join(settings.BASE_DIR, "compliance", "data")

DATA_FILES = ["soc2.json", "iso27001.json", "pci_dss_v4.json"]

# The keys crosswalk.json names its lists by; the only controls this command places in a theme.
CORE_FRAMEWORK_KEYS = ("soc2", "iso27001", "pci_dss_v4")

# The Auditor and Viewer descriptions state what accounts/permissions.py allows (USER_GUIDE.md, Roles).
BUILTIN_ROLES = [
    ("Administrator", "Full platform administration.",
     dict(can_manage_users=True, can_manage_frameworks=True, can_manage_documents=True,
          can_manage_folders=True, can_view_all=True)),
    ("Compliance Manager", "Manages frameworks, documents and folders across the org.",
     dict(can_manage_frameworks=True, can_manage_documents=True,
          can_manage_folders=True, can_view_all=True)),
    ("Control Owner", "Owns controls and maintains their evidence.",
     dict(can_manage_documents=True)),
    ("Auditor", "Read-only outside party: packages issued to them, the folders granted with them, and the trail.",
     dict(is_auditor=True)),
    ("Viewer", "Reads the programme-wide records and the folders granted to them; adds "
               "notes to risks and edits the risks they own.", dict()),
]


class Command(BaseCommand):
    help = "Seed frameworks, controls, crosswalk and built-in roles."

    def add_arguments(self, parser):
        parser.add_argument("--with-folders", action="store_true",
                            help="Also create app folders mirroring the control tree.")
        parser.add_argument("--roles-only", action="store_true",
                            help="Seed the built-in roles and nothing else.")
        parser.add_argument("--all-workspaces", action="store_true",
                            help="Every active workspace in turn, not just --workspace. "
                                 "The container entrypoint runs this, so a release that "
                                 "adds a role or a control reaches every organisation on "
                                 "the installation rather than only Default.")
        tenancy.workspace_option(parser)

    def handle(self, *args, **opts):
        if opts.get("all_workspaces"):
            count = 0
            for workspace in tenancy.for_each_workspace():
                # One transaction per workspace: a failure rolls back that organisation alone.
                with transaction.atomic():
                    self._seed_one(workspace, opts)
                count += 1
            self.stdout.write(self.style.SUCCESS(f"Seeding complete in {count} workspace(s)."))
            return
        workspace = tenancy.from_option(opts)
        with tenancy.scoped(workspace), transaction.atomic():
            self._seed_one(workspace, opts)
        self.stdout.write(self.style.SUCCESS("Seeding complete."))

    def _seed_one(self, workspace, opts):
        """Seed the active workspace; idempotent, because the container entrypoint runs it on every boot."""
        self.stdout.write(f"Workspace: {workspace.name} ({workspace.slug})")
        self._seed_roles()
        if opts["roles_only"]:
            self.stdout.write(self.style.SUCCESS("Roles seeded."))
            return
        self._seed_frameworks()
        self._seed_crosswalk()
        if opts["with_folders"]:
            self._seed_folders()

    def _seed_roles(self):
        for name, desc, flags in BUILTIN_ROLES:
            Role.objects.update_or_create(
                name=name, defaults=dict(description=desc, is_system=True, **flags)
            )
        self.stdout.write(f"  Roles: {Role.objects.count()}")

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
                # The file's order is the standard's order (Control.order); every run puts it back.
                for place, control in enumerate(cat["controls"], start=1):
                    # Keyed by (framework, control_id), not category: a moved control is updated, not duplicated.
                    existing = Control.objects.filter(
                        category__framework=fw, control_id=control["control_id"]
                    ).first()
                    if existing:
                        existing.category = category
                        existing.order = place
                        existing.title = control["title"]
                        existing.objective = control.get("objective", "")
                        existing.save(update_fields=["category", "order", "title", "objective"])
                    else:
                        Control.objects.create(
                            category=category, control_id=control["control_id"],
                            order=place, title=control["title"],
                            objective=control.get("objective", ""),
                        )
                    nctrl += 1
                # A hand-added control the file does not list stays after the listed ones.
                listed = [control["control_id"] for control in cat["controls"]]
                rest = (Control.objects.filter(category=category)
                        .exclude(control_id__in=listed).order_by("order", "pk"))
                for place, control in enumerate(rest, start=len(listed) + 1):
                    if control.order != place:
                        control.order = place
                        control.save(update_fields=["order"])
            self.stdout.write(f"  {fw.name} {fw.version}: {ncat} categories, {nctrl} controls")

    def _seed_crosswalk(self):
        path = os.path.join(DATA_DIR, "crosswalk.json")
        if not os.path.exists(path):
            return
        with open(path, encoding="utf-8") as f:
            mappings = json.load(f)["mappings"]

        for m in mappings:
            mapping, _ = ControlMapping.objects.get_or_create(theme=m["theme"])
            # Match per library: a clause number such as "6.2" is not an identity across standards.
            wanted = Q()
            for key in CORE_FRAMEWORK_KEYS:
                ids = m.get(key, [])
                if ids:
                    wanted |= Q(category__framework__key=key, control_id__in=ids)
            controls = list(Control.objects.filter(wanted)) if wanted else []
            # Only the shipped libraries' controls are this command's to add or drop; other libraries' links stay.
            stale = mapping.controls.filter(category__framework__key__in=CORE_FRAMEWORK_KEYS).exclude(
                pk__in=[c.pk for c in controls])
            mapping.controls.remove(*stale)
            mapping.controls.add(*controls)
        self.stdout.write(f"  Crosswalk: {ControlMapping.objects.count()} themes")

    # Windows MAX_PATH is 260 and uploads live under media/documents/<framework>/<category>/<control>/<filename>,
    # so the control segment is capped to leave room for a filename.
    CONTROL_FOLDER_MAX = 70

    @staticmethod
    def _safe_segment(name, limit):
        cleaned = "".join("-" if ch in '/\\:*?"<>|' else ch for ch in name)
        cleaned = cleaned.strip().rstrip(". ")
        if len(cleaned) > limit:
            cleaned = cleaned[:limit].rstrip(". ")
        return cleaned or "unnamed"

    def _sync_folder(self, folder, name, parent, **fields):
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
        from documents.models import Folder

        created = 0
        for fw in Framework.objects.all():
            fw_name = self._safe_segment(str(fw), 80)
            # FK first; the name match adopts a tree seeded before the FK existed, instead of growing a second one.
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
