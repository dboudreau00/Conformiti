"""Shared fixtures for the test suite.

Tests build a *small* hand-made framework (one framework, one category, two
controls, the matching folder spine) rather than seeding the full 217-control
library, so a class-level fixture costs milliseconds. Suites that specifically
exercise the seed commands call them explicitly.
"""
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Role
from compliance.management.commands.seed_frameworks import BUILTIN_ROLES
from compliance.models import Control, ControlCategory, Framework
from documents.models import EDIT, MANAGE, VIEW, Document, Folder, FolderPermission  # noqa: F401

PASSWORD = "Correct-Horse-Battery-9"
User = get_user_model()


def make_roles():
    roles = {}
    for name, desc, flags in BUILTIN_ROLES:
        roles[name], _ = Role.objects.update_or_create(
            name=name, defaults=dict(description=desc, is_system=True, **flags)
        )
    return roles


def make_user(username, role=None, superuser=False, password=PASSWORD, **extra):
    user = User(
        username=username, email=extra.pop("email", f"{username}@test.local"),
        first_name=extra.pop("first_name", username.title()), last_name=extra.pop("last_name", "Tester"),
        role=role, is_superuser=superuser, is_staff=superuser, **extra,
    )
    user.set_password(password)
    user.save()
    return user


class Tree:
    """The folder spine for one framework: root → category → control(s)."""

    def __init__(self):
        self.framework = Framework.objects.create(key="tfw", name="Test Framework", version="1.0")
        self.category = ControlCategory.objects.create(
            framework=self.framework, key="TC", name="TC - Test Category", order=0
        )
        self.c1 = Control.objects.create(category=self.category, control_id="TC1.1", title="First control")
        self.c2 = Control.objects.create(category=self.category, control_id="TC1.2", title="Second control")
        self.root = Folder.objects.create(name="Test Framework 1.0", is_framework_root=True, framework=self.framework)
        self.cat = Folder.objects.create(name="TC - Test Category", parent=self.root, category=self.category)
        self.ctrl1 = Folder.objects.create(name="TC1.1 - First control", parent=self.cat, control=self.c1)
        self.ctrl2 = Folder.objects.create(name="TC1.2 - Second control", parent=self.cat, control=self.c2)


def make_doc(folder, owner, name="Policy", cadence="annual", days=30, content=b"policy text"):
    doc = Document(folder=folder, name=name, owner=owner, created_by=owner,
                   review_cadence=cadence, status=Document.Status.APPROVED, control=folder.control)
    doc.file.save(f"{name}.txt", ContentFile(content), save=False)
    doc.next_review_date = timezone.localdate() + timezone.timedelta(days=days)
    doc.save()
    return doc


def grant(folder, role=None, user=None, level=VIEW):
    return FolderPermission.objects.create(folder=folder, role=role, user=user, access_level=level)


class APITestBase(TestCase):
    """TestCase with a throwaway MEDIA_ROOT, cleared throttle cache, roles,
    the standard five personas and a small folder tree."""

    @classmethod
    def setUpClass(cls):
        cls._media = tempfile.mkdtemp(prefix="conformiti-test-media-")
        cls._override = override_settings(MEDIA_ROOT=cls._media)
        cls._override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        cls.roles = make_roles()
        cls.admin = make_user("ada", cls.roles["Administrator"], superuser=True)
        cls.manager = make_user("mia", cls.roles["Compliance Manager"])
        cls.owner = make_user("owen", cls.roles["Control Owner"])
        cls.auditor = make_user("aria", cls.roles["Auditor"])
        cls.viewer = make_user("val", cls.roles["Viewer"])
        cls.tree = Tree()

    def setUp(self):
        cache.clear()

    @staticmethod
    def client_for(user=None):
        c = APIClient()
        if user is not None:
            c.force_authenticate(user)
        return c
