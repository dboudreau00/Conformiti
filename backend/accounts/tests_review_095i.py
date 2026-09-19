"""The sixth independent review, fixed in 0.9.5i.

Three findings, two of them defects in fixes 0.9.5h shipped the same day.

L-1: 0.9.5h closed the assignee disclosure on the write path and left the
filter on the same collection open, where django-filter's generated
ModelChoiceFilter answers 400 for an id that is nobody and 200 for an id that
is somebody. The audit trail and the document register take a person's id the
same way, and the trail is readable by an issued auditor with no live grant.

L-2 lives in ``tools/validate.py``: it is a property of a shell script, and
the failure it guards against is one that hides itself.

L-3: a questionnaire link that is not open returns its state and nothing else.
"""
from rest_framework.test import APIRequestFactory

from accounts.models import Role
from testutils import APITestBase, make_user


class FilterOracleTests(APITestBase):
    """L-1. These are the three collections an external auditor may GET that
    take a person's id. None of them returns a name, so this is narrower than
    the directory walk M-2 closed in 0.9.5h: it answers whether an id belongs
    to anybody, one sequential id at a time, which is the same question
    through a different door."""

    def setUp(self):
        super().setUp()
        self.client_ = self.client_for(self.auditor)
        self.absent = 10_000_000

    def test_the_request_list_does_not_say_who_exists(self):
        real = self.client_.get(f"/api/pbc-requests/?assignee={self.owner.pk}")
        absent = self.client_.get(f"/api/pbc-requests/?assignee={self.absent}")
        self.assertEqual(real.status_code, 200, getattr(real, "data", real))
        self.assertEqual(absent.status_code, real.status_code)

    def test_the_audit_trail_does_not_say_who_exists(self):
        real = self.client_.get(f"/api/audit-log/?user={self.owner.pk}")
        absent = self.client_.get(f"/api/audit-log/?user={self.absent}")
        self.assertEqual(real.status_code, 200, getattr(real, "data", real))
        self.assertEqual(absent.status_code, real.status_code)

    def test_the_document_register_does_not_say_who_exists(self):
        real = self.client_.get(f"/api/documents/?owner={self.owner.pk}")
        absent = self.client_.get(f"/api/documents/?owner={self.absent}")
        self.assertEqual(real.status_code, 200, getattr(real, "data", real))
        self.assertEqual(absent.status_code, real.status_code)

    def test_filtering_by_a_person_still_works(self):
        """The control: an id that exists still narrows the result, so this
        closed an oracle rather than a feature."""
        from audit.models import AuditLog

        AuditLog.objects.create(user=self.owner, action="login", object_type="session",
                                detail="seeded for the filter test")
        mine = self.client_.get(f"/api/audit-log/?user={self.owner.pk}").data
        nobody = self.client_.get(f"/api/audit-log/?user={self.absent}").data
        self.assertGreaterEqual(mine["count"], 1)
        self.assertEqual(nobody["count"], 0)


class EveryAuditorReadableFilterTests(APITestBase):
    """The walk, so the next collection added to the auditor's allowed list
    cannot bring an oracle with it.

    0.9.5h wrote a walk over ``@action`` routes for exactly this reason and it
    found a second instance immediately. This is the same idea applied to the
    filters: it resolves the filterset DRF would build for each readable
    collection and refuses any filter on a person that validates membership.
    """

    def filters_for(self, viewset):
        """The filterset DRF would build, whether declared or generated."""
        from django_filters.rest_framework import DjangoFilterBackend

        view = viewset()
        view.request = None
        queryset = getattr(viewset, "queryset", None)
        if queryset is None:
            return {}
        klass = DjangoFilterBackend().get_filterset_class(view, queryset)
        return dict(getattr(klass, "base_filters", {})) if klass else {}

    def test_no_readable_collection_validates_a_person_id(self):
        from django_filters import ModelChoiceFilter, ModelMultipleChoiceFilter

        from accounts.tests_auditor_surface import ALLOWED, registered_viewsets

        User = type(self.admin)
        offenders = []
        for prefix, viewset in sorted(registered_viewsets(), key=lambda pair: pair[0]):
            if prefix not in ALLOWED:
                continue
            for name, declared in self.filters_for(viewset).items():
                if not isinstance(declared, (ModelChoiceFilter, ModelMultipleChoiceFilter)):
                    continue
                model = getattr(getattr(declared, "queryset", None), "model", None)
                if model is User:
                    offenders.append(f"{prefix}?{name}")
        self.assertEqual(offenders, [], (
            "These filters are reachable by an external auditor and validate that the id "
            "names a person, so an id that exists and an id that does not answer "
            "differently. Use config.personfilters.person() instead, which filters on the "
            "number and says nothing about who holds it."
        ))


class DeadQuestionnaireStateTests(APITestBase):
    """L-3. 0.9.5h removed the names from a link that is no longer open and
    left the timestamps. ``submitted_at`` on a stolen URL is when the vendor
    filed, and the changelog sentence claimed the link said only which state
    it was in."""

    def test_the_payload_is_the_state_and_nothing_else(self):
        import datetime as dt

        from django.utils import timezone

        from vendors import questionnaire as q
        from vendors.models import QuestionnaireInvite, Vendor

        vendor = Vendor.objects.create(name="Northwind Cloud", category="Cloud hosting",
                                       tier="critical", contact_email="sec@northwind.example",
                                       owner=self.owner)
        invite = QuestionnaireInvite.objects.create(
            vendor=vendor, sent_to="sec@northwind.example", sent_by_name="Mia Manager",
            message="Please complete by Friday, Dana",
            expires_at=timezone.now() - dt.timedelta(days=1))
        self.assertEqual(invite.status, "expired")

        state = q.public_state(invite)
        self.assertEqual(set(state), {"status", "questions", "answers"})
        self.assertEqual(state["status"], "expired")
        body = str(state)
        for secret in (vendor.name, invite.sent_to, invite.sent_by_name, invite.message):
            self.assertNotIn(secret, body)


class RoleCapabilityCapTests(APITestBase):
    """Not a finding: the sixth review confirmed the 0.9.5h containment holds
    even though the Django admin still registers Role without a clean(). This
    records why that is acceptable, so the next reviewer does not have to
    re-derive it: the admin can still store the combination, and _cap means
    storing it grants nothing."""

    def test_a_role_saved_outside_the_api_still_grants_nothing(self):
        mixed = Role.objects.create(name="Saved in the admin", is_auditor=True,
                                    can_view_all=True, can_manage_folders=True)
        person = make_user("admin-made", mixed)
        self.assertFalse(person.can_view_all)
        self.assertFalse(person.can_manage_folders)
        self.assertTrue(person.is_auditor)
