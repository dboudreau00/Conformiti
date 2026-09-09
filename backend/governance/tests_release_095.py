"""0.9.5: completing an access review carries out its own decisions."""
from rest_framework.test import APIClient

from governance.models import AccessReviewItem
from testutils import PASSWORD, APITestBase


class ReviewCompletionAppliesDecisionsTests(APITestBase):
    def start(self):
        admin = self.client_for(self.admin)
        r = admin.post("/api/access-reviews/", {"name": "Q3 review"}, format="json")
        self.assertEqual(r.status_code, 201)
        rid = r.data["id"]
        items = {i["username"]: i for i in admin.get(f"/api/access-review-items/?review={rid}").data}
        return admin, rid, items

    def decide(self, admin, item, decision):
        r = admin.patch(f"/api/access-review-items/{item['id']}/",
                        {"decision": decision, "decision_notes": "review"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)

    def test_a_revoke_decision_deactivates_the_account_and_ends_its_sessions(self):
        login = APIClient().post("/api/auth/token/", {"username": "val", "password": PASSWORD},
                                 format="json")
        refresh = login.data["refresh"]

        admin, rid, items = self.start()
        for username, item in items.items():
            self.decide(admin, item, "revoke" if username == "val" else "keep")
        r = admin.post(f"/api/access-reviews/{rid}/complete/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["applied"]["revoked"], ["val"])
        self.assertEqual(r.data["applied"]["skipped"], [])

        self.viewer.refresh_from_db()
        self.assertFalse(self.viewer.is_active)
        self.assertEqual(APIClient().post("/api/auth/token/refresh/", {"refresh": refresh},
                                          format="json").status_code, 401)
        self.assertEqual(APIClient().post("/api/auth/token/",
                                          {"username": "val", "password": PASSWORD},
                                          format="json").status_code, 401)

    def test_the_reviewer_and_superusers_are_reported_not_revoked(self):
        admin, rid, items = self.start()
        for username, item in items.items():
            self.decide(admin, item, "revoke" if username in ("ada",) else "keep")
        r = admin.post(f"/api/access-reviews/{rid}/complete/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["applied"]["revoked"], [])
        self.assertEqual([s["username"] for s in r.data["applied"]["skipped"]], ["ada"])
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_keep_and_modify_change_nothing(self):
        admin, rid, items = self.start()
        for username, item in items.items():
            self.decide(admin, item, "modify" if username == "owen" else "keep")
        r = admin.post(f"/api/access-reviews/{rid}/complete/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["applied"], {"revoked": [], "skipped": []})
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_active)
        self.assertEqual(AccessReviewItem.objects.filter(review_id=rid, decision="modify").count(), 1)
