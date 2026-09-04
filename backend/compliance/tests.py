"""Control library, evidence mapping RBAC and seed idempotence."""
from django.core.management import call_command

from compliance.models import Control, ControlEvidence, Framework
from documents.models import EDIT, VIEW, Folder
from testutils import APITestBase, grant, make_doc
from datetime import timedelta
from django.test import override_settings
from django.utils import timezone
from compliance import scoring
from compliance.models import Control, ControlEvidence, ControlMapping
from documents.access import accessible_folder_ids
from documents.models import Document
from governance.models import Risk
from audit.models import AuditLog


class ControlApiTests(APITestBase):
    def test_controls_are_readable_by_everyone_but_only_managers_patch(self):
        c = self.client_for(self.viewer)
        self.assertEqual(c.get("/api/controls/").status_code, 200)
        self.assertEqual(c.get(f"/api/frameworks/{self.tree.framework.key}/controls/").status_code, 200)
        self.assertEqual(c.patch(f"/api/controls/{self.tree.c1.pk}/", {"status": "implemented"}, format="json").status_code, 403)
        m = self.client_for(self.manager)
        r = m.patch(f"/api/controls/{self.tree.c1.pk}/", {"status": "implemented", "owner": self.owner.pk}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["owner_name"], "Owen Tester")
        # the catalog itself is not writable through the API
        self.assertEqual(m.post("/api/controls/", {"control_id": "X"}, format="json").status_code, 405)
        self.assertEqual(m.delete(f"/api/controls/{self.tree.c1.pk}/").status_code, 405)
        # identifying fields are read-only
        m.patch(f"/api/controls/{self.tree.c1.pk}/", {"control_id": "HACK", "title": "x"}, format="json")
        self.assertEqual(Control.objects.get(pk=self.tree.c1.pk).control_id, "TC1.1")

    def test_framework_counts(self):
        r = self.client_for(self.viewer).get("/api/frameworks/")
        fw = r.data["results"][0]
        self.assertEqual(fw["control_count"], 2)
        self.assertEqual(fw["implemented_count"], 0)


class EvidenceMappingTests(APITestBase):
    def setUp(self):
        super().setUp()
        self.doc = make_doc(self.tree.ctrl1, self.owner, name="ACP")

    def test_counts_respect_folder_visibility(self):
        ControlEvidence.objects.create(control=self.tree.c1, document=self.doc, linked_by=self.manager)
        vis = self.client_for(self.viewer).get(f"/api/controls/{self.tree.c1.pk}/").data
        self.assertEqual(vis["evidence_count"], 0)
        self.assertEqual(self.client_for(self.viewer).get("/api/control-evidence/").data["count"], 0)
        grant(self.tree.ctrl1, user=self.viewer, level=VIEW)
        vis = self.client_for(self.viewer).get(f"/api/controls/{self.tree.c1.pk}/").data
        self.assertEqual(vis["evidence_count"], 1)
        rows = self.client_for(self.viewer).get("/api/control-evidence/").data["results"]
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["can_unlink"])

    def test_link_requires_edit_or_framework_capability(self):
        payload = {"control": self.tree.c2.pk, "document": self.doc.pk, "note": "covers it"}
        # viewer can't even see the document
        self.assertEqual(self.client_for(self.viewer).post("/api/control-evidence/", payload, format="json").status_code, 403)
        grant(self.tree.ctrl1, user=self.viewer, level=VIEW)
        self.assertEqual(self.client_for(self.viewer).post("/api/control-evidence/", payload, format="json").status_code, 403)
        grant(self.tree.ctrl1, user=self.viewer, level=EDIT)
        r = self.client_for(self.viewer).post("/api/control-evidence/", payload, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.data["can_unlink"])
        self.assertEqual(ControlEvidence.objects.get(pk=r.data["id"]).linked_by, self.viewer)
        # duplicate link -> 400, not 500
        self.assertEqual(self.client_for(self.viewer).post("/api/control-evidence/", payload, format="json").status_code, 400)
        # an auditor is capped at view even with a manage grant: sees the link, cannot remove it
        grant(self.tree.ctrl1, user=self.auditor, level=EDIT)
        self.assertEqual(self.client_for(self.auditor).get(f"/api/control-evidence/{r.data['id']}/").status_code, 200)
        self.assertEqual(self.client_for(self.auditor).delete(f"/api/control-evidence/{r.data['id']}/").status_code, 403)
        self.assertEqual(self.client_for(self.manager).delete(f"/api/control-evidence/{r.data['id']}/").status_code, 204)
        # links are immutable
        self.assertEqual(self.client_for(self.manager).patch(f"/api/control-evidence/{r.data['id']}/", {"note": "x"}, format="json").status_code, 405)

    def test_bulk_attach_reports_skips(self):
        hidden = make_doc(self.tree.ctrl2, self.manager, name="hidden")
        grant(self.tree.ctrl1, user=self.owner, level=EDIT)
        ControlEvidence.objects.create(control=self.tree.c1, document=self.doc, linked_by=self.manager)
        r = self.client_for(self.owner).post("/api/control-evidence/bulk/", {
            "control": self.tree.c1.pk, "documents": [self.doc.pk, hidden.pk, 424242], "note": "audit prep",
        }, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["created"], [])
        reasons = {s["document"]: s["reason"] for s in r.data["skipped"]}
        self.assertEqual(reasons[self.doc.pk], "already linked")
        self.assertEqual(reasons[hidden.pk], "not found or not visible")
        self.assertEqual(reasons[424242], "not found or not visible")
        r = self.client_for(self.owner).post("/api/control-evidence/bulk/", {"control": self.tree.c2.pk, "documents": [self.doc.pk]}, format="json")
        self.assertEqual(len(r.data["created"]), 1)
        self.assertEqual(self.client_for(self.owner).post("/api/control-evidence/bulk/", {"control": 0, "documents": [1]}, format="json").status_code, 400)

    def test_choices_only_lists_visible_documents(self):
        make_doc(self.tree.ctrl2, self.manager, name="Other")
        grant(self.tree.ctrl1, user=self.viewer, level=VIEW)
        data = self.client_for(self.viewer).get("/api/control-evidence/choices/").data
        self.assertEqual([d["name"] for d in data["documents"]], ["ACP"])
        self.assertEqual(len(data["controls"]), 2)


class SeedTests(APITestBase):
    def test_seed_frameworks_is_idempotent_and_matches_the_documented_counts(self):
        call_command("seed_frameworks", "--with-folders", verbosity=0)
        counts = {
            fw.key: Control.objects.filter(category__framework=fw).count()
            for fw in Framework.objects.exclude(key="tfw")
        }
        self.assertEqual(counts, {"soc2": 61, "iso27001": 93, "pci_dss_v4": 63})
        folders_before = Folder.objects.count()
        call_command("seed_frameworks", "--with-folders", verbosity=0)
        self.assertEqual(Folder.objects.count(), folders_before)
        self.assertEqual(sum(counts.values()), 217)
        # every control has exactly one folder, every folder root is flagged
        real = Folder.objects.filter(control__isnull=False).exclude(control__category__framework__key="tfw")
        self.assertEqual(real.count(), 217)
        self.assertEqual(Folder.objects.filter(is_framework_root=True).count(), 4)  # 3 real + the test one
        # the ISO root name no longer carries a path separator
        self.assertFalse(Folder.objects.filter(is_framework_root=True, name__contains="/").exists())


class ReadinessScoringTests(APITestBase):
    """A control is "ready" when someone owns it, evidence exists, the evidence
    is current, it has been tested, and nothing is openly failing -- not when a
    box is ticked."""

    def setUp(self):
        super().setUp()
        self.control = self.tree.c1
        self.today = timezone.localdate()

    def _perfect(self):
        """Implemented, owned, one approved document due in 90 days, tested 10
        days ago, no open risks."""
        self.control.status = "implemented"
        self.control.owner = self.owner
        self.control.last_tested_on = self.today - timedelta(days=10)
        self.control.save()
        doc = make_doc(self.tree.ctrl1, owner=self.owner, name="Policy", days=90)
        ControlEvidence.objects.create(control=self.control, document=doc, linked_by=self.manager)
        return doc

    def _score(self, user=None):
        control = scoring.annotate(
            Control.objects.filter(pk=self.control.pk), user or self.admin
        ).get()
        return scoring.score_control(control, user or self.admin)

    def test_a_fully_evidenced_control_scores_one_hundred(self):
        self._perfect()
        result = self._score()
        self.assertEqual(result["score"], 100)
        self.assertEqual(result["band"], "ready")
        self.assertIsNone(result["next_best_action"])

    def test_each_missing_signal_costs_exactly_its_weight(self):
        doc = self._perfect()
        self.assertEqual(self._score()["score"], 100)

        self.control.owner = None
        self.control.save()
        self.assertEqual(self._score()["score"], 90, "owner is worth 10")

        self.control.last_tested_on = None
        self.control.save()
        self.assertEqual(self._score()["score"], 75, "testing is worth 15")

        ControlEvidence.objects.all().delete()
        doc.delete()
        # evidence (20) and freshness (20) both fall away together.
        self.assertEqual(self._score()["score"], 35)

        self.control.status = "in_progress"
        self.control.save()
        self.assertEqual(self._score()["score"], 14)

    def test_not_applicable_controls_are_unscored_and_excluded(self):
        self.control.status = "not_applicable"
        self.control.save()
        result = self._score()
        self.assertIsNone(result["score"])
        self.assertEqual(result["band"], "not_applicable")
        self.assertEqual(result["band_label"], "Excluded")

    def test_freshness_grades_on_the_freshest_approved_document(self):
        """One current approved policy satisfies the control even if a stale
        one is also linked."""
        self._perfect()
        stale = make_doc(self.tree.ctrl1, owner=self.owner, name="Old policy", days=-400)
        ControlEvidence.objects.create(control=self.control, document=stale, linked_by=self.manager)
        self.assertEqual(self._score()["score"], 100)

    def test_evidence_with_no_review_schedule_scores_zero_freshness(self):
        """Otherwise the one document nobody will ever chase becomes the
        best-scoring evidence you can attach."""
        self.control.status = "implemented"
        self.control.owner = self.owner
        self.control.last_tested_on = self.today
        self.control.save()
        doc = make_doc(self.tree.ctrl1, owner=self.owner, name="Undated", cadence="none")
        Document.objects.filter(pk=doc.pk).update(next_review_date=None)
        ControlEvidence.objects.create(control=self.control, document=doc, linked_by=self.manager)
        result = self._score()
        self.assertEqual(result["score"], 80)
        freshness = next(c for c in result["components"] if c["key"] == "freshness")
        self.assertEqual(freshness["points"], 0)
        self.assertIn("no review schedule", freshness["detail"])

    def test_overdue_evidence_loses_freshness_by_degrees(self):
        self._perfect()
        doc = Document.objects.get(name="Policy")
        for days, expected in [(10, 95), (-10, 88), (-400, 80)]:
            Document.objects.filter(pk=doc.pk).update(
                next_review_date=self.today + timedelta(days=days))
            self.assertEqual(self._score()["score"], expected, f"{days} days")

    def test_open_risks_subtract_and_the_score_floors_at_zero(self):
        self._perfect()
        # Two evidence links AND two risks: the only shape that catches a
        # dropped distinct=True on either annotation.
        second = make_doc(self.tree.ctrl1, owner=self.owner, name="Second policy", days=90)
        ControlEvidence.objects.create(control=self.control, document=second, linked_by=self.manager)
        Risk.objects.create(title="Gap one", control=self.control, status="open")
        self.assertEqual(self._score()["score"], 90, "one risk costs half the penalty")
        Risk.objects.create(title="Gap two", control=self.control, status="mitigating")
        self.assertEqual(self._score()["score"], 80, "two or more costs all of it")

        bare = self.tree.c2
        Risk.objects.create(title="Gap three", control=bare, status="open")
        Risk.objects.create(title="Gap four", control=bare, status="open")
        scored = scoring.score_control(
            scoring.annotate(Control.objects.filter(pk=bare.pk), self.admin).get(), self.admin)
        self.assertEqual(scored["score"], 0, "the score never goes negative")

    def test_closed_risks_do_not_count_against_a_control(self):
        self._perfect()
        Risk.objects.create(title="Closed gap", control=self.control, status="closed")
        Risk.objects.create(title="Accepted gap", control=self.control, status="accepted")
        self.assertEqual(self._score()["score"], 100)

    def test_evidence_components_respect_folder_visibility(self):
        """An org-wide per-control integer handed to a folder-restricted
        auditor is losslessly invertible into whether hidden evidence exists."""
        self._perfect()
        self.assertEqual(self._score(self.admin)["score"], 100)
        # aria holds no folder grants, so the evidence is invisible to her and
        # must not show up in her score.
        self.assertEqual(accessible_folder_ids(self.auditor), set())
        self.assertEqual(self._score(self.auditor)["score"], 60)

    def test_weights_are_normalised_so_doubling_them_changes_nothing(self):
        self._perfect()
        base = self._score()["score"]
        doubled = {k: v * 2 for k, v in scoring.DEFAULT_WEIGHTS.items()}
        with override_settings(READINESS_WEIGHTS=doubled):
            self.assertEqual(self._score()["score"], base)

    def test_a_partial_weight_override_merges_over_the_defaults(self):
        self._perfect()
        with override_settings(READINESS_WEIGHTS={"owner": 0}):
            result = self._score()
            self.assertEqual(result["score"], 100, "the other five still sum to the whole")
            owner = next(c for c in result["components"] if c["key"] == "owner")
            self.assertEqual(owner["weight"], 0)

    def test_bands_are_configurable(self):
        self._perfect()
        self.control.owner = None
        self.control.save()
        self.assertEqual(self._score()["band"], "ready")   # 90 with 40,70,90
        with override_settings(READINESS_BANDS=[50, 80, 95]):
            self.assertEqual(self._score()["band"], "nearly")

    def test_band_labels_are_honest_and_do_not_collide_with_statuses(self):
        """Two adjacent chips both called 'Not started' would be unusable --
        and 'Unscored' would be a lie, because a control in the lowest band
        does have a score."""
        labels = set(scoring.BAND_LABELS.values())
        self.assertNotIn("Not started", labels)
        self.assertNotIn("Not applicable", labels)
        self.assertNotIn("Unscored", labels)
        self.assertEqual(scoring.BAND_LABELS["not_started"], "Not ready")

    def test_a_low_but_real_score_is_not_labelled_as_having_none(self):
        self.control.status = "implemented"   # 35 of 100
        self.control.save()
        result = self._score()
        self.assertEqual(result["score"], 35)
        self.assertEqual(result["band_label"], "Not ready")
        self.assertIsNotNone(result["score"], "only not_applicable is unscored")

    def test_the_breakdown_endpoint_explains_every_component(self):
        self._perfect()
        self.control.owner = None
        self.control.save()
        r = self.client_for(self.manager).get(f"/api/controls/{self.control.pk}/readiness/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["score"], 90)
        keys = [c["key"] for c in r.data["components"]]
        self.assertEqual(keys, ["implementation", "owner", "evidence", "freshness", "testing"])
        self.assertTrue(all(c["detail"] for c in r.data["components"]))
        self.assertEqual(r.data["next_best_action"], "Assign an owner.")

    def test_the_next_best_action_is_the_biggest_gap_not_the_first(self):
        """A control missing 15 points of testing and 5 of freshness should be
        told to record a test, not to tidy the review date."""
        self._perfect()
        doc = Document.objects.get(name="Policy")
        Document.objects.filter(pk=doc.pk).update(
            next_review_date=self.today + timedelta(days=10))  # freshness 15/20
        self.control.last_tested_on = None                      # testing 0/15
        self.control.save()
        self.assertEqual(self._score()["next_best_action"],
                         "Record a test date for this control.")

    def test_the_register_reports_the_score_without_a_query_per_row(self):
        self._perfect()
        c = self.client_for(self.manager)
        with self.assertNumQueries(4):
            r = c.get("/api/controls/")
        row = next(x for x in r.data["results"] if x["id"] == self.control.pk)
        self.assertEqual(row["readiness_score"], 100)
        self.assertEqual(row["readiness_band_label"], "Ready")

    def test_recording_a_test_stamps_who_and_when_and_audits_it(self):
        c = self.client_for(self.manager)
        r = c.patch(f"/api/controls/{self.control.pk}/",
                    {"last_tested_on": str(self.today)}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.control.refresh_from_db()
        self.assertEqual(self.control.last_tested_by, self.manager)
        self.assertIsNotNone(self.control.last_tested_recorded_at)
        # The middleware also logs the PATCH (field names only). The row that
        # matters is the explicit one naming the old and new dates.
        self.assertTrue(
            AuditLog.objects.filter(object_type="controls",
                                    detail__contains="last_tested_on never ->").exists(),
            [e.detail for e in AuditLog.objects.filter(object_type="controls")])

    def test_a_future_test_date_and_a_silly_interval_are_refused(self):
        c = self.client_for(self.manager)
        r = c.patch(f"/api/controls/{self.control.pk}/",
                    {"last_tested_on": str(self.today + timedelta(days=1))}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("last_tested_on", r.data)
        r = c.patch(f"/api/controls/{self.control.pk}/",
                    {"test_interval_days": 0}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_the_export_carries_the_score_the_band_and_the_test_date(self):
        self._perfect()
        r = self.client_for(self.manager).get("/api/controls/export/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode("utf-8")
        header = body.splitlines()[0]
        for column in ("Readiness", "Band", "Last tested"):
            self.assertIn(column, header)
        self.assertIn("Ready", body)

    def test_the_crosswalk_does_not_score_and_does_not_regress_into_n_plus_one(self):
        self._perfect()
        mapping = ControlMapping.objects.create(theme="Access control")
        mapping.controls.add(self.tree.c1, self.tree.c2)
        c = self.client_for(self.manager)
        with self.assertNumQueries(5):
            r = c.get("/api/crosswalk/")
        control = r.data["results"][0]["controls"][0]
        self.assertNotIn("readiness_score", control)
