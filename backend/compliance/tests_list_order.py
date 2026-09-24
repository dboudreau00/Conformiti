"""Paged registers carry an ORDER BY that ends in a unique id.

The control, risk, vendor and evidence-package lists annotate counts, which
makes them GROUP BY queries, and Django drops Meta.ordering from those. The
folder-permission model has no Meta.ordering at all. Unordered, each page is a
LIMIT/OFFSET over rows PostgreSQL may return in any order, so a register built
from several pages can repeat one row and skip another. Each viewset now
orders its own queryset: Meta.ordering (where there is one), then the id.

The page size is patched down to 2 so a handful of rows spans several pages,
and Django's UnorderedObjectListWarning is raised as an error while paging.
"""
import warnings
from datetime import timedelta
from unittest import mock

from django.core.paginator import UnorderedObjectListWarning
from rest_framework.pagination import PageNumberPagination
from rest_framework.test import APIRequestFactory, force_authenticate

from attestations.models import EvidencePackage
from attestations.views import EvidencePackageViewSet
from compliance.models import Control, ControlCategory, Framework
from compliance.views import ControlViewSet
from documents.models import EDIT, MANAGE, VIEW
from documents.views import FolderPermissionViewSet
from governance.models import Risk
from governance.views import RiskViewSet
from testutils import APITestBase, grant
from vendors.models import Vendor
from vendors.views import VendorViewSet

PAGE = 2


def list_queryset(viewset, user):
    """The queryset a list request would paginate, filters applied."""
    request = APIRequestFactory().get("/")
    force_authenticate(request, user=user)
    view = viewset(action_map={"get": "list"})
    view.request = view.initialize_request(request)
    view.format_kwarg = None
    view.action = "list"
    view.args, view.kwargs = (), {}
    return view.filter_queryset(view.get_queryset())


class ListOrderTests(APITestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Controls: a second framework whose name sorts first, and controls
        # created out of their places, whose ids also sort wrongly as text
        # (AA.10 before AA.2), so Meta.ordering has something to do.
        alpha = Framework.objects.create(key="alpha", name="Alpha Framework", version="1")
        cat = ControlCategory.objects.create(framework=alpha, key="AA", name="AA", order=0)
        for control_id, place in (("AA.10", 3), ("AA.1", 1), ("AA.2", 2)):
            Control.objects.create(category=cat, control_id=control_id, title=control_id, order=place)

        # Risks and packages: three rows share one timestamp, so only the id
        # separates them.
        risks = [Risk.objects.create(title=f"Risk {n}") for n in range(5)]
        stamp = risks[0].created_at
        Risk.objects.filter(pk__in=[r.pk for r in risks[:3]]).update(created_at=stamp)
        Risk.objects.filter(pk=risks[3].pk).update(created_at=stamp - timedelta(hours=1))
        Risk.objects.filter(pk=risks[4].pk).update(created_at=stamp + timedelta(hours=1))
        packages = [EvidencePackage.objects.create(name=f"Package {n}", created_by=cls.manager)
                    for n in range(5)]
        EvidencePackage.objects.filter(pk__in=[p.pk for p in packages[:3]]).update(
            created_at=packages[0].created_at)

        for name in ("Zeta Hosting", "Acme Payroll", "Midway Identity", "Beta Mail", "Kappa Backup"):
            Vendor.objects.create(name=name)

        tree = cls.tree
        grant(tree.ctrl2, user=cls.viewer, level=VIEW)
        grant(tree.root, user=cls.owner, level=MANAGE)
        grant(tree.ctrl1, user=cls.viewer, level=EDIT)
        grant(tree.cat, role=cls.roles["Viewer"], level=VIEW)
        grant(tree.ctrl1, role=cls.roles["Control Owner"], level=VIEW)

    CASES = (
        # (route, viewset, expected order of the whole list)
        ("/api/controls/", ControlViewSet, ("category", "order", "control_id", "id")),
        ("/api/risks/", RiskViewSet, ("-created_at", "-id")),
        ("/api/vendors/", VendorViewSet, ("name", "id")),
        ("/api/folder-permissions/", FolderPermissionViewSet, ("id",)),
        ("/api/evidence-packages/", EvidencePackageViewSet, ("-created_at", "-id")),
    )

    def page_through(self, route):
        """Every id the list returns, page by page, with an unordered page an
        error rather than a warning."""
        client = self.client_for(self.admin)
        ids, page = [], 1
        with warnings.catch_warnings(), mock.patch.object(PageNumberPagination, "page_size", PAGE):
            warnings.simplefilter("error", UnorderedObjectListWarning)
            while True:
                r = client.get(route, {"page": page})
                self.assertEqual(r.status_code, 200, r.data)
                ids += [row["id"] for row in r.data["results"]]
                if not r.data["next"]:
                    return ids, r.data["count"]
                page += 1

    def test_each_list_queryset_is_ordered_and_ends_in_the_id(self):
        for route, viewset, _ in self.CASES:
            with self.subTest(route=route):
                qs = list_queryset(viewset, self.admin)
                self.assertTrue(qs.ordered, f"{viewset.__name__} pages an unordered queryset")
                self.assertIn(qs.query.order_by[-1], ("id", "-id"))

    def test_paging_returns_every_row_once_in_the_documented_order(self):
        for route, viewset, order in self.CASES:
            with self.subTest(route=route):
                model = list_queryset(viewset, self.admin).model
                expected = list(model.objects.order_by(*order).values_list("id", flat=True))
                self.assertGreater(len(expected), PAGE, "the fixture must span more than one page")
                ids, count = self.page_through(route)
                self.assertEqual(count, len(expected))
                self.assertEqual(len(ids), len(set(ids)), "a row appeared on two pages")
                self.assertEqual(ids, expected)

    def test_the_fixture_exercises_the_order(self):
        """Guards the test itself: insertion order is not the answer."""
        ids, _ = self.page_through("/api/controls/")
        controls = Control.objects.in_bulk(ids)
        self.assertEqual([controls[i].control_id for i in ids[:3]], ["AA.1", "AA.2", "AA.10"])
        ids, _ = self.page_through("/api/vendors/")
        self.assertEqual(Vendor.objects.get(pk=ids[0]).name, "Acme Payroll")
        # Newest first, and the three rows sharing a timestamp newest id first.
        ids, _ = self.page_through("/api/risks/")
        tied = list(Risk.objects.filter(created_at=Risk.objects.get(pk=ids[1]).created_at)
                    .values_list("id", flat=True))
        self.assertEqual(len(tied), 3)
        self.assertEqual(ids[1:4], sorted(tied, reverse=True))

    def test_a_valid_ordering_parameter_still_wins(self):
        client = self.client_for(self.admin)
        r = client.get("/api/vendors/", {"ordering": "-name"})
        names = [row["name"] for row in r.data["results"]]
        self.assertEqual(names, sorted(names, reverse=True))
        r = client.get("/api/controls/", {"ordering": "-control_id"})
        control_ids = [row["control_id"] for row in r.data["results"]]
        self.assertEqual(control_ids, sorted(control_ids, reverse=True))

    def test_the_framework_control_list_is_ordered_too(self):
        """Not paged, but it shares the annotated queryset, so it gets the
        same order rather than whatever the GROUP BY returns."""
        r = self.client_for(self.admin).get(f"/api/frameworks/{self.tree.framework.key}/controls/")
        self.assertEqual([row["control_id"] for row in r.data], ["TC1.1", "TC1.2"])
        r = self.client_for(self.admin).get("/api/frameworks/alpha/controls/")
        self.assertEqual([row["control_id"] for row in r.data], ["AA.1", "AA.2", "AA.10"])
