"""The lead schedule: one row per framework on the dashboard, from the same
scoring pass as the headline, and a summary that scores the programme once."""
from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from accounts import tenancy
from accounts import tests_tenancy
from analytics.models import ReadinessSnapshot
from analytics.snapshots import record_today
from compliance import scoring
from compliance.models import Control, ControlCategory, ControlEvidence, Framework
from testutils import APITestBase, make_doc

SUMMARY = "/api/analytics/summary/"
BANDS = ("ready", "nearly", "at_risk", "not_started")


def add_framework(key, statuses):
    """A framework of one category holding a control per entry in ``statuses``."""
    fw = Framework.objects.create(key=key, name=key.upper(), version="1")
    cat = ControlCategory.objects.create(framework=fw, key=f"{key}-c", name=f"{key} category", order=0)
    controls = [
        Control.objects.create(category=cat, control_id=f"{key}.{n}", title=f"{key} control {n}", status=status)
        for n, status in enumerate(statuses, start=1)
    ]
    return fw, controls


class ScheduleTests(APITestBase):
    def setUp(self):
        super().setUp()
        # tfw: two controls. alpha: three, one of them not applicable and one
        # linked as evidence. omega: nothing but a not applicable control that
        # still has a document linked to it.
        self.alpha, (self.a1, self.a2, self.a3) = add_framework(
            "alpha", ["implemented", "in_progress", "not_applicable"])
        self.omega, (self.o1,) = add_framework("omega", ["not_applicable"])
        self.doc = make_doc(self.tree.ctrl1, self.owner, name="Policy", days=90)
        for control in (self.a1, self.o1):
            ControlEvidence.objects.create(control=control, document=self.doc, linked_by=self.manager)
        Control.objects.filter(pk=self.a1.pk).update(owner=self.owner, last_tested_on=timezone.localdate())

    def summary(self, user=None):
        r = self.client_for(user or self.manager).get(SUMMARY)
        self.assertEqual(r.status_code, 200, r.data)
        return r.data

    def row(self, data, key):
        return next(f for f in data["frameworks"] if f["key"] == key)

    def test_every_row_carries_its_evidence_score_and_bands(self):
        data = self.summary()
        alpha = self.row(data, "alpha")
        self.assertEqual(alpha["id"], self.alpha.pk)
        self.assertEqual(alpha["with_evidence"], 1)
        self.assertEqual(alpha["applicable"], 2)
        self.assertEqual(set(alpha["bands"]), set(BANDS))
        self.assertEqual(sum(alpha["bands"].values()), 2)
        # The row's score is the mean of its applicable controls' scores, the
        # way the headline is for the programme.
        expected = [
            scoring.score_control(scoring.annotate(Control.objects.filter(pk=c.pk), self.admin).get(), self.admin)["score"]
            for c in (self.a1, self.a2)
        ]
        self.assertEqual(alpha["score"], round(sum(expected) / 2))
        # pct stays the implemented share, a different figure with a different name.
        self.assertEqual(alpha["pct"], 50)

    def test_a_framework_with_nothing_applicable_has_no_score_but_counts_its_evidence(self):
        omega = self.row(self.summary(), "omega")
        self.assertEqual(omega["applicable"], 0)
        self.assertIsNone(omega["score"])
        self.assertEqual(omega["bands"], dict.fromkeys(BANDS, 0))
        self.assertEqual(omega["with_evidence"], 1, "a linked not applicable control is still linked")

    def test_the_rows_foot_to_the_programme_figures(self):
        data = self.summary()
        rows = data["frameworks"]
        self.assertEqual(sum(f["applicable"] for f in rows), data["readiness"]["applicable"])
        self.assertEqual(sum(f["with_evidence"] for f in rows), data["controls"]["with_evidence"])
        for status, n in data["controls"]["by_status"].items():
            self.assertEqual(sum(f["by_status"][status] for f in rows), n, status)
        for band, n in data["readiness"]["bands"].items():
            self.assertEqual(sum(f["bands"][band] for f in rows), n, band)

    def test_a_viewer_sees_the_same_schedule_as_a_manager(self):
        """Aggregates count every folder, like the controls block beside them."""
        self.assertEqual(self.summary(self.viewer)["frameworks"], self.summary(self.manager)["frameworks"])

    def test_rows_keep_the_order_by_name(self):
        names = [f["name"] for f in self.summary()["frameworks"]]
        self.assertEqual(names, sorted(names))

    def test_the_cost_of_the_summary_does_not_grow_with_the_frameworks(self):
        self.summary()  # today's snapshot exists from here on
        with CaptureQueriesContext(connection) as before:
            self.summary()
        for n in range(4):
            add_framework(f"extra{n}", ["not_started", "implemented"])
        with CaptureQueriesContext(connection) as after:
            data = self.summary()
        self.assertEqual(len(data["frameworks"]), 7)
        self.assertEqual(len(after), len(before))

    def test_a_request_scores_the_programme_once_even_on_the_first_of_the_day(self):
        self.assertFalse(ReadinessSnapshot.objects.exists())
        with mock.patch("compliance.scoring.programme_score", wraps=scoring.programme_score) as spy:
            self.summary()
            self.assertEqual(spy.call_count, 1, "the snapshot reuses the summary's own pass")
            self.summary()
            self.assertEqual(spy.call_count, 2, "a day that already has its row measures nothing more")
        self.assertEqual(ReadinessSnapshot.objects.get().score, self.summary()["readiness"]["score"])

    def test_record_today_measures_only_when_it_has_to(self):
        record_today()
        handed = scoring.programme_score()
        with mock.patch("compliance.scoring.programme_score", wraps=scoring.programme_score) as spy:
            record_today()
            self.assertEqual(spy.call_count, 0)
            record_today(force=True)
            self.assertEqual(spy.call_count, 1)
            record_today(force=True, scored=handed)
            self.assertEqual(spy.call_count, 1, "a result handed in is not measured again")


class ProgrammeScoreByFrameworkTests(APITestBase):
    def test_the_old_keys_are_untouched_and_the_frameworks_foot_to_them(self):
        fw, _ = add_framework("beta", ["implemented", "not_started", "not_applicable"])
        Control.objects.filter(pk=self.tree.c1.pk).update(status="implemented")
        scored = scoring.programme_score()
        self.assertEqual({"score", "applicable", "bands", "by_framework"}, set(scored))
        by = scored["by_framework"]
        self.assertEqual(set(by), {self.tree.framework.pk, fw.pk})
        self.assertEqual(sum(f["applicable"] for f in by.values()), scored["applicable"])
        for band, n in scored["bands"].items():
            self.assertEqual(sum(f["bands"][band] for f in by.values()), n)
        total = sum(f["score"] * f["applicable"] for f in by.values())
        # Rounded per framework, so only close to the programme's own mean.
        self.assertAlmostEqual(total / scored["applicable"], scored["score"], delta=1)

    def test_a_queryset_handed_in_is_grouped_the_same_way(self):
        _, controls = add_framework("beta", ["implemented", "in_progress"])
        scored = scoring.programme_score(Control.objects.filter(pk__in=[c.pk for c in controls]))
        self.assertEqual(scored["applicable"], 2)
        self.assertEqual(list(scored["by_framework"].values())[0]["applicable"], 2)


class ScheduleTenancyTests(tests_tenancy.TwoWorkspaces):
    def test_both_workspaces_own_a_framework_called_tfw_and_each_counts_only_its_own(self):
        with tenancy.scoped(self.beta):
            Control.objects.filter(pk=self.b_tree.c1.pk).update(status="implemented")
            ControlEvidence.objects.create(control=self.b_tree.c1, document=self.b_doc, linked_by=self.b_admin)
        data = self.client_for(self.manager).get(SUMMARY).data
        self.assertEqual([f["key"] for f in data["frameworks"]], ["tfw"])
        row = data["frameworks"][0]
        self.assertEqual(row["id"], self.tree.framework.pk)
        self.assertEqual(row["total"], 2)
        self.assertEqual(row["by_status"]["implemented"], 0, "Beta's implemented control is not Alpha's")
        self.assertEqual(row["with_evidence"], 0, "nor is Beta's evidence")
        self.assertEqual(row["applicable"], data["readiness"]["applicable"])

        beta = self.client_for(self.b_manager).get(SUMMARY).data
        self.assertEqual(beta["frameworks"][0]["id"], self.b_tree.framework.pk)
        self.assertEqual(beta["frameworks"][0]["with_evidence"], 1)
