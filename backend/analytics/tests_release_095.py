"""0.9.5: the dashboard's headline number is the register's score, not the
share of controls somebody marked implemented."""
from django.utils import timezone

from analytics.models import ReadinessSnapshot
from analytics.snapshots import record_today, trend
from compliance.models import Control, ControlEvidence
from compliance.scoring import programme_score
from testutils import APITestBase, make_doc


class ProgrammeScoreTests(APITestBase):
    def test_implemented_with_nothing_behind_it_does_not_count_as_ready(self):
        # Both controls marked implemented: the old headline said 100 %.
        Control.objects.update(status="implemented")
        scored = programme_score()
        self.assertEqual(scored["applicable"], 2)
        self.assertLess(scored["score"], 70, "no owner, no evidence, no test: not ready")
        self.assertEqual(scored["bands"]["ready"], 0)

        # The summary carries both figures, and they now disagree honestly.
        s = self.client_for(self.manager).get("/api/analytics/summary/").data["readiness"]
        self.assertEqual(s["pct"], 100)
        self.assertEqual(s["score"], scored["score"])
        self.assertEqual(sum(s["bands"].values()), 2)

    def test_evidence_an_owner_and_a_test_move_the_score(self):
        Control.objects.update(status="implemented", owner=self.owner,
                               last_tested_on=timezone.localdate())
        make_doc(self.tree.ctrl1, owner=self.owner, name="Policy")
        make_doc(self.tree.ctrl2, owner=self.owner, name="Standard")
        for control, folder in ((self.tree.c1, self.tree.ctrl1), (self.tree.c2, self.tree.ctrl2)):
            ControlEvidence.objects.create(control=control, document=folder.documents.first(),
                                           linked_by=self.manager)
        scored = programme_score()
        self.assertGreaterEqual(scored["score"], 90)
        self.assertEqual(scored["bands"]["ready"], 2)

    def test_not_applicable_controls_are_excluded(self):
        Control.objects.filter(pk=self.tree.c2.pk).update(status="not_applicable")
        self.assertEqual(programme_score()["applicable"], 1)

    def test_a_snapshot_records_the_score_and_the_trend_carries_it(self):
        Control.objects.update(status="implemented")
        snap = record_today(force=True)
        self.assertIsNotNone(snap.score)
        self.assertEqual(snap.score, programme_score()["score"])
        points = trend()["points"]
        self.assertEqual(points[-1]["score"], snap.score)
        self.assertIsNone(trend()["score_delta_pts"], "one point is no delta")

    def test_a_pre_095_snapshot_has_no_score_and_says_so(self):
        today = timezone.localdate()
        last_month = (today.replace(day=1) - timezone.timedelta(days=1)).replace(day=1)
        ReadinessSnapshot.objects.create(date=last_month, total_controls=2, applicable=2,
                                         implemented=1)
        record_today(force=True)
        t = trend()
        self.assertIsNone(t["points"][0]["score"])
        self.assertIsNotNone(t["points"][-1]["score"])
        self.assertIsNone(t["score_delta_pts"])
        self.assertIsNotNone(t["delta_pts"])
