# Conformiti 0.9.0 — adversarial review

**Date:** 2026-09-07 · **Scope:** the whole repository at v0.9.0 (`0ded621`).

**Method.** Sixteen independent reviewers attacked the product across separate
dimensions — cross-workspace reads and writes, the tenancy mechanism itself,
authentication, single sign-on, authorisation, the unauthenticated surface,
file ingest and file serving, cryptography, injection and SSRF, the browser,
concurrency, background jobs and migrations, denial of service, and
deployment. Every candidate was then attacked by three more with different
lenses: can it actually be carried out, does the cited code really say this,
and is it already mitigated somewhere. A finding is listed only if at least
two of the three could not kill it.

**Result.** 69 candidates → **50 confirmed**, 5 contested, 14 killed in
verification.

| Severity | | | Status | |
|---|---|---|---|---|
| Critical | 3 | | Fixed in 0.9.1 | 14 |
| High | 25 | | Fixed in 0.9.2 | 21 |
| Medium | 12 | | Fixed in 0.9.3 | 4 |
| Low | 10 | | Partly fixed / open | 11 |

Several findings are the same defect reached from two dimensions; they are
listed separately because they were found and verified separately. What each
fix does is in [CHANGELOG.md](CHANGELOG.md).

## Critical

| # | Finding | Where | Status |
|---|---|---|---|
| 1 | The shipped Docker stack seeds a superuser with the published password DemoPass123! by default, and /api/health/ tells… | `backend/entrypoint.sh:41-49` | fixed 0.9.2 |
| 2 | The login page prints working superuser credentials to anonymous visitors, and the shipped production stack seeds thos… | `frontend/src/pages/Login.jsx:308-313` | fixed 0.9.1 |
| 3 | Sealed-manifest workpaper fields stay writable after sealing: any PATCH that also touches a conclusion or the manageme… | `backend/attestations/views.py:409-441` | fixed 0.9.1 |

## High

| # | Finding | Where | Status |
|---|---|---|---|
| 1 | PATCH /api/package-evidence/{id}/ re-points `document` with no `assert_pinnable`, turning a draft package into a read … | `backend/attestations/views.py:618-623` | fixed 0.9.1 |
| 2 | PATCH /api/package-samples/{id}/ with only `package_control` runs no authorization check at all, letting an issued aud… | `backend/attestations/views.py:557-580` | fixed 0.9.1 |
| 3 | Audit rows are stamped from `user.workspace_id`, so a superuser working under X-Workspace files another tenant's docum… | `backend/audit/models.py:8-16` | fixed 0.9.2 |
| 4 | A superuser's writes inside a switched workspace are audited into their own workspace, so the tenant's audit trail — a… | `backend/audit/models.py:12` | fixed 0.9.2 |
| 5 | One installation-wide Ed25519 signing key plus a manifest with no tenant identity: any workspace can seal a bundle tha… | `backend/attestations/models.py:383` | fixed 0.9.3 |
| 6 | Every per-IP throttle (login, MFA, refresh, questionnaire, anon) is keyed on an attacker-controlled X-Forwarded-For he… | `backend/config/settings.py:369-400` | fixed 0.9.1 |
| 7 | The Django admin login bypasses MFA, the login throttle and the 0.9.0 archived-workspace refusal — and the resulting s… | `backend/config/urls.py:85` | fixed 0.9.3 |
| 8 | SSO account resolution runs with no active workspace: SSO_WORKSPACE gates only provisioning, so one IdP signs people i… | `backend/accounts/oidc.py:433` | fixed 0.9.2 |
| 9 | A revoked, expired or withdrawn package grant does not stop the external auditor reading evidence bytes: the PBC assig… | `backend/attestations/access.py:118-121` | fixed 0.9.2 |
| 10 | The issued auditor can write the organisation-only `management_response` and silently mutate sealed sampling metadata,… | `backend/attestations/views.py:409-441` | fixed 0.9.1 |
| 11 | `Folder.owner` is writable by anyone with EDIT, and owner means MANAGE — a self-service edit→manage escalation that un… | `backend/documents/views.py:60-80` | fixed 0.9.1 |
| 12 | `PATCH /api/documents/{id}/` replaces the stored evidence bytes with no folder-edit check, no AV scan, no archived ver… | `backend/documents/views.py:199-208` | fixed 0.9.1 |
| 13 | The shipped "Auditor" role — described as "sees only granted folders" — is a full-program reader of the whole workspac… | `backend/accounts/permissions.py:9-14` | partly 0.9.2 |
| 14 | Every rate limit in the product is keyed on an attacker-supplied X-Forwarded-For header, and there is no account locko… | `backend/config/urls.py:29 and :62` | fixed 0.9.1 |
| 15 | PATCH /api/documents/{id}/ swaps the stored evidence file with no malware scan, no version snapshot, and leaves the st… | `backend/documents/views.py:199-208` | fixed 0.9.1 |
| 16 | Uploading a new version silently releases a quarantined document, and the quarantined bytes stay downloadable through … | `backend/documents/views.py:248-262 and 290-299` | fixed 0.9.1 |
| 17 | The audit-package ZIP export streams quarantined documents' bytes to the external auditor — the one byte route with no… | `backend/attestations/bundle.py:432-448` | fixed 0.9.1 |
| 18 | PATCH /api/package-evidence/{id}/ re-points a pinned row at any document in the workspace, bypassing folder permission… | `backend/attestations/views.py:618-623` | fixed 0.9.1 |
| 19 | A sealed, signed package can gain evidence rows after sealing, and /verify/ still reports ok:true | `backend/attestations/views.py:618-623` | fixed 0.9.2 |
| 20 | An external auditor keeps reading PBC attachment bytes forever after the grant is revoked or expires, by self-assignin… | `backend/attestations/access.py:112-121` | fixed 0.9.2 |
| 21 | Meeting-minute files and form templates are downloadable by every authenticated account, including an external auditor… | `backend/governance/views.py:196-201` | fixed 0.9.2 |
| 22 | The Ed25519 signature covers only manifest.json — the auditor's conclusions in controls.csv/samples.csv are unsigned, … | `backend/attestations/bundle.py:490-505` | fixed 0.9.3 |
| 23 | One installation-wide signing key signs every workspace's packages, and the signed manifest names no organisation — on… | `backend/attestations/signing.py:88-116` | fixed 0.9.3 |
| 24 | The sidebar's workspace label shows the superuser's home workspace, not the workspace they are actually reading and wr… | `backend/accounts/serializers.py:48-50` | fixed 0.9.2 |
| 25 | A write refused with 403 has already been committed: the issued auditor can forge the organisation's management respon… | `backend/attestations/views.py:418-436` | fixed 0.9.1 |

## Medium

| # | Finding | Where | Status |
|---|---|---|---|
| 1 | Cross-workspace username oracle: DRF's uniqueness check on User.username is workspace-pinned but the DB constraint is … | `backend/accounts/models.py:111` | fixed 0.9.2 |
| 2 | Any tenant administrator reads every other organisation's webhook delivery log via GET /api/notifications/channels/ | `backend/notifications/views.py:28-32` | fixed 0.9.2 |
| 3 | Changing a password (or resetting a user's MFA) revokes nothing: a stolen refresh token keeps working and renews itsel… | `backend/accounts/serializers.py:128-132` | fixed 0.9.2 |
| 4 | A TOTP code is accepted repeatedly for up to 90 seconds — no used-code or counter store, so an intercepted code is rep… | `backend/accounts/models.py:303-315` | open |
| 5 | SSO auto-provisioning probes username uniqueness workspace-scoped against a globally-unique column, so provisioning di… | `backend/accounts/oidc.py:463` | fixed 0.9.2 |
| 6 | XLSX importer's zip-bomb guard trusts the archive's declared sizes, then decompresses unbounded — 300 KB of upload all… | `backend/governance/risk_import.py:142-168` | fixed 0.9.2 |
| 7 | In-app signature verification trusts the public key stored in the same database row, so a database-write attacker can … | `backend/attestations/signing.py:201-207` | open |
| 8 | Unbounded XLSX column index in the stdlib importer turns a ~300-byte upload into a multi-gigabyte allocation (worker O… | `backend/governance/risk_import.py:115-121` | fixed 0.9.2 |
| 9 | Vendor-supplied column headings are written into the responsibility-matrix CSV export without csv_safe, reopening form… | `backend/vendors/views.py:239` | fixed 0.9.2 |
| 10 | The switched-workspace choice survives a change of user in the same browser: login() never clears it | `frontend/src/api/client.js:154-165` | fixed 0.9.2 |
| 11 | Sealing is a check-then-act with no row lock: evidence pinned concurrently lands inside a sealed package but outside i… | `backend/attestations/views.py:204-205 and 227` | open |
| 12 | Quarantine and release events written by the `scan_evidence` sweep land with workspace = NULL and are invisible to eve… | `backend/documents/monitor.py:75-84` | fixed 0.9.2 |

## Low

| # | Finding | Where | Status |
|---|---|---|---|
| 1 | Every workspace's document, vendor and auditor-request detail is emailed to one installation-wide COMPLIANCE_TEAM_EMAI… | `backend/notifications/tasks.py:25, :100, :140` | open |
| 2 | TenantQuerySet._pin() permanently skips the workspace filter on any queryset that was sliced while no workspace was ac… | `backend/accounts/tenancy.py:263-270` | open |
| 3 | Enrolling a passkey needs no password re-authentication, while removing one does — a hijacked session can plant an att… | `backend/accounts/webauthn_views.py:39-61 and :86-97` | open |
| 4 | Default SSO_MFA_ASSERTIONS accepts amr values that are not second factors, letting a single-factor IdP login satisfy S… | `backend/config/settings.py:649` | open |
| 5 | `GET /api/folders/{id}/permissions/` discloses a folder's full access map to anyone with VIEW, contradicting the manag… | `backend/documents/views.py:120-124` | fixed 0.9.2 |
| 6 | The unauthenticated health endpoint discloses the filesystem path of the Ed25519 package-signing private key when it i… | `backend/config/health.py:54-59 and :81` | fixed 0.9.2 |
| 7 | Switching to the workspace whose slug is literally "default" silently lands the superuser in their own workspace instead | `frontend/src/pages/Account.jsx:1016-1019` | fixed 0.9.2 |
| 8 | Every page of a self-hosted compliance product, including the anonymous login screen and the public vendor questionnai… | `frontend/index.html:10-15` | open |
| 9 | MFA backup codes are single-use only in Python: an unlocked read-modify-write lets one code authenticate two concurren… | `backend/accounts/models.py:195-209` | open |
| 10 | "One live questionnaire link per vendor" is enforced by an UPDATE with nothing to lock, so two concurrent sends leave … | `backend/vendors/questionnaire.py:123-135` | open |


## Contested

One verifier of three disagreed. Worth a second look rather than a fix on this evidence.

- **[low]** SAML Destination/Recipient are validated against an ACS URL derived from the request's Host header, not from configura…
- **[medium]** verify.py silently downgrades a stripped signature to a passing "unsigned" verdict — removing manifest.sig and signing…
- **[high]** 0.9.0 scoped every query per workspace but not a single notification recipient: all workspaces' reminders, alerts and …
- **[medium]** Editing a document's review clock through PATCH never clears `reminders_sent`, so a document that has gone overdue onc…
- **[medium]** Upgrading re-seeds the shipped control library into the `default` workspace only; every other tenant is silently froze…


## What is still open

The three highest-severity items are closed in 0.9.3: the signature now covers
the whole bundle by way of a second signature over `SHA256SUMS`, each
workspace signs with its own derived key, and the Django admin demands the
second factor while its session no longer authenticates the API.

What remains: the shipped Auditor role still reads more of a workspace than
"granted folders" implies, though minutes and blank templates are now closed
to it. TOTP codes are replayable inside their 90-second window. Sealing is a
check-then-act with no row lock. In-app signature verification trusts the
public key stored beside the signature, so it reports "signed" for a row an
attacker with database write access re-signed — the offline verifier and the
published fingerprint are the real check, and they are unaffected. Reminder
email goes to one installation-wide address. The remaining low findings are
listed above.
