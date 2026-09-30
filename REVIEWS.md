# Security and code reviews

This document consolidates six review records of Conformiti core: one
internal line-by-line review (0.2.0) and five independent reviews (an
adversarial review of 0.9.0, a source review of 0.9.5, and three further
source reviews closed in 0.9.5f, 0.9.5h and 0.9.5i). For each review it gives
the method, every finding, and where the finding stands today.

The finding identifiers (S-1, M-4, L-8 and so on) are the ones the code, the
tests and the changelog cite. They are kept exactly as the original review
records numbered them. The same identifier recurs across reviews (an S-1 in
the 0.9.5 review and an S-01 in the 0.2.0 review, an M-1 in three reviews), so
a citation always names its review: "0.9.5 review, S-3" or "0.9.5f review,
H-3". Reviews are named by the release that closed them, as the code comments
do, with the release reviewed given in the heading. SECURITY.md lists the same
reviews by the release each one reviewed, so its 0.9.5e review is the "0.9.5f
review" here.

**Status means status at v0.9.5ma (HEAD b580826).** How a status was set:

- *Fixed*: the named function, setting or file was read at that commit and
  the fix is there, and the backend test modules that lock it pass.
- *Fixed (not re-verified)*, or a stated part that was not re-checked:
  something the tree cannot show on its own (a browser rendering, `npm
  audit`).
- *Accepted* and *Deferred*: the finding was left as it is, on the reasoning
  given under "Deferred and accepted".
- *Regressed*: a fix that has gone. None was found.

Limits of the re-check: the backend suite (829 tests, 1 skipped) was run
against SQLite with the password hasher swapped for a fast one, and passed.
`tools/validate.py` passed (20 checks). The frontend build, the Playwright
suite, `npm audit` and the container and compose jobs were not re-run for this
document. Where no test in the tree exercises a fixed behaviour, the row says
so.

## Summary

| Review | Kind | Reviewed | Findings | Fixed | Deferred or accepted | Open | Fixed in |
|---|---|---|---|---|---|---|---|
| 0.2.0, line by line | internal | 0.1.1 | 34 | 32 | 2 | 0 | 0.2.0 |
| 0.9.0, adversarial | independent | 0.9.0 | 50 (of 69 candidates) | 48 in full, 2 in part | 1 part (H-16) | 1 part (H-14) | 0.9.1 to 0.9.4 |
| 0.9.5, source review | independent | 0.9.5 | 9, plus 2 found while fixing | 11 | 0 | 0 | 0.9.5b |
| 0.9.5f, fourth independent | independent | 0.9.5e | 14, plus 3 raised in passing | 17 | 0 | 0 | 0.9.5f (0.9.5g for one follow-up) |
| 0.9.5h, fifth independent | independent | 0.9.5g | 14 | 13 | 1 | 0 | 0.9.5h |
| 0.9.5i, sixth independent | independent | 0.9.5h | 3 | 3 | 0 | 0 | 0.9.5i |

Notes on the counts:

- 0.2.0: 19 security findings (S-01 to S-19), 10 on correctness and
  operations (C-01 to C-10), 5 on the interface (U-01 to U-05). Two of the 32
  fixed carry a limited check (U-02, U-03), and one has a part not re-run
  (C-04). Four deliberate non-changes named in the review (its section 3) are
  not numbered findings and are listed under "Deferred and accepted".
- 0.9.0: 69 candidates, 50 confirmed, 5 contested, 14 killed in
  verification. The review counts all 50 as fixed. Two were closed in part
  only: H-14 (the throttle key was fixed, no account lockout was added) and
  H-16 (quarantined bytes are no longer archived, but a new version still
  clears quarantine). The 5 contested were not fixed on that evidence; each
  is taken up under "Deferred and accepted" with its status today.
- Other reviews listed in `SECURITY.md` have no review record of their own and
  are not consolidated here: the 0.1.0 first pass, the 0.9.4 review, the 0.9.5j
  code review, the 0.9.5l post-release install check and the 0.9.5m release
  review. `CHANGELOG.md` describes them.

---

## 0.2.0 review: internal, line by line (v0.1.1)

Internal, dated 2026-09-03, of the whole repository at v0.1.1: backend,
frontend, installers, containers and documentation. Every app and page was
read in full, the running system was driven over HTTP (five personas,
adversarial requests, the installer on Windows, the compose stack in Docker),
and a test was written for each finding. Two more defects (S-19, C-10) were
found afterwards by running the release rather than reading it. Severity:
High is exploitable for data loss, escalation or denial of service; Medium is
a control materially weaker than documented; Low is hardening; Info is a
noted limit.

### Security

| ID | Sev | Finding | Status at 0.9.5ma |
|---|---|---|---|
| S-01 | High | Folder parent cycle loops forever in every access check | Fixed. `Folder.ancestors` (bounded, raises), `Folder.would_cycle`, `FolderSerializer.validate_parent`; `FolderIntegrityTests` |
| S-02 | High | Re-parenting planted a subtree under a folder the mover could not see | Fixed. `FolderViewSet.perform_update`: manage on the folder, edit on the destination, top level needs the folders capability, seeded folders immovable; `FolderIntegrityTests` |
| S-03 | High | Refresh tokens neither rotated nor revocable | Fixed. `ROTATE_REFRESH_TOKENS`, `BLACKLIST_AFTER_ROTATION`, `LogoutView`, weekly `accounts.tasks.flush_expired_tokens`, rotated token stored in `frontend/src/api/client.js`; `TokenLifecycleTests`. Later hardened by 0.9.5f M-4 |
| S-04 | Med | Throttle counters per process | Fixed. `CACHE_URL` selects Redis in `config/settings.py`, compose sets it; without it the boot emits a warning and each worker counts alone |
| S-05 | Med | Owner could delete own evidence with view-only folder access | Fixed. `documents/permissions.py` (DELETE needs manage); `DocumentLifecycleTests.test_owner_may_edit_but_not_delete_without_manage` |
| S-06 | Med | No upload size or type limit | Fixed. `validate_upload` in `documents/uploads.py` on every upload path, `MAX_UPLOAD_MB`, nginx `/media/` sandbox CSP; `test_upload_size_ceiling`, `test_active_content_extensions_are_refused`. Extended by 0.9.5 S-4 and 0.9.5f M-2 |
| S-07 | Med | Auth events absent from the audit trail, mutation entries recorded the path only | Fixed. `audit/events.py`, `audit/middleware.py` (`SENSITIVE_KEYS` excluded); `AuditMiddlewareTests`, `LoginTests` |
| S-08 | Med | Docker path ran DEBUG on with the published placeholder key | Fixed. Compose sets `DJANGO_DEBUG: ${CONFORMITI_DEBUG:-false}`, key generated into a volume. Two follow-ups: S-19 and 0.9.5f H-3 |
| S-09 | Med | API and admin published on all interfaces, browsable API on | Fixed. Compose publishes `127.0.0.1:${CONFORMITI_API_PORT:-8000}`; `DEFAULT_RENDERER_CLASSES` is JSON only off DEBUG |
| S-10 | Low | Built-in role flags editable through the API | Fixed. `RoleViewSet.perform_update`; `test_builtin_role_flags_are_locked_but_custom_roles_work` |
| S-11 | Low | Non-superuser admin could reset a superuser's MFA | Fixed. `UserViewSet.reset_mfa` |
| S-12 | Low | Folder names unvalidated | Fixed. `validate_folder_name` (`documents/models.py`), migration 0002; `test_folder_names_are_single_path_segments` |
| S-13 | Low | Notification dismiss accepted arbitrary keys | Fixed. `NotificationDismissView` accepts only keys in the caller's live feed; `test_mark_read_and_dismiss` |
| S-14 | Low | CSP shipped commented out (inline script) | Fixed. `frontend/public/theme-init.js`; nginx sends a CSP with `script-src 'self' 'wasm-unsafe-eval'` |
| S-15 | Low | Password minimum 8 | Fixed. `PASSWORD_MIN_LENGTH` defaults to 12 |
| S-16 | Low | Container ran as root | Fixed. `backend/Dockerfile` creates uid 10001 and sets `USER app` |
| S-17 | Info | `GET /users/` readable by every signed-in user | Accepted; see below |
| S-18 | Info | MFA challenge confirms the password before asking for the code | Accepted; see below |
| S-19 | High | `DEBUG=true` from a developer `.env` leaked into the Docker stack | Fixed. Compose reads `CONFORMITI_DEBUG` and `CONFORMITI_SECRET_KEY`; validator check 16 (compose isolation) passes |

### Correctness and operations

| ID | Sev | Finding | Status at 0.9.5ma |
|---|---|---|---|
| C-01 | High | Installers and container ran `makemigrations` at install time | Fixed. `install.sh` and `install.ps1` run only `makemigrations --check`; `entrypoint.sh` applies shipped migrations; CI runs `--check`; validator check 2 fails on any other use |
| C-02 | Med | `install.ps1` ignored native exit codes and versions | Fixed. `Fail` on non-zero `$LASTEXITCODE`, Python 3.11+ and Node 20.19+ checks in `install.ps1`, matching checks in `install.sh` |
| C-03 | Med | Celery beat "24 h after start" schedule, worker started before migrations | Fixed. `crontab(hour=REVIEW_SCAN_HOUR)` in settings; compose `depends_on` uses `service_healthy`; a separate `beat` service since 0.9.5 |
| C-04 | Med | End-of-life Django, React Router advisories, psycopg2 | Fixed (versions re-verified, `npm audit` not re-run). `requirements.txt`: Django `>=5.2.17,<6.0`, `psycopg[binary]>=3.3.5`; `package.json`: react-router-dom `^7.9.0`, vite `^8.2.2` (Vite 7 at the time) |
| C-05 | Low | `date.today()` ignored `TIME_ZONE` | Fixed. `timezone.localdate()` in analytics, attestations, notifications; only the demo seeder (`bootstrap_demo`) still calls `date.today()` |
| C-06 | Low | Duplicate evidence link or group membership gave a 500 | Fixed. Unique constraints with serializer validation; tests in `compliance/tests.py` ("duplicate link -> 400") and `governance/tests.py` ("duplicate membership is a 400") |
| C-07 | Low | `LICENSE` missing | Fixed. MIT `LICENSE` at the repository root |
| C-08 | Low | No health endpoint | Fixed. `/api/health/` (`config/health.py`), compose healthchecks |
| C-09 | Low | No tests, no CI | Fixed. `.github/workflows/ci.yml`; the backend suite is 829 tests at 0.9.5ma |
| C-10 | Med | Audit-log filter dropdowns listed each action once per entry | Fixed. `AuditLogViewSet.facets` uses `.order_by()` before `.distinct()`; `test_facets_are_deduplicated` |

### Interface

| ID | Sev | Finding | Status at 0.9.5ma |
|---|---|---|---|
| U-01 | Med | Write controls shown to roles the API rejects | Fixed. `can_unlink` (`compliance/serializers.py`, `ControlDetail.jsx`), `manage_users` gate (`pages/UserAudit.jsx`, `canWrite`), skipped reasons surfaced (`ControlDetail.jsx`) |
| U-02 | Med | Folder tree, tabs, chips and rows not keyboard-operable | Fixed for the folder tree (`FolderTree.jsx`: `role="tree"`, arrow keys); tabs, chips and rows not re-verified |
| U-03 | Low | Light-only backgrounds broke the dark themes | Fixed (not re-verified). Needs a browser; not checked |
| U-04 | Low | Login screen always advertised the demo password | Fixed. `Login.jsx` shows a notice only while `/api/health/` reports demo accounts; it no longer prints a password (0.9.0 C-2) |
| U-05 | Low | Sign-out revoked nothing server-side | Fixed. See S-03 |

---

## 0.9.0 review: adversarial (v0.9.0)

Independent, dated 2026-09-07, of the whole repository at v0.9.0 (`0ded621`).
Sixteen reviewers each attacked one dimension (tenancy, authentication, single
sign-on, authorisation, the unauthenticated surface, file ingest, cryptography,
injection and SSRF, the browser, concurrency, background jobs, denial of
service, deployment). Every candidate was then attacked by three more (can it
be carried out, does the cited code say this, is it already mitigated) and was
listed only if two of the three could not kill it. Result: 69 candidates, 50
confirmed (3 Critical, 25 High, 12 Medium, 10 Low), 5 contested, 14 killed.

Identifiers: the review numbers findings inside each severity table, so they
are written here C-1 to C-3 (Critical), H-1 to H-25, M-1 to M-12 and L-1 to
L-10, as later reviews cite them ("M-1" in the 0.9.5f review). Several
findings are one defect reached from two directions and were verified
separately; a row says "same as" where the fix is shared. The original tables
truncate the titles; the titles below are completed from the code.

### Critical

| ID | Finding | Fixed in | Status at 0.9.5ma |
|---|---|---|---|
| C-1 | Docker stack seeded a superuser with a published password | 0.9.2 | Fixed. `bootstrap_demo` generates the password per installation (`secrets.token_urlsafe`, or `DEMO_PASSWORD`); the demo is not seeded unless `SEED_DEMO_DATA=true` (0.9.5 S-9); `accounts/tests_demo.py` |
| C-2 | Login page printed working superuser credentials | 0.9.1 | Fixed. `Login.jsx` says the demo accounts exist and how to retire them; no password is printed |
| C-3 | Sealed-manifest workpaper fields writable after sealing | 0.9.1 | Fixed. `PackageControlViewSet.perform_update` authorises the whole request, then saves once; `SealedManifestTests` |

### High

| ID | Finding | Fixed in | Status at 0.9.5ma |
|---|---|---|---|
| H-1 | PATCH on package evidence re-pointed `document` without `assert_pinnable` | 0.9.1 | Fixed. `PackageEvidenceViewSet.perform_update`: `document` and `package_control` fixed once pinned; `test_a_pinned_artefact_cannot_be_repointed` |
| H-2 | PATCH on package samples with only `package_control` ran no authorisation | 0.9.1 | Fixed. `PackageSampleViewSet.perform_update` needs the assemble capability when no result or item field is touched; `test_a_sample_row_needs_a_reason_to_be_touched` |
| H-3 | Audit rows stamped with the actor's workspace, not the action's | 0.9.2 | Fixed. `AuditLog` is a `TenantModel` stamped with the active workspace; `accounts/tests_tenancy.py`, `test_save_with_nothing_to_go_on_refuses` |
| H-4 | A superuser's writes in a switched workspace audited into their own | 0.9.2 | Fixed. Same code and test as H-3 |
| H-5 | One installation-wide signing key, manifest with no tenant identity | 0.9.3 | Fixed. `derive_workspace_key` (HKDF over the workspace slug) in `attestations/signing.py`, manifest names the workspace; `ManifestIdentityTests`, `PerWorkspaceKeyTests` |
| H-6 | Per-IP throttles keyed on the whole `X-Forwarded-For` header | 0.9.1 | Fixed. `NUM_PROXIES` defaults to 1 in `config/settings.py`; boot warning when `BEHIND_TLS` is set and `NUM_PROXIES` is not (0.9.5h M-4). No test drives a rotating header against a throttle |
| H-7 | Django admin login bypassed MFA, the throttle and the archived-workspace refusal | 0.9.3 | Fixed. `accounts/tests_admin_login.py` (`AdminLoginTests`, `AdminSessionIsNotAnApiCredentialTests`); `SessionAuthentication` is DEBUG-only |
| H-8 | SSO account resolution ran with no active workspace | 0.9.2 | Fixed. `sso_workspace` and `resolve_user` in `accounts/oidc.py` link, match and provision inside `SSO_WORKSPACE`; an identity whose account is in another workspace is refused. No test names the cross-workspace case |
| H-9 | A revoked or expired grant did not stop an auditor reading evidence bytes through PBC assignment | 0.9.2 | Fixed. `readable_pbc_requests` (`attestations/access.py`) gives an auditor the request list through the grant only; `attestations/tests_pbc.py` |
| H-10 | Auditor could write the management response and mutate sealed sampling data | 0.9.1 | Fixed. `PackageControlViewSet.perform_update`; `SealedManifestTests`, `attestations/tests.py` `test_the_management_response_is_written_by_the_organisation_not_the_auditor` |
| H-11 | `Folder.owner` writable with EDIT, and owner means MANAGE | 0.9.1 | Fixed. `FolderViewSet.perform_update`; `test_taking_folder_ownership_needs_manage` |
| H-12 | PATCH on a document replaced the stored bytes with no edit check, scan or version | 0.9.1 | Fixed. `DocumentViewSet.perform_update` refuses `file`; `new_version` takes edit, scans, archives, bumps; `test_patching_a_file_is_refused` |
| H-13 | The Auditor role read the whole workspace | 0.9.4 | Fixed. Default permissions are `IsAuthenticated` plus `NotExternalAuditor`; routes an auditor may reach are an explicit allow-list walked by `accounts/tests_auditor_surface.py`. The audit log and access reviews stay readable by design (see Deferred and accepted) |
| H-14 | Rate limits keyed on `X-Forwarded-For`, and no account lockout | 0.9.1 | Fixed for the header keying (see H-6). No per-account lockout exists: limits are per client address (see Deferred and accepted) |
| H-15 | PATCH replaced document bytes with no scan or version snapshot | 0.9.1 | Same as H-12 |
| H-16 | A new version silently released a quarantined document and kept its bytes downloadable | 0.9.1 | Fixed for the bytes: `new_version` no longer archives quarantined bytes. A new version still clears quarantine, after a scan when scanning is on and without one when it is off (see Deferred and accepted); `test_uploads_are_marked_clean_and_a_new_version_resets_the_verdict` |
| H-17 | The audit-package ZIP streamed quarantined bytes to the auditor | 0.9.1 | Fixed. `write_bundle` (`attestations/bundle.py`) calls `refuse_if_quarantined` before writing. No test in the tree drives the export against a quarantined file; a throwaway check returned 403 |
| H-18 | PATCH re-pointed a pinned row at any document, bypassing folder permission | 0.9.1 | Same as H-1 |
| H-19 | A sealed, signed package could gain evidence rows and `/verify/` still said ok | 0.9.2 | Fixed. `package_control` fixed once pinned and `assert_open` in `PackageEvidenceViewSet.perform_update`; `lock_open` on create and delete |
| H-20 | An auditor kept reading PBC attachments after revocation by self-assigning | 0.9.2 | Same as H-9; `test_patching_an_assignee_onto_their_own_line_is_refused_too` |
| H-21 | Meeting minutes and form templates downloadable by every account, auditors included | 0.9.2 | Fixed. `MeetingMinuteViewSet.download` refuses auditors; both are on the denied list in `tests_auditor_surface.py` |
| H-22 | The signature covered only `manifest.json`; conclusions sat outside it | 0.9.3 | Fixed. `write_bundle` also signs `SHA256SUMS`; `attestations/verifier.py` checks both; `BundleSignatureCoverageTests`, `tests_release_095.py` |
| H-23 | One installation key signed every workspace's packages | 0.9.3 | Same as H-5 |
| H-24 | Sidebar showed the superuser's home workspace, not the active one | 0.9.2 | Fixed. `UserSerializer.get_active_workspace`, `Sidebar.jsx` |
| H-25 | A write refused with 403 had already been committed | 0.9.1 | Fixed. Same code as C-3; `test_a_refused_mixed_write_commits_nothing` |

### Medium

| ID | Finding | Fixed in | Status at 0.9.5ma |
|---|---|---|---|
| M-1 | Cross-workspace username oracle (DRF check workspace-pinned, constraint global) | 0.9.2 | Fixed. `UserWriteSerializer.validate_username`; the first fix was a no-op and was redone in 0.9.5f M-3; `CrossTenantUniquenessTests` |
| M-2 | A tenant administrator read every organisation's webhook delivery log | 0.9.2 | Fixed. `ChannelsView.get` returns `deliveries` to a superuser only; `test_the_channels_endpoint_and_the_test_message` (`notifications/tests_channels.py`) |
| M-3 | Changing a password or resetting MFA revoked nothing | 0.9.2 | Fixed. `end_all_sessions` (`accounts/session_views.py`) called from the serializers and `reset_mfa`; `accounts/tests_release_095.py` `test_setting_somebody_elses_password_revokes_their_refresh_tokens`. The Django admin half was not in force until 0.9.5mb: see 0.9.5f M-4. Access tokens: 0.9.5f M-4 |
| M-4 | A TOTP code was accepted repeatedly for up to 90 seconds | 0.9.4 | Fixed. Last accepted time step recorded on the device, claimed by a conditional UPDATE; `TotpReplayTests` |
| M-5 | SSO provisioning probed username uniqueness workspace-scoped | 0.9.2 | Fixed. `_unique_username` (`accounts/oidc.py`) runs unscoped |
| M-6 | XLSX importer trusted declared sizes, then decompressed unbounded | 0.9.2 | Fixed. `_bounded_read` in `governance/risk_import.py`; no test in the tree names it; a throwaway check confirmed the ceiling |
| M-7 | In-app signature verification trusted the key stored in the same row | 0.9.4 | Fixed. `signature_status` (`attestations/signing.py`) checks the registered key for that key id and organisation; `SignatureStatusTests` |
| M-8 | Unbounded XLSX column index allocated gigabytes | 0.9.2 | Fixed. `MAX_COLS` (512) in `governance/risk_import.py`; same check and same gap as M-6 |
| M-9 | Vendor column headings written to the matrix CSV without `csv_safe` | 0.9.2 | Fixed. `csv_safe` on the vendor-layout headings in `matrix_export` (`vendors/views.py`); `vendors/tests.py` covers the export, not a formula in a heading |
| M-10 | Switched-workspace choice survived a change of user | 0.9.2 | Fixed. `login()` calls `clearSession()`, which clears the workspace choice (`frontend/src/api/client.js`). Browser suite not re-run |
| M-11 | Sealing was check-then-act with no row lock | 0.9.4 | Fixed. `lock_open` (`select_for_update`) on seal, pin, unpin; `SealLockTests` |
| M-12 | Quarantine events from the sweep landed with no workspace | 0.9.2 | Fixed. `workspace_id=document.workspace_id` in `documents/monitor.py` |

### Low

| ID | Finding | Fixed in | Status at 0.9.5ma |
|---|---|---|---|
| L-1 | Every workspace's reminders went to one installation-wide address | 0.9.4 | Fixed. `compliance_inbox` (`notifications/tasks.py`) uses the workspace's own address; the installation setting remains the fallback; `ComplianceInboxTests` |
| L-2 | `TenantQuerySet._pin()` skipped the filter on a sliced queryset | 0.9.4 | Fixed. `tenancy.UnscopedRead` is raised instead; `SlicedQuerysetTests` |
| L-3 | Passkey enrolment needed no re-authentication | 0.9.4 | Fixed. `reauthenticated` (`accounts/reauth.py`) guards passkey enrolment; widened to the authenticator app in 0.9.5f H-1 |
| L-4 | Default `SSO_MFA_ASSERTIONS` accepted `amr` values that are not second factors | 0.9.4 | Fixed. `user` and `pin` are out of the default in `config/settings.py`; `SsoAssertionDefaultTests` |
| L-5 | Folder access map readable with only VIEW | 0.9.2 | Fixed. `FolderViewSet.permissions` needs manage, or the folders or view-all capability, or superuser |
| L-6 | Health endpoint disclosed the signing key's filesystem path | 0.9.2 | Fixed. `signing_state` (`config/health.py`) returns `"misconfigured"`, never the error text. No test names it |
| L-7 | Switching to the workspace slugged "default" landed in the home workspace | 0.9.2 | Fixed. `Account.jsx` always sends the slug. Browser suite not re-run |
| L-8 | Every page fetched a webfont from Google | 0.9.4 | Fixed. No third-party reference in `frontend/index.html` or `nginx.conf`; validator check 18 |
| L-9 | Backup codes single-use only in Python | 0.9.4 | Fixed. Conditional UPDATE in `verify_backup_code`; `BackupCodeClaimTests` |
| L-10 | Two concurrent questionnaire sends left two live links | 0.9.4 | Fixed. The vendor row is locked during the swap (`vendors/questionnaire.py`); `test_a_second_send_supersedes_the_first` covers the outcome, not the race |

---

## 0.9.5 review: source review of v0.9.5, closed in 0.9.5b

Independent source review of v0.9.5 (local `a96ff49`, publish `85e5f00`),
received 2026-09-12 and fixed 2026-09-15 in 0.9.5b. Every finding was checked
against the tree before it was accepted: 9 received, 9 verified, none
rejected; S-7 is real but reaches less far than reported and was re-scored.
Each fix has a test that fails against 0.9.5. Two more defects were found
while fixing and are listed as (a) and (b) below.

| ID | Sev | Finding | Status at 0.9.5ma |
|---|---|---|---|
| S-1 | High | Slack and Teams webhook URLs returned to every signed-in member, auditors included | Fixed. `WorkspaceSerializer` (`accounts/workspace_views.py`): URLs write-only, `*_configured` booleans, non-superusers get `PUBLIC_FIELDS` only (today that adds `can_switch`); `Account.jsx` sends a webhook only when typed; `WebhookSecrecyTests`, `tests_auditor_surface.py`, `e2e/tests/settings.spec.js` |
| S-2 | Med | Slack host check was a substring test, Teams had none, dispatcher followed redirects | Fixed. `config/outbound.py` (`check_shape`, `assert_safe_url`, `NoRedirect`, pinned connection), run by `validate_webhook_url` at save and `webhooks._post` before every send; host lists in settings; `config/tests_outbound.py`, `WebhookDestinationTests` |
| S-3 | Med | Webhook URLs stored in plaintext, admin skipped the serializer | Fixed. `EncryptedCharField(max_length=800, aad_from="id")` on both columns, migration `0011_encrypt_webhooks`, `Workspace.clean`; `WebhookAtRestTests` |
| S-4 | Med | Macro-enabled Office documents accepted as evidence | Fixed. `BLOCKED_EXTENSIONS` and `_holds_macros` in `documents/uploads.py` (opens `.docx`, `.xlsx`, `.pptx` and refuses macro parts); `documents/tests.py`. Scanning stays off by default (see Deferred and accepted) |
| S-5 | Med | Mailed questionnaire links fell back to the request `Origin` | Fixed. `public_base` (`vendors/questionnaire.py`) raises `LinkBaseUnset` off DEBUG without `PUBLIC_URL`; `QuestionnaireLinkBaseTests` |
| S-6 | Low to Med | SAML `Destination` and `Recipient` accepted when absent | Fixed. Both required in `accounts/saml.py`; `SAML_ACS_URL` and `OIDC_REDIRECT_URI` required only with SSO on, off DEBUG, and `DJANGO_ALLOWED_HOSTS=*` (`config/settings.py`); `tests_saml.py` |
| S-7 | Low | Sign-out could not see the refresh cookie | Fixed. `POST /api/auth/token/clear/` (`config/urls.py`) inside the cookie's path, used first by `client.js`; `SignOutTests` |
| S-8 | Low | Signing-key directory distinguished a real slug from a wrong one | Superseded by 0.9.5f L-2. The 400 for an unknown slug that fixed it is not today's behaviour: an unknown slug now answers 200 with an empty list, like an organisation that never signed (`SigningKeysView`). See 0.9.5f L-2 |
| S-9 | Info | Demo dataset seeded by default and advertised on the health endpoint | Fixed for the default: `SEED_DEMO_DATA` defaults to false in compose, `entrypoint.sh` and both installers (`--demo` and `-Demo` opt in). `demo_accounts` stays on the health payload (see Deferred and accepted) |
| (a) | n/a | Unnumbered: key rotation used a hand-written column list and would have stranded the new webhook columns | Fixed. `encrypted_columns` (`rotate_field_keys`) reads the model registry; `KeyRotationCoverageTests` |
| (b) | n/a | Unnumbered: carrier-grade NAT (`100.64.0.0/10`) read as public | Fixed. Explicit list in `config/outbound.py` (RFC 6598, 6890, 2544, NAT64); `config/tests_outbound.py` |

Rows (a) and (b) were unnumbered in the original and are lettered here.

---

## 0.9.5f review: source review of 0.9.5e, closed in 0.9.5f

Fourth independent review, of 0.9.5e, closed in 0.9.5f (the second half of H-3
in 0.9.5g). The reviewer opened fourteen findings against the claims the
repository makes about itself, and named what was checked and sound (the ORM
tenancy pin, the cookie prefixes, webhook secrecy, the auditor deny list, SAML
signature wrapping and replay, OIDC PKCE, TOTP counter spending, the passkey
clone detector, the preview bounds, the X-Accel path). All fourteen were real
and fixed, each with a test that fails on 0.9.5e. Tests are in
`accounts/tests_review_095f.py` unless noted.

| ID | Sev | Finding | Status at 0.9.5ma |
|---|---|---|---|
| H-1 | High | A hijacked session could enrol its own authenticator | Fixed. `accounts/reauth.py` guards `MfaSetupView`, `MfaVerifyView`, `MfaDisableView`, `MfaBackupCodesView` and passkey enrolment and removal; a first enrolment with no usable password and no factor stays open. `ReauthOnEveryFactorChangeTests` |
| H-2 | High | A self-edited email decided who single sign-on linked to | Fixed. `email` removed from `ProfileUpdateSerializer`; `UserWriteSerializer.validate_email` refuses a duplicate within the workspace. `SelfServiceEmailTests` |
| H-3 | High | The published image booted with DEBUG on | Fixed. `backend/Dockerfile` pins `DJANGO_DEBUG=false` and `BEHIND_TLS=false`; validator refuses a Dockerfile without the first; both CI workflows boot a container and fail unless the banner says `DEBUG=off`, `/api/` is not the browsable API, and the health check returns 200 |
| M-1 | Med | An issued auditor could read the Jira backlog (action replaced viewset permissions) | Fixed. `JiraBoardViewSet.issues` declares no `permission_classes`; `accounts/tests_auditor_surface.py` walks `get_extra_actions()` on every viewset |
| M-2 | Med | Legacy Office (`.doc`, `.xls`, `.ppt`, `.rtf`) still accepted | Fixed. `_is_ole2` signature check, legacy extensions blocked, packaged OLE objects in OOXML refused, macro scan reads every zip entry (`documents/uploads.py`); `documents/tests.py` `test_legacy_office_is_refused_by_name_and_by_shape` |
| M-3 | Med | The cross-tenant username check was a no-op | Fixed. Queryset built inside `unscoped()` in `UserWriteSerializer.validate_username`; `CrossTenantUniquenessTests` |
| M-4 | Med | A reset left the access token alive | Fixed. `User.sessions_valid_from` stamped by `end_all_sessions`, enforced by `_refuse_if_superseded` (`accounts/cookie_auth.py`); signing out does not stamp. `AccessTokenEpochTests`. The admin hook this fix added, in `CustomUserAdmin.save_model`, never ran (the admin sets a password on its own page, which does not call it), so a password set in the Django admin ended no session until 0.9.5mb moved it to `user_change_password`; `AdminPasswordPageTests` in `accounts/tests_review_095mb.py` |
| M-5 | Med | Signing in was not CSRF-protected in cookie mode | Fixed. `csrf_required` (`accounts/cookie_auth.py`) on token, refresh and OIDC redeem; `/api/auth/config/` seeds the token. `LoginCsrfTests` |
| M-6 | Med | An SSO account could not remove a factor | Fixed. `reauthenticated` accepts a backup code; `test_an_sso_account_disables_with_a_backup_code` |
| M-7 | Med | A build could bake a developer's keys into the image | Fixed. `backend/.dockerignore` lists `.field-encryption-key`, `.package-signing-key`, `*.pem`, `*.key`; validator check enforces it |
| L-1 | Low | SAML bearer confirmation with no expiry | Fixed. `NotOnOrAfter` required in `accounts/saml.py`; `test_a_confirmation_with_no_expiry_confirms_nothing` |
| L-2 | Low | Published-keys route still distinguished slugs | Fixed, narrowed and not closed. `SigningKeysView` resolves the single-tenant case to that workspace and answers an unknown slug like an organisation with no key; `SigningKeyDirectoryTests` in `attestations/tests_release_095.py`. An organisation that has published a key still answers differently (see Deferred and accepted) |
| L-3 | Low | Boot banner contradicted the boot | Fixed. `backend/entrypoint.sh` reads `DJANGO_DEBUG` and `SEED_DEMO_DATA` with off defaults |
| L-4 | Low | nginx overwrote the scheme | Fixed. `map $http_x_forwarded_proto $forwarded_proto` in `frontend/nginx.conf`, `$scheme` as fallback |
| (a) | n/a | `.env` written mode 600 by the POSIX installer | Fixed. `chmod 600 .env` in `install.sh`; `install.ps1` states it sets no ACL |
| (b) | n/a | `ip_is_public` unwraps IPv4-mapped IPv6 addresses | Fixed. `config/outbound.py` |
| (c) | n/a | OIDC client outbound requests go through `config.outbound` | Fixed. `accounts/oidc.py` uses `outbound.assert_safe_url` and `outbound.opener` |

Rows (a) to (c) are the three items the review raised in passing. They were
unnumbered in the original and are lettered here. The follow-up to H-3
(the redirect found by publishing the fix, 0.9.5g) is part of the H-3 row, not
a separate finding.

---

## 0.9.5h review: source review of 0.9.5g, closed in 0.9.5h

Fifth independent review, of 0.9.5g, closed in 0.9.5h: fourteen findings (six
Medium, eight Low, no High). The reviewer also re-read all fourteen findings
of 0.9.5f as claims and confirmed each still held. Thirteen are fixed, each
with a test that fails on 0.9.5g; L-8 is deferred. The review names the shape
of the set: a rule applied in one place and not in the place beside it. Tests
are in `accounts/tests_review_095h.py` except M-2 (`attestations/tests_pbc.py`),
L-1 (`attestations/tests_review_fixes.py`), L-5 (`documents/tests.py`), L-6
(`vendors/tests_questionnaire.py`); L-3 is a shell script.

| ID | Sev | Finding | Status at 0.9.5ma |
|---|---|---|---|
| M-1 | Med | Login minted a refresh token before the second factor | Fixed. `MFATokenObtainPairSerializer` authenticates through the grandparent and mints in `_issue()` after the factor passes; `LoginMintsAfterTheFactorTests` |
| M-2 | Med | An issued auditor could walk the staff directory through the PBC `assignee` field | Fixed. `PbcRequestSerializer` empties the `assignee` queryset for an external auditor, so a real and an unknown id both answer 400; `test_a_real_pk_and_an_unknown_one_look_the_same` |
| M-3 | Med | An auditor role could hold capabilities, and they worked | Fixed. `User._cap` returns False for an external auditor; `RoleSerializer.validate` refuses to introduce the combination and does not strip stored flags; `AuditorRoleHoldsNoCapabilitiesTests` |
| M-4 | Med | Production checklist collapsed every throttle into one bucket | Fixed. INSTALL.md production section and `.env.example` explain `NUM_PROXIES`; settings warn at boot when `BEHIND_TLS` is on and `NUM_PROXIES` is unset; `ThrottleDepthTests` |
| M-5 | Med | `fec0::/10` and IP literals under a proxy treated as public | Fixed. `fec0::/10` listed in `config/outbound.py`; `assert_safe_url` checks a literal even when a proxy applies; `OutboundAddressTests` |
| M-6 | Med | The server believed the client about https | Fixed. `SECURE_PROXY_SSL_HEADER` set only when `BEHIND_TLS` is on (`config/settings.py`); nginx map unchanged; `ForwardedProtoTests` |
| L-1 | Low | A sealed package published every live grant to each grantee | Fixed. `PackageGrantViewSet.get_queryset` filters a non-assembler to their own row; `GrantListDisclosureTests` |
| L-2 | Low | `POST /api/auth/token/clear/` had no CSRF check | Fixed. `SessionClearView` calls `csrf_required`; `SignOutCsrfTests` |
| L-3 | Low | `scripts/backup.sh` wrote `secrets.tgz` at mode 644 | Fixed, and the first fix was itself redone in 0.9.5i L-2. `umask 077`, mode set inside the container, directory 700 |
| L-4 | Low | Moving the Jira base URL to another host carried the saved token across | Fixed. `JiraConfigSerializer.update` clears the token and disables the integration on a host change (`integrations/serializers.py`); no test in the tree covers it; a throwaway check confirmed it |
| L-5 | Low | Document writes took the owner short-circuit before the auditor check | Fixed. `DocumentAccessPermission` refuses an external auditor first (`documents/permissions.py`); `AuditorWriteTests` |
| L-6 | Low | A dead questionnaire link still returned names, sender, address and message | Fixed. `public_state` (`vendors/questionnaire.py`); `DeadLinkDisclosureTests`. Timestamps removed by 0.9.5i L-3 |
| L-7 | Low | `csv_safe` judged the raw first character | Fixed. The stripped value decides (`config/csvsafe.py`); `CsvFormulaTests` |
| L-8 | Low | A passkey cannot be used as proof when changing a factor | Deferred; see below |

---

## 0.9.5i review: source review of 0.9.5h, closed in 0.9.5i

Sixth independent review, of 0.9.5h, closed in 0.9.5i. Three Low findings, two
of them defects in fixes 0.9.5h shipped the same day; the reviewer re-read the
fixes rather than the code they replaced. Each has a test. Tests are in
`accounts/tests_review_095i.py`.

| ID | Sev | Finding | Status at 0.9.5ma |
|---|---|---|---|
| L-1 | Low | The assignee oracle was closed on write and open on the filter | Fixed. `person()` in `config/personfilters.py` filters by number for `assignee` (`attestations/pbc_views.py`), `owner` (`documents/views.py`) and `user` (`audit/views.py`); `FilterOracleTests`; `EveryAuditorReadableFilterTests` walks every collection an auditor can read and refuses a filter that validates a person |
| L-2 | Low | The file mode 0.9.5h set could not take | Fixed. `scripts/backup.sh` sets `umask 077`, the archive and `chmod 600` inside the container; the validator refuses a backup script that hides a `chmod` failure or does not set the mode in the container |
| L-3 | Low | The dead-link payload was wider than the changelog sentence | Fixed. `public_state` returns state, empty questions and empty answers for a link that is not open; `DeadQuestionnaireStateTests` |

---

## Deferred and accepted

Every finding that is not fixed, and every decision the reviews name as
leaving something as it is. Status is at 0.9.5ma.

### From the 0.2.0 review

**S-17, `GET /users/` readable by every signed-in user (accepted).** Owner
and assignee pickers need the list. Status today: still true for internal
roles, limited to the person's own workspace since 0.9.0. An external auditor
is refused the route (default `NotExternalAuditor`; `users` is on the denied
list in `accounts/tests_auditor_surface.py`), so the exposure is staff
usernames and emails to staff.

**S-18, the MFA challenge confirms the password first (accepted).** A
two-step login lets someone with a password learn that it is right without
the second factor. Status today: unchanged. The `login` (8/min) and `mfa`
(10/min) throttles bound it, a failed second factor is audited as
`login_failed` ("invalid second factor"), and since 0.9.5h M-1 no token is
stored until the factor passes.

**Not changed, deliberately (section 3 of the 0.2.0 review).** Status today,
each:

- JWTs stay in `localStorage`. No longer true: cookie transport is the
  default since 0.6.1 (`HttpOnly`, `SameSite=Lax`, CSRF on unsafe methods);
  `AUTH_TRANSPORT=header` restores `localStorage`. `SECURITY.md` states the
  size of the gain.
- No field encryption for TOTP secrets or the Jira token. No longer true:
  both are `EncryptedCharField` (AES-256-GCM, rotatable ring), as are the two
  webhook columns since 0.9.5b.
- No SSO or WebAuthn ("roadmap"). No longer true: OpenID Connect, SAML 2.0
  and passkeys are implemented.
- Control objective text is a paraphrase, because of the standards'
  copyright. Unchanged; the README says so.

**Residual risks and recommendations (section 5 of the 0.2.0 review).** An
external penetration test before hosting regulated data, TLS and HSTS only
once TLS is terminated, removing demo accounts, backups with a restore
rehearsal. These are operator actions, not code changes. Nothing in the
repository records an external penetration test.

### From the 0.9.0 review

**H-14, no account lockout.** The finding had two parts: the throttle key and
the absence of a lockout behind it. The key was fixed in 0.9.1; a lockout was
not added. Login (8/min), MFA (10/min), refresh (30/min) and anonymous
(30/min) limits are per client address and, with Redis, shared across
workers; a distributed guess is bounded only per address. Status: open by
omission, not tracked as a separate finding in the review.

**H-16, release by upload retained.** The finding said a new version
"silently releases" a quarantined document. The fix stopped quarantined bytes
being archived as a downloadable version; it kept the release, on the reasoning
that a new file is a new scan subject. `new_version` clears quarantine after
`scan_or_raise`, which scans only when `CLAMAV_ENABLED` is on. With scanning
off (the default), an editor of the folder who uploads a new version clears a
quarantine that an earlier scan set. Status: unchanged, and not recorded
elsewhere as a decision.

**The five contested findings.** One of three verifiers disagreed, and the
review left them unfixed on that evidence. Status today:

- SAML `Destination` and `Recipient` validated against an ACS URL taken from
  the request's `Host` header (Low). Both attributes are now required
  (0.9.5 S-6). The ACS still comes from the request unless `SAML_ACS_URL` is
  pinned, so `ALLOWED_HOSTS` is the backstop; with `DJANGO_ALLOWED_HOSTS=*`,
  off DEBUG and SSO on, boot refuses unless `SAML_ACS_URL` and
  `OIDC_REDIRECT_URI` are pinned. Residual: with a listed `ALLOWED_HOSTS`,
  pinning is optional.
- `verify.py` treated a stripped signature as a passing "unsigned" verdict
  (Medium). Fixed in 0.9.5: an unsigned bundle exits 3, and
  `--allow-unsigned` accepts it on purpose
  (`attestations/tests_release_095.py`, `UnsignedBundleTests`).
- Reminders and alerts were not scoped per workspace (High). Fixed for
  reminders in 0.9.4 (L-1, `compliance_inbox`). The fallback to the
  installation-wide `COMPLIANCE_TEAM_EMAIL` remains for a workspace with no
  address of its own, and is the whole answer for a single organisation.
- Editing a document's review date through PATCH never cleared
  `reminders_sent` (Medium). Fixed in 0.9.5: `DocumentViewSet.perform_update`
  clears it when `next_review_date` changes.
- An upgrade re-seeded the control library into the `default` workspace only
  (Medium). Fixed in 0.9.5: the container entrypoint runs `seed_frameworks
  --with-folders --all-workspaces`. Outside the container the operator has to
  run the same command.

**Auditor reads of the audit log and access reviews (product decision).** An
issued external auditor can read the audit trail (emails, last sign-ins,
capabilities, client addresses) and every access-review snapshot without a
live package grant, and folder grants to the Auditor role outlive the
engagement. The 0.9.0 review calls the first two deliberate, because they are
audit artefacts produced to be inspected; the 0.9.5f review argues it and the
0.9.5h and 0.9.5i reviews leave it unchanged. Status: unchanged
(`ALLOWED` in `accounts/tests_auditor_surface.py`; `CanViewAuditLog` admits
`is_auditor`). A client who wants an auditor confined to one engagement's trail
should issue the package and withhold the account.

### From the 0.9.5 review

**S-4, malware scanning not on by default (declined).** Fail-closed scanning
is strictly better, but on by default a first `docker compose up` would pull
a container and a virus-definition database, and every upload would answer
503 until `freshclam` finished. The class of file that motivated it is now
refused outright. Status: unchanged (compose sets `CLAMAV_ENABLED` from
`${CONFORMITI_SCANNING:-false}`); scanning is a `--profile scanning` opt-in
and fails closed when on. Files are typed and size-capped but not scanned by
default.

**S-9, `demo_accounts` stays on the unauthenticated health payload
(declined).** The field puts the "remove the demo accounts" warning on the
sign-in page, the one screen the person who can act on it is looking at, and
hiding it would remove the warning and leave the accounts. With the seed off
by default there is nothing to disclose unless the operator asked for the
demo. Status: unchanged (`config/health.py`).

**S-5, no boot-time check for `PUBLIC_URL` (declined).** An installation
upgrading from 0.9.5 has no `PUBLIC_URL`, and refusing to start would turn a
questionnaire problem into an outage. Status: unchanged; the send is refused
with a message naming `PUBLIC_URL` (`public_base`).

**S-6, `SAML_ACS_URL` and `OIDC_REDIRECT_URI` not mandatory (narrowed).**
Making them mandatory would break every working SSO installation on upgrade
to close a gap `ALLOWED_HOSTS` already closes. Status: unchanged; the boot
guard covers the `*` case only (see the contested SAML item above).

### From the 0.9.5f review

**L-2, published-keys route narrowed, not closed.** An organisation that has
published a key still answers differently from one that has not, which is
what publishing a key means. Closing it would mean authenticating the
endpoint, and an auditor could then not verify a bundle without an account on
the server it came from, which is the property the scheme exists for. Status:
unchanged (`SigningKeysView`).

**Auditor reads of access reviews and the audit trail.** See the 0.9.0 item
above. The 0.9.5f review records it again as a product decision left as a
decision, so the next reviewer finds it argued rather than missed.

### From the 0.9.5h review

**L-8, a passkey cannot be used as proof when changing a factor
(deferred).** `reauthenticated` accepts a password, an authenticator code or
a backup code. An account provisioned through single sign-on whose only factor
is a passkey, with backup codes spent, cannot add or remove a factor without
an administrator's MFA reset. A passkey proof is a two-step ceremony with
stored challenge state, origin and clone detection, the same machinery as
signing in; accepting an assertion in the reauth body without it would be a
new way around the check. Enrolling a first passkey issues backup codes, and
those satisfy the check. Status: unchanged (`accounts/reauth.py` has no
passkey path). The test `test_enrolling_a_first_passkey_issues_backup_codes`
(class `DeferredTests`) holds the assumption the deferral rests on; it
passes.

**SAML replay bound by `InResponseTo` and the one-time flow cookie.** The
0.9.5h review restates this residual with the published-keys one. Status:
unchanged; assertion ids are also accepted once from a shared table
(`_refuse_replay` in `accounts/saml.py`).

### From the 0.9.5i review

Confirmed and not reopened by that review, status today:

- The Django admin registers `Role` without a `clean()`, so an auditor role
  with capabilities can still be stored there. `User._cap` means storing it
  grants nothing. Unchanged (`admin.site.register(Role)` in
  `accounts/admin.py`); the test
  `test_a_role_saved_outside_the_api_still_grants_nothing` (class
  `RoleCapabilityCapTests`) holds it.
- `2002::/16` (6to4) and `2001:0::/32` (Teredo) still read as public in the
  outbound guard: the caller is an operator typing a Jira base URL. Unchanged
  (not in `config/outbound.py`).
- `/api/health/` creates the signing key on first call. Unchanged
  (`signing_state` calls `current_key_info(create=True)`); workers no longer
  reach it and the fingerprint is already published.
- L-8 of the fifth review remains deferred, for the reason above.

---

## Re-verifying

Backend, from `backend/` with the repository's virtualenv (see `TESTING.md`):

```
python manage.py test accounts.tests_review_095 accounts.tests_review_095f
python manage.py test accounts.tests_review_095h accounts.tests_review_095i
python manage.py test accounts.tests_review_open accounts.tests_auditor_surface
python manage.py test attestations.tests_review_fixes attestations.tests_review_open
python manage.py test config.tests_outbound accounts.tests_saml accounts.tests_tenancy
```

The test modules that lock each review:

| Review | Modules |
|---|---|
| 0.2.0 | `documents/tests.py` (`FolderIntegrityTests`, `DocumentLifecycleTests`), `accounts/tests.py` (`LoginTests`, `TokenLifecycleTests`), `audit/tests.py`, `notifications/tests.py`, `tools/validate.py` |
| 0.9.0 | `accounts/tests_review_open.py`, `attestations/tests_review_open.py`, `attestations/tests_review_fixes.py`, `accounts/tests_tenancy.py`, `accounts/tests_admin_login.py`, `accounts/tests_auditor_surface.py`, `attestations/tests_pbc.py`, `attestations/tests_signing.py`, `documents/tests_monitor.py`, `accounts/tests_demo.py` |
| 0.9.5 | `accounts/tests_review_095.py`, `config/tests_outbound.py`, `accounts/tests_saml.py`, `documents/tests.py`, `vendors/tests_questionnaire.py`, `attestations/tests_release_095.py`, `e2e/tests/settings.spec.js`, the compose job in `.github/workflows/ci.yml` |
| 0.9.5f | `accounts/tests_review_095f.py`, `accounts/tests_auditor_surface.py`, `documents/tests.py`, `accounts/tests_saml.py`, `attestations/tests_release_095.py`, `tools/validate.py`, both workflows |
| 0.9.5h | `accounts/tests_review_095h.py`, `attestations/tests_pbc.py`, `attestations/tests_review_fixes.py`, `documents/tests.py`, `vendors/tests_questionnaire.py` |
| 0.9.5i | `accounts/tests_review_095i.py`, `tools/validate.py` (backup script rule) |

Rows that no test in the tree locks, for a reader who wants to add one: 0.9.0
H-6 and H-14 (a rotating `X-Forwarded-For` against a throttle), H-8
(cross-workspace SSO), H-17 (export with a quarantined file), M-6 and M-8
(spreadsheet ceilings), M-9 (a formula in a vendor heading), L-6 (health error
text); 0.9.5h L-4 (a Jira host change). The whole gate is `./install.sh --test`
or `install.ps1 -Test`; the browser suite and the compose job run in CI.
