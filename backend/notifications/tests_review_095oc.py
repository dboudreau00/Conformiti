from datetime import date, datetime, timezone as dt_tz
from unittest import mock

from django.core import mail
from django.test import override_settings
from django.utils import timezone

from documents.models import Document
from notifications.tasks import run_digests, run_review_scan
from testutils import APITestBase, make_doc


@override_settings(EMAIL_PROVIDER="console", COMPLIANCE_TEAM_EMAIL="grc@test.local",
                   REVIEW_ALERT_LEAD_DAYS=[30, 14, 7, 1])
class ReviewScanRaceTests(APITestBase):
    @staticmethod
    def _race(action):
        """Run ``action`` once, in the gap between the scan reading the documents and its conditional claim."""
        real_filter = Document.objects.filter
        raced = []

        def filter_(*args, **kwargs):
            if "reminders_sent" in kwargs and not raced:
                raced.append(True)
                action()
            return real_filter(*args, **kwargs)

        return mock.patch.object(Document.objects, "filter", side_effect=filter_)

    def test_a_review_marked_done_during_the_scan_is_not_expired(self):
        doc = make_doc(self.tree.ctrl1, self.owner, name="Late", days=-2)
        manager = self.client_for(self.manager)

        def reviewed():
            self.assertEqual(manager.post(f"/api/documents/{doc.pk}/mark_reviewed/").status_code, 200)

        with self._race(reviewed):
            run_review_scan()
        doc.refresh_from_db()
        self.assertEqual(doc.status, Document.Status.APPROVED)
        self.assertEqual(doc.reminders_sent, [])
        self.assertGreater(doc.next_review_date, doc.last_reviewed)
        self.assertEqual(len(mail.outbox), 0, "an overdue notice for a document that was just reviewed")

    def test_a_review_date_moved_during_the_scan_keeps_its_own_windows(self):
        doc = make_doc(self.tree.ctrl1, self.owner, name="Soon", days=6)
        manager = self.client_for(self.manager)

        def moved():
            response = manager.patch(f"/api/documents/{doc.pk}/",
                                     {"last_reviewed": str(timezone.localdate())}, format="json")
            self.assertEqual(response.status_code, 200)

        with self._race(moved):
            run_review_scan()
        doc.refresh_from_db()
        self.assertEqual(doc.reminders_sent, [], "the old date's windows were stamped onto the new date")
        self.assertEqual(len(mail.outbox), 0)

    def test_an_undisturbed_scan_still_sends_and_stamps(self):
        doc = make_doc(self.tree.ctrl1, self.owner, name="Late", days=-1)
        run_review_scan()
        doc.refresh_from_db()
        self.assertEqual(doc.status, Document.Status.EXPIRED)
        self.assertEqual(len(mail.outbox), 1)


@override_settings(TIME_ZONE="Pacific/Auckland")
class LocalCalendarDayTests(APITestBase):
    """ROB-04: ages and review dates use the configured time zone's day, not the UTC day."""

    # 20:00 UTC on 4 November is 09:00 on 5 November in Auckland.
    NOW = datetime(2026, 11, 4, 20, 0, tzinfo=dt_tz.utc)

    def test_a_document_due_on_the_utc_day_is_overdue_on_the_local_next_day(self):
        doc = make_doc(self.tree.ctrl1, self.owner, name="Policy")
        doc.next_review_date = date(2026, 11, 4)
        with mock.patch("django.utils.timezone.now", return_value=self.NOW):
            self.assertTrue(doc.is_overdue)
            self.assertEqual(doc.days_until_review, -1)

    def test_marking_reviewed_stamps_the_local_day(self):
        doc = make_doc(self.tree.ctrl1, self.owner, name="Policy")
        with mock.patch("django.utils.timezone.now", return_value=self.NOW):
            r = self.client_for(self.manager).post(f"/api/documents/{doc.pk}/mark_reviewed/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        doc.refresh_from_db()
        self.assertEqual(doc.last_reviewed, date(2026, 11, 5))

    def test_the_bell_ages_a_new_vendor_from_its_local_creation_day(self):
        from notifications.notifications import build
        from vendors.models import Vendor

        vendor = Vendor.objects.create(name="Northwind Cloud", tier="critical", owner=self.owner)
        Vendor.objects.filter(pk=vendor.pk).update(created_at=self.NOW)
        with mock.patch("django.utils.timezone.now", return_value=self.NOW):
            item = next(i for i in build(self.owner) if i["key"] == f"vendor-onboard:{vendor.pk}")
        self.assertIn("(0 days since onboarding)", item["detail"])


@override_settings(EMAIL_PROVIDER="console", PUBLIC_URL="https://grc.example")
class WeeklyDigestCatchUpTests(APITestBase):
    """ROB-06: a weekly digest missed on Monday goes out on the next run once the last one is over six days old."""

    def setUp(self):
        super().setUp()
        make_doc(self.tree.ctrl1, self.owner, name="Late", days=-1)
        self.owner.digest = "weekly"
        self.owner.save()
        mail.outbox.clear()
        self.tuesday = date(2026, 9, 8)

    def _sent_ago(self, days):
        sent = self.tuesday - timezone.timedelta(days=days)
        self.owner.digest_sent_at = datetime(sent.year, sent.month, sent.day, 12, tzinfo=dt_tz.utc)
        self.owner.save()

    def test_a_missed_monday_is_made_up_on_a_later_day(self):
        self._sent_ago(8)
        self.assertEqual(run_digests(today=self.tuesday), 1)
        self.assertIn("Your weekly Conformiti digest", mail.outbox[0].body, "the choice label's (Monday) is not copied in")
        self.assertEqual(run_digests(today=self.tuesday), 0, "the claim stops a second mail the same day")

    def test_a_recent_digest_or_none_at_all_waits_for_monday(self):
        self.assertEqual(run_digests(today=self.tuesday), 0, "never sent: no surprise first mail")
        self._sent_ago(3)
        self.assertEqual(run_digests(today=self.tuesday), 0)
        self.assertEqual(run_digests(today=date(2026, 9, 7)), 1, "Monday still sends")
