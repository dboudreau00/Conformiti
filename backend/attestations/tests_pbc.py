"""
The PBC request list: who raises a line, who answers it, who judges it, and
who can read what came back. The access tests are the ones that matter: the
assignee route is a deliberate, narrow disclosure and must stay narrow.
"""
from django.core import mail
from django.test import override_settings
from django.utils import timezone

from attestations.models import PbcItem, PbcRequest
from audit.models import AuditLog
from documents.models import VIEW
from notifications.notifications import build as build_feed
from notifications.tasks import OVERDUE, run_pbc_scan
from testutils import grant, make_doc
from attestations.tests import PackageTestBase


class PbcBase(PackageTestBase):
    def setUp(self):
        super().setUp()
        self.add_control()
        self.seal()
        self.assertEqual(self.issue_to(self.auditor).status_code, 201)
        self.auditor_client = self.client_for(self.auditor)
        self.owner_client = self.client_for(self.owner)

    def raise_line(self, client, **body):
        payload = {"package": self.package.pk, "title": "Termination tickets for the period"}
        payload.update(body)
        return client.post("/api/pbc-requests/", payload, format="json")


class RaiseAndEditTests(PbcBase):
    def test_the_auditor_and_the_organisation_can_both_raise_lines_with_sequential_references(self):
        a = self.raise_line(self.auditor_client, due_date=str(timezone.localdate() + timezone.timedelta(days=5)))
        self.assertEqual(a.status_code, 201, a.data)
        self.assertEqual((a.data["reference"], a.data["requested_by_side"], a.data["status"]),
                         ("PBC-01", "auditor", "open"))
        b = self.raise_line(self.manager_client, title="Change tickets sample", assignee=self.owner.pk,
                            package_control=self.package.controls.first().pk)
        self.assertEqual(b.status_code, 201, b.data)
        self.assertEqual((b.data["reference"], b.data["requested_by_side"], b.data["assignee_name"],
                          b.data["control_ref"]), ("PBC-02", "organisation", "Owen Tester", "TC1.1"))
        self.assertTrue(AuditLog.objects.filter(object_type="evidence-packages",
                                                detail__contains="PBC-01 raised by the auditor").exists())
        summary = self.manager_client.get(f"/api/evidence-packages/{self.package.pk}/").data["pbc_summary"]
        self.assertEqual((summary["total"], summary["open"]), (2, 2))

    def test_nobody_else_can_raise_or_see_a_line(self):
        for client in (self.owner_client, self.client_for(self.viewer)):
            self.assertEqual(self.raise_line(client).status_code, 403)
        self.raise_line(self.auditor_client)
        self.assertEqual(self.owner_client.get("/api/pbc-requests/").data["count"], 0)
        # A revoked auditor loses the list with the grant.
        self.package.grants.update(revoked_at=timezone.now())
        self.assertEqual(self.auditor_client.get("/api/pbc-requests/").data["count"], 0)
        self.assertEqual(self.raise_line(self.auditor_client).status_code, 403)

    def test_the_auditor_edits_only_their_own_open_lines_and_the_organisation_edits_any(self):
        mine = self.raise_line(self.auditor_client).data
        theirs = self.raise_line(self.manager_client).data
        ok = self.auditor_client.patch(f"/api/pbc-requests/{mine['id']}/", {"description": "FY26 only"}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(self.auditor_client.patch(f"/api/pbc-requests/{theirs['id']}/",
                                                   {"title": "x"}, format="json").status_code, 403)
        r = self.manager_client.patch(f"/api/pbc-requests/{mine['id']}/",
                                      {"assignee": self.owner.pk, "due_date": "2030-01-01"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["assignee_name"], "Owen Tester")
        # Status is never patched directly, and lines are withdrawn not deleted.
        self.assertEqual(self.manager_client.patch(f"/api/pbc-requests/{mine['id']}/",
                                                   {"status": "accepted"}, format="json").status_code, 400)
        self.assertEqual(self.manager_client.delete(f"/api/pbc-requests/{mine['id']}/").status_code, 400)

    def test_a_control_must_belong_to_the_package(self):
        from attestations.models import EvidencePackage, PackageControl
        other = EvidencePackage.objects.create(name="Other", created_by=self.manager)
        row = PackageControl.objects.create(package=other, control_ref="ZZ", title="z")
        r = self.raise_line(self.manager_client, package_control=row.pk)
        self.assertEqual(r.status_code, 400)


class AnswerTests(PbcBase):
    def setUp(self):
        super().setUp()
        self.line = self.raise_line(self.auditor_client, assignee=self.owner.pk,
                                    due_date=str(timezone.localdate() + timezone.timedelta(days=3))).data
        self.hidden = make_doc(self.tree.ctrl2, owner=self.manager, name="Hidden report", content=b"secret")
        grant(self.tree.ctrl1, user=self.owner, level=VIEW)   # Owen's own control folder

    def attach(self, client, doc, **extra):
        return client.post("/api/pbc-items/", {"request": self.line["id"], "document": doc.pk, **extra}, format="json")

    def test_the_assignee_sees_their_line_answers_it_and_nothing_more_of_the_package(self):
        listed = self.owner_client.get("/api/pbc-requests/?mine=1").data
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["results"][0]["package_name"], "SOC 2 fieldwork")
        self.assertTrue(listed["results"][0]["can"]["answer"])
        self.assertFalse(listed["results"][0]["can"]["edit"])
        # ...but not the package itself.
        self.assertEqual(self.owner_client.get("/api/evidence-packages/").data["count"], 0)
        # Owen can attach the document in his own folder, not the hidden one.
        r = self.attach(self.owner_client, self.doc, note="Signed copy")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["content_sha256"], __import__("hashlib").sha256(b"policy bytes").hexdigest())
        self.assertEqual(self.attach(self.owner_client, self.hidden).status_code, 403)
        self.assertEqual(self.attach(self.owner_client, self.doc).status_code, 400)   # already attached
        # Marking provided, with the attachment standing in for a note.
        r = self.owner_client.post(f"/api/pbc-requests/{self.line['id']}/provide/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data["status"], r.data["provided_by_name"]), ("provided", "Owen Tester"))

    def test_provided_needs_something(self):
        r = self.manager_client.post(f"/api/pbc-requests/{self.line['id']}/provide/", {}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.manager_client.post(f"/api/pbc-requests/{self.line['id']}/provide/",
                                     {"response_note": "No such tickets exist; see the change log instead."},
                                     format="json")
        self.assertEqual(r.status_code, 200)

    def test_the_auditor_reads_the_attachment_under_the_grant_and_it_is_recorded(self):
        self.attach(self.manager_client, self.doc)
        item = PbcItem.objects.get()
        r = self.auditor_client.get(f"/api/pbc-items/{item.pk}/file/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b"".join(r.streaming_content), b"policy bytes")
        self.assertTrue(AuditLog.objects.filter(action="read", detail__contains="from PBC-01").exists())
        self.package.refresh_from_db()
        self.assertEqual(self.package.grants.get().access_count, 1)
        # The same document is still closed to the auditor by every other route.
        self.assertEqual(self.auditor_client.get(f"/api/documents/{self.doc.pk}/download/").status_code, 404)
        # And the viewer, with no route at all, gets nothing.
        self.assertEqual(self.client_for(self.viewer).get(f"/api/pbc-items/{item.pk}/file/").status_code, 404)
        self.assertEqual(self.client_for(self.viewer).get("/api/pbc-items/").data["count"], 0)

    def test_the_assignee_reads_attachments_on_their_line_only(self):
        self.attach(self.manager_client, self.doc)
        other = self.raise_line(self.manager_client, title="Other line").data
        grant(self.tree.ctrl2, user=self.manager, level=VIEW)
        self.manager_client.post("/api/pbc-items/", {"request": other["id"], "document": self.hidden.pk}, format="json")
        mine, theirs = PbcItem.objects.get(request_id=self.line["id"]), PbcItem.objects.get(request_id=other["id"])
        self.assertEqual(self.owner_client.get(f"/api/pbc-items/{mine.pk}/file/").status_code, 200)
        self.assertEqual(self.owner_client.get(f"/api/pbc-items/{theirs.pk}/file/").status_code, 404)

    def test_accept_and_return_are_the_auditors_and_a_returned_line_reopens(self):
        self.attach(self.manager_client, self.doc)
        lid = self.line["id"]
        # Cannot judge what has not been provided.
        self.assertEqual(self.auditor_client.post(f"/api/pbc-requests/{lid}/accept/").status_code, 400)
        self.manager_client.post(f"/api/pbc-requests/{lid}/provide/", {"response_note": "Attached."}, format="json")
        # The assignee is not a judge.
        self.assertEqual(self.owner_client.post(f"/api/pbc-requests/{lid}/accept/").status_code, 403)
        r = self.auditor_client.post(f"/api/pbc-requests/{lid}/return/", {}, format="json")
        self.assertEqual(r.status_code, 400)          # a return says why
        r = self.auditor_client.post(f"/api/pbc-requests/{lid}/return/",
                                     {"returned_note": "Need the full period, not Q1."}, format="json")
        self.assertEqual((r.status_code, r.data["status"]), (200, "returned"))
        self.assertIn(f"pbc-returned:{lid}", [i["key"] for i in build_feed(self.owner)])
        # Provide again, then accept; accepted lines are closed for good.
        self.attach(self.manager_client, self.hidden)
        self.manager_client.post(f"/api/pbc-requests/{lid}/provide/", {"response_note": "Full period."}, format="json")
        r = self.auditor_client.post(f"/api/pbc-requests/{lid}/accept/")
        self.assertEqual((r.status_code, r.data["status"], r.data["accepted_by_name"]),
                         (200, "accepted", "Aria Tester"))
        self.assertEqual(self.attach(self.manager_client, self.doc).status_code, 400)
        self.assertEqual(self.manager_client.post(f"/api/pbc-requests/{lid}/withdraw/").status_code, 400)
        self.assertEqual(self.manager_client.delete(f"/api/pbc-items/{PbcItem.objects.first().pk}/").status_code, 400)

    def test_withdrawal_and_a_withdrawn_package_close_the_list(self):
        lid = self.line["id"]
        self.assertEqual(self.owner_client.post(f"/api/pbc-requests/{lid}/withdraw/").status_code, 403)
        r = self.auditor_client.post(f"/api/pbc-requests/{lid}/withdraw/")
        self.assertEqual((r.status_code, r.data["status"]), (200, "withdrawn"))
        self.manager_client.post(f"/api/evidence-packages/{self.package.pk}/withdraw/", {"reason": "done"}, format="json")
        self.assertEqual(self.raise_line(self.manager_client).status_code, 400)

    def test_export_is_csv(self):
        r = self.manager_client.get(f"/api/pbc-requests/export/?package={self.package.pk}")
        self.assertEqual(r["Content-Type"], "text/csv")
        self.assertIn("PBC-01", r.content.decode())


@override_settings(EMAIL_PROVIDER="console", COMPLIANCE_TEAM_EMAIL="grc@test.local",
                   REVIEW_ALERT_LEAD_DAYS=[30, 14, 7, 1])
class ReminderTests(PbcBase):
    def test_the_feed_and_the_scan_chase_the_assignee_once_per_window(self):
        today = timezone.localdate()
        late = self.raise_line(self.manager_client, title="Late", assignee=self.owner.pk,
                               due_date=str(today - timezone.timedelta(days=1))).data
        soon = self.raise_line(self.manager_client, title="Soon", assignee=self.owner.pk,
                               due_date=str(today + timezone.timedelta(days=6))).data
        self.raise_line(self.manager_client, title="Unowned", due_date=str(today - timezone.timedelta(days=2)))
        keys = [i["key"] for i in build_feed(self.owner)]
        self.assertIn(f"pbc-overdue:{late['id']}", keys)
        self.assertIn(f"pbc-due:{soon['id']}", keys)
        mgr = [i["key"] for i in build_feed(self.manager)]
        self.assertIn("digest-pbc-overdue", mgr)
        self.assertIn("digest-pbc-unassigned", mgr)

        # Three: the unowned overdue line is chased too, to the team alone.
        self.assertEqual(run_pbc_scan(dry_run=True), 3)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(run_pbc_scan(), 3)
        self.assertEqual(len(mail.outbox), 3)
        recipients = [set(m.to) for m in mail.outbox]
        self.assertIn({"owen@test.local", "grc@test.local"}, recipients)
        self.assertIn({"grc@test.local"}, recipients)
        self.assertTrue(any("[Overdue]" in m.subject for m in mail.outbox))
        self.assertEqual(PbcRequest.objects.get(pk=late["id"]).reminders_sent, [OVERDUE])
        self.assertEqual(PbcRequest.objects.get(pk=soon["id"]).reminders_sent, [7, 14, 30])
        self.assertEqual(run_pbc_scan(), 0)
        # A new due date restarts the clock; a provided line is not chased.
        self.manager_client.patch(f"/api/pbc-requests/{late['id']}/",
                                  {"due_date": str(today + timezone.timedelta(days=1))}, format="json")
        self.assertEqual(PbcRequest.objects.get(pk=late["id"]).reminders_sent, [])
        self.manager_client.post(f"/api/pbc-requests/{soon['id']}/provide/", {"response_note": "done"}, format="json")
        self.assertEqual(run_pbc_scan(), 1)

    def test_the_auditor_is_told_what_is_waiting_for_them(self):
        line = self.raise_line(self.auditor_client).data
        self.assertNotIn(f"pbc-awaiting:{self.package.pk}", [i["key"] for i in build_feed(self.auditor)])
        self.manager_client.post(f"/api/pbc-requests/{line['id']}/provide/", {"response_note": "x"}, format="json")
        feed = {i["key"]: i for i in build_feed(self.auditor)}
        self.assertIn(f"pbc-awaiting:{self.package.pk}", feed)
        self.assertIn("1 answer to review", feed[f"pbc-awaiting:{self.package.pk}"]["title"])
