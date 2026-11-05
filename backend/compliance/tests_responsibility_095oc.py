from rest_framework.exceptions import ValidationError
from rest_framework.test import APIRequestFactory

from compliance.models import Responsibility
from compliance.responsibility_views import ResponsibilitySerializer, ResponsibilityViewSet
from testutils import APITestBase, make_user


class SingleAccountableTests(APITestBase):
    """PRG-11: the one-Accountable rule is checked again under a lock on the control, not only in validate()."""

    def test_a_request_that_validated_before_another_insert_is_refused(self):
        alice = make_user("alice", self.roles["Viewer"])
        bob = make_user("bob", self.roles["Viewer"])
        control = self.tree.c1
        view = ResponsibilityViewSet()
        view.request = APIRequestFactory().post("/")
        view.request.user = self.manager
        serializer = ResponsibilitySerializer(data={"control": control.pk, "role": "accountable", "user": bob.pk})
        self.assertTrue(serializer.is_valid(), serializer.errors)  # nothing clashes yet
        # The other request commits between validation and the write. (On the unfixed code both rows are stored.)
        Responsibility.objects.create(control=control, role="accountable", user=alice, created_by=self.manager)
        with self.assertRaises(ValidationError):
            view.perform_create(serializer)
        self.assertEqual(Responsibility.objects.filter(control=control, role="accountable").count(), 1)

    def test_the_api_still_refuses_a_second_accountable_and_allows_other_roles(self):
        alice = make_user("alice", self.roles["Viewer"])
        bob = make_user("bob", self.roles["Viewer"])
        m = self.client_for(self.manager)
        control = self.tree.c1.pk
        first = m.post("/api/responsibilities/", {"control": control, "role": "accountable", "user": alice.pk},
                       format="json")
        self.assertEqual(first.status_code, 201, first.data)
        second = m.post("/api/responsibilities/", {"control": control, "role": "accountable", "user": bob.pk},
                        format="json")
        self.assertEqual(second.status_code, 400)
        consulted = m.post("/api/responsibilities/", {"control": control, "role": "consulted", "user": bob.pk},
                           format="json")
        self.assertEqual(consulted.status_code, 201, consulted.data)
        moved = m.patch(f"/api/responsibilities/{consulted.data['id']}/", {"role": "accountable"}, format="json")
        self.assertEqual(moved.status_code, 400)

    def test_an_auditor_cannot_write_a_responsibility(self):
        r = self.client_for(self.auditor).post(
            "/api/responsibilities/", {"control": self.tree.c1.pk, "role": "informed", "user": self.viewer.pk},
            format="json")
        self.assertEqual(r.status_code, 403)
