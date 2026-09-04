# Conformiti 0.2.0 — full review and release-readiness report

**Date:** 2026-09-03 · **Scope:** the complete repository at v0.1.1 (backend,
frontend, installers, containers, documentation) · **Method:** line-by-line
code review of every app and page, dynamic verification against a running
system, and a test suite written to lock each finding · **Verdict:** **ready
to ship as 0.2.0** under the residual risks listed at the end.

This document is the audit record. `SECURITY.md` carries the operator-facing
summary; `CHANGELOG.md` the user-facing one.

---

## 1. What was reviewed

| Area | Files | How |
|---|---|---|
| Settings, URL routing, auth, throttling | `backend/config/*`, `accounts/*` | read in full; booted with placeholder / short / file-based keys; login, refresh, logout, MFA exercised over HTTP |
| RBAC and the folder tree | `documents/*`, `compliance/*` | read in full; every permission class traced to its view; adversarial requests (cycles, re-parenting, owner delete, hidden folders) issued as each of the five personas |
| Governance (risks, access reviews, meetings, groups) | `governance/*` | read in full; import/export fixtures including formula-injection strings and malformed files |
| Notifications, email, audit, analytics, calendar, Jira | remaining apps | read in full; review scan run in dry/real mode; SSRF guard exercised with private hosts |
| Frontend | all 13 pages, client, theme, shell | read in full; every write control compared against the API's permission rules; keyboard traversal checked |
| Install & deploy | `install.sh`, `install.ps1`, `docker-compose.yml`, both Dockerfiles, `nginx.conf`, `entrypoint.sh` | read in full; installer run end-to-end on Windows; compose stack built and booted in Docker (WSL) and polled at `/api/health/` |
| Docs | every `*.md` | checked against the behaviour actually observed |

## 2. Findings

Severity: **High** = exploitable for data loss, escalation or denial of service;
**Medium** = a control materially weaker than documented; **Low** = hardening
or defence in depth. Status is as of this release.

### 2.1 Security

| ID | Sev | Finding | Status |
|---|---|---|---|
| S-01 | High | **Folder parent cycle → infinite loop in every access check.** `PATCH /folders/{id}/ {parent}` accepted any folder, including a descendant; `Folder.ancestors()` had no guard, so `effective_access()`, `path` and the tree endpoint spun forever. Any user with *edit* on one folder could hang the API. | Fixed: serializer rejects self/descendant parents; `ancestors()` bounded and raises on corruption. Tests `FolderIntegrityTests`. |
| S-02 | High | **Subtree exposure by re-parenting.** Moving a folder required only *edit* on the folder; the destination was unchecked, so a subtree could be planted under a folder the mover couldn't see — every principal granted on the destination's ancestors then inherited it. | Fixed: manage on folder + edit on destination; top-level moves need the folders capability; seeded folders immovable. Tested. |
| S-03 | High | **Refresh tokens non-rotating, non-revocable.** Documented in 0.1.x as a residual risk; a stolen refresh token was valid for 7 days and "sign out" only cleared `localStorage`. | Fixed: rotation + blacklist, `POST /auth/logout/`, weekly pruning task, client stores rotated tokens. Tests `TokenLifecycleTests`. |
| S-04 | Med | **Per-process throttle counters.** `LocMemCache` default → each gunicorn worker counted separately; no sharing across containers. | Fixed: `CACHE_URL` → Redis; compose sets it. Throttle behaviour tested (default rate). |
| S-05 | Med | **Owner could delete own evidence with view-only folder access.** | Fixed: delete requires manage. Tested. |
| S-06 | Med | **No application-level upload size/type limit** (only nginx's 32 MB; dev server/admin/direct gunicorn unbounded; `.html`/`.svg`/`.exe` accepted). | Fixed: `MAX_UPLOAD_MB` + blocked extensions + empty-file check on every upload path; `/media/` sandbox CSP. Tested. |
| S-07 | Med | **Auth events absent from the audit trail; mutation entries recorded the path only.** | Fixed: login / login_failed (with reason) / logout with IP; mutation entries carry field names and created ids; sensitive keys excluded. Tests `AuditMiddlewareTests`, `LoginTests`. |
| S-08 | Med | **Docker path ran DEBUG on with the published placeholder key**; the 0.1.1 key guard only fires with DEBUG off, so the documented quickstart never triggered it. | Fixed: compose defaults DEBUG off, key auto-generated into a volume; installers write a production-style `.env`; loud banner otherwise. Boot guard tested in a subprocess. |
| S-09 | Med | **API/admin published on all interfaces** next to nginx; browsable API on. | Fixed: `127.0.0.1:8000`, admin proxied, JSON-only renderer off DEBUG. |
| S-10 | Low | Built-in role flags editable via API. | Fixed: locked for `is_system` roles. Tested. |
| S-11 | Low | Non-superuser admin could reset a superuser's MFA. | Fixed. Tested. |
| S-12 | Low | Folder names unvalidated (separators, `..`, reserved chars). | Fixed: validator + migration. Tested. |
| S-13 | Low | Notification dismiss accepted arbitrary keys (unbounded receipts). | Fixed. Tested. |
| S-14 | Low | CSP shipped commented out because of an inline script. | Fixed: external bootstrap, CSP on. |
| S-15 | Low | Password minimum 8 (< PCI DSS v4.0.1 §8.3.6). | Fixed: 12 by default. Tested. |
| S-16 | Low | Container ran as root. | Fixed: unprivileged user. |
| S-17 | Info | `GET /users/` readable by every signed-in user (owner pickers need it). | Accepted; documented as residual. |
| S-18 | Info | MFA challenge confirms the password before asking for the code (standard two-step; lets an attacker learn a password is right without the second factor). | Accepted; the login throttle bounds it; failed second factors are audited. |

### 2.2 Correctness and operations

| ID | Sev | Finding | Status |
|---|---|---|---|
| C-01 | High | **Installers and the container ran `makemigrations` at install time**, generating schema on the target machine that was never reviewed; the shipped migration set was in fact complete, so the step was pure risk. | Fixed: removed everywhere; CI runs `makemigrations --check`; validator forbids it in install paths. |
| C-02 | Med | **`install.ps1` ignored native exit codes and never checked versions** — a failed `pip install` still printed "Setup complete". | Fixed: every native command exit-code checked; Python 3.11+/Node 20.19+ verified; same in `install.sh`. |
| C-03 | Med | **Celery beat "24 h after start" schedule** — a worker restart shifted or skipped the daily scan; the worker also started before the API had migrated. | Fixed: crontab at `REVIEW_SCAN_HOUR`; worker depends on backend *healthy*. |
| C-04 | Med | Django 5.0/5.1 (end of life), React Router 6.30 with two open advisories, psycopg2. | Fixed: Django 5.2 LTS, RR 7, psycopg 3, Vite 7; `npm audit` 0. |
| C-05 | Low | `date.today()` in analytics/reminders/cadence ignored `TIME_ZONE`. | Fixed: `timezone.localdate()`. |
| C-06 | Low | Duplicate evidence link / group membership → 500. | Fixed (serializer uniqueness) — tested. |
| C-07 | Low | `LICENSE` missing from the tree although README/badges claim MIT. | Fixed: MIT text restored from the published repository. |
| C-08 | Low | No health endpoint for orchestration; installers could not wait for readiness. | Fixed: `/api/health/`; compose healthchecks; installers poll it. |
| C-09 | Low | No automated tests, no CI. | Fixed: 80 tests + CI matrix (see §4). |

### 2.3 Interface

| ID | Sev | Finding | Status |
|---|---|---|---|
| U-01 | Med | Write controls rendered for roles the API rejects: auditors saw "Start new review", decision selects and "Complete review"; evidence "Unlink" showed for every link regardless of folder rights; bulk-attach skips were silent. | Fixed in the redesign: gates on `manage_users`; per-link `can_unlink` from the API; skipped reasons surfaced. |
| U-02 | Med | Folder tree, account tabs, framework chips, risk rows not keyboard-operable. | Fixed: tree with `role=tree`/arrow keys; tabs/chips are buttons; rows keyboard-activatable. |
| U-03 | Low | Hard-coded light-only backgrounds broke the dark themes; four themes had inconsistent token coverage. | Fixed: token-driven design system; four theme packs verified light and dark. |
| U-04 | Low | Login screen always advertised the demo password. | Fixed: shown only while `/api/health/` reports demo accounts. |
| U-05 | Low | Sign-out did not revoke anything server-side. | Fixed (see S-03). |

## 3. What was *not* changed, deliberately

- **JWTs stay in `localStorage`.** Moving to cookie auth is an architectural
  change with CSRF implications across the SPA; rotation + revocation + CSP
  were judged the right step for this release.
- **No field encryption for TOTP secrets / Jira token.** Requires key
  management the project does not yet have; documented as residual.
- **No SSO/WebAuthn.** Roadmap.
- **Control objective text remains paraphrase.** Copyright of the standards.

## 4. Verification record

| Gate | Result |
|---|---|
| `python tools/validate.py` (15 checks) | PASS, 0 errors |
| `manage.py check` / `makemigrations --check` | clean |
| Backend test suite (SQLite, Python 3.13) | **80 tests, 0 failures** (~95 s) |
| Frontend production build (Vite 7) | clean, 0 errors |
| `npm audit` | 0 vulnerabilities |
| Docker stack (WSL Docker 29): build, boot, `/api/health/` | recorded in the release notes for this tag |
| Windows installer `install.ps1 -SetupOnly` | recorded in the release notes for this tag |
| Interface walkthrough (every route, two roles, light + dark) | recorded in the release notes for this tag |

The last three rows are filled in by the release process (see the GitHub
release for v0.2.0) rather than claimed here in advance.

## 5. Residual risks and recommendations

1. Commission an external penetration test before hosting regulated data.
2. Enable `BEHIND_TLS=true` + HSTS only once TLS is actually terminated in
   front of nginx; set the three origin variables to the real hostname.
3. Run `remove_demo_data` and verify `/api/health/` shows
   `"demo_accounts": false` before inviting real users.
4. Back up PostgreSQL and the `media` volume; rehearse a restore.
5. Roadmap for 0.3: cookie-based auth, SSO (OIDC/SAML), WebAuthn, evidence
   virus scanning, per-control readiness scoring, e2e browser tests in CI.
