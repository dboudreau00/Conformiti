"""Dashboard aggregation: org-wide control figures, visibility-scoped documents,
and the readiness history behind the trend line."""
from datetime import date

from django.core.management import call_command
from django.utils import timezone

from analytics.models import ReadinessSnapshot
from analytics.snapshots import record_today, trend
from compliance.models import Control
from documents.models import VIEW
from testutils import APITestBase, grant, make_doc


class AnalyticsTests(APITestBase):
    def test_summary_shape_and_scoping(self):
        Control.objects.filter(pk=self.tree.c1.pk).update(status="implemented")
        make_doc(self.tree.ctrl1, self.owner, name="Hidden", days=-4)
        make_doc(self.tree.ctrl2, self.owner, name="Shown", days=20)
        grant(self.tree.ctrl2, user=self.viewer, level=VIEW)

        s = self.client_for(self.viewer).get("/api/analytics/summary/").data
        self.assertEqual(s["controls"]["total"], 2)
        self.assertEqual(s["controls"]["by_status"]["implemented"], 1)
        fw = next(f for f in s["frameworks"] if f["key"] == "tfw")
        self.assertEqual(fw["pct"], 50)
        self.assertEqual(s["readiness"]["pct"], 50)
        # documents are scoped to what the caller may see
        self.assertEqual(s["documents"]["total"], 1)
        self.assertEqual(s["reviews"]["overdue"], 0)
        self.assertEqual(s["reviews"]["due_30"], 1)
        self.assertEqual(s["overdue_sample"], [])
        self.assertEqual(len(s["review_timeline"]), 6)

        m = self.client_for(self.manager).get("/api/analytics/summary/").data
        self.assertEqual(m["documents"]["total"], 2)
        self.assertEqual(m["reviews"]["overdue"], 1)
        self.assertEqual(m["overdue_sample"][0]["name"], "Hidden")
        self.assertEqual(self.client_for().get("/api/analytics/summary/").status_code, 401)

    def test_summary_records_one_snapshot_per_day(self):
        c = self.client_for(self.viewer)
        c.get("/api/analytics/summary/")
        c.get("/api/analytics/summary/")
        self.assertEqual(ReadinessSnapshot.objects.count(), 1)
        snap = ReadinessSnapshot.objects.get()
        self.assertEqual(snap.date, timezone.localdate())
        self.assertEqual(snap.applicable, 2)
        s = c.get("/api/analytics/summary/").data
        self.assertEqual(len(s["readiness"]["trend"]), 1)
        self.assertIsNone(s["readiness"]["delta_pts"])  # no history yet -> no invented delta

    def test_trend_uses_last_point_per_month_and_delta(self):
        today = timezone.localdate()
        prev = (today.replace(day=1) - timezone.timedelta(days=1))
        ReadinessSnapshot.objects.create(date=prev.replace(day=1), implemented=1, applicable=10, total_controls=10)
        ReadinessSnapshot.objects.create(date=prev, implemented=2, applicable=10, total_controls=10)   # last of prev month: 20%
        ReadinessSnapshot.objects.create(date=today, implemented=5, applicable=10, total_controls=10)  # this month: 50%
        t = trend()
        self.assertEqual([p["pct"] for p in t["points"]], [20, 50])
        self.assertEqual(t["delta_pts"], 30)

    def test_record_readiness_command_refreshes(self):
        record_today()
        Control.objects.update(status="implemented")
        call_command("record_readiness", verbosity=0)
        self.assertEqual(ReadinessSnapshot.objects.get().implemented, 2)


class ControlsExportTests(APITestBase):
    def test_export_is_csv_and_formula_safe(self):
        Control.objects.filter(pk=self.tree.c1.pk).update(title="=HYPERLINK(\"x\")", status="implemented")
        r = self.client_for(self.viewer).get("/api/controls/export/?status=implemented")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "text/csv")
        body = r.content.decode()
        self.assertIn("'=HYPERLINK", body)
        self.assertNotIn("TC1.2", body)  # status filter applied
        r = self.client_for(self.viewer).get("/api/controls/export/")
        self.assertIn("TC1.2", r.content.decode())
