# Changelog

All notable changes to Conformiti are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

---

## [0.3.0] — 2026-09-04

The release that makes Conformiti useful **at audit time**, not just before
one. Evidence can now be sealed and handed to an external auditor as a
verifiable package; readiness is a graded score rather than a ticked box; the
secrets that must be readable are encrypted at rest; uploaded evidence is read
through an authorised endpoint and can be scanned for malware; and the SPA can
keep its credentials where script cannot reach them.

### Added

- **Audit packages — sealed evidence issued to a named external auditor.**
  Assemble the controls in scope, pin their evidence, write the management
  assertion, and **seal**: every row is snapshotted (control text, status,
  owner, document name, version, size, SHA-256) into a canonical manifest with
  a digest. **Issue** it to one named auditor for a fixed period; they see that
  package and nothing else, record a **design** and an **operating** conclusion
  per control that nobody at the assessed organisation can edit, and leave with
  a self-verifying ZIP — manifest, `SHA256SUMS`, workpaper and evidence CSVs, an
  audit-trail extract, the files, and a stdlib-only `verify.py`. Exceptions
  promote into the risk register, which makes `Risk.Type.AUDIT_FINDING`
  reachable from the product for the first time. Access expires or is withdrawn
  in one click; what was disclosed, to whom, and every file they opened is
  permanent.
  The bundle proves **integrity, not origin** — it carries no signature, and the
  README, `SECURITY.md` and the UI all say so.
- **Per-control readiness scoring.** Six signals — implementation, owner,
  evidence, evidence freshness, test recency, minus a penalty for open risks —
  normalised to 0–100 and banded. Expanding a control explains the score
  component by component and names the single change worth the most points.
  Controls gain `last_tested_on` and a retest interval, recorded with who and
  when. `GET /api/controls/{id}/readiness/` returns the breakdown; the CSV
  export carries the score, the band and the test date.
- **Field encryption for secrets at rest.** The TOTP secret and the Jira API
  token — the two values the server must be able to read back — are AES-256-GCM
  encrypted under a rotatable key ring, with associated data binding each
  ciphertext to its own row and column. `manage.py rotate_field_keys` moves rows
  onto a new key and reports rows per key.
- **Optional malware scanning for uploaded evidence** (`docker compose
  --profile scanning up -d` plus `CONFORMITI_SCANNING=true`). Every path that
  stores a file goes through it. Scanning runs *after* the folder permission
  check, and when enabled it fails **closed**.
- **HttpOnly cookie authentication** as an opt-in transport
  (`AUTH_TRANSPORT=cookie`): the same tokens, delivered where script cannot read
  them, with CSRF protection on unsafe methods and a sign-out that works even
  after the access cookie has expired.
- **An end-to-end browser suite** (`e2e/`) that drives the *built* SPA through
  every screen and fails on any console error, plus **a 17th validator check**.
  CI runs the suite once per authentication transport.
- The demo dataset now seeds an in-flight access review and a sealed evidence
  package, so neither screen is empty on a fresh install.

### Security

- **Uploaded evidence is no longer readable without authorisation.** nginx
  served the whole media volume as a plain alias, and upload paths are derived
  predictably from the folder tree — so anyone who could reach the site and
  guess a path could fetch any document regardless of folder permissions, with
  nothing recorded. Reads now go through `GET /api/documents/<id>/download/`,
  which resolves folder access first and writes an audit row; both media
  locations are `internal`, and no serializer publishes a storage path.
- **The auditor bypass is confined to one module.** `attestations/access.py` is
  the only place folder permissions are bypassed, behind six gates — assembling
  is capability-gated, pinning re-checks the packager's own visibility so
  packaging cannot launder access, the recipient must hold the Auditor role,
  only sealed packages are visible to a grantee, grants are per user and
  time-boxed and re-evaluated every request, and every byte that leaves is
  recorded first.
- `AlertExceedsMax yes` in the shipped `clamd.conf`: ClamAV's default silently
  *skips* content that trips a size or recursion limit and answers OK, which
  would store a file carrying the claim that it was scanned.

### Changed

- React 19, Vite 8, framer-motion 13 and lucide-react 1, verified by the new
  suite against the production bundle. Backend floors raised to the tested
  versions. **Django stays on the 5.2 LTS line and Tailwind on 3** — both
  deliberate, both recorded in `.github/dependabot.yml` with the reason.
- The API image runs threaded gunicorn workers: a malware scan holds a worker,
  and three sync workers against a slow scanner would block `/api/health/` too.
- `SQLITE_PATH` and `MEDIA_INTERNAL` settings; `ATTESTATION_*`, `CLAMAV_*`,
  `READINESS_*`, `AUTH_*` and field-encryption keys, all documented in
  `.env.example`.

### Fixed

- `bootstrap_demo` never created an access review, so **User audit was empty on
  a fresh install** even though the README screenshot showed a populated one.
- The SPA rendered the shell and fired every page's queries before the session
  was confirmed — invisible with header auth, three console errors with cookie
  auth.

### Upgrading from 0.2.x

1. Pull and `docker compose up -d --build`, or re-run the installer. Four
   migrations apply automatically; the two that encrypt existing secrets are
   reversible.
2. **Back up the `secrets` volume with your database.** It now holds the
   field-encryption key as well as the signing key. Losing it degrades safely —
   MFA is still demanded, backup codes still work, an administrator can reset a
   user's enrollment — but enrolled authenticators become unreadable.
3. Nothing changes for existing sessions: the authentication transport still
   defaults to `header`.
4. Saved `/media/...` links stop working, by design. Use the application.

### Verification for this tag

| Gate | Result |
|---|---|
| `tools/validate.py` (17 checks) | PASS — 0 errors, 0 warnings |
| Backend suite | 215 tests, 0 failures |
| End-to-end (both transports) | 67 + 66 tests, 0 console errors |
| Frontend build + `npm audit` | clean, 0 vulnerabilities |

**Conformiti is still unaudited beta software.** No third-party penetration
test has been performed.

---

## [0.2.0] — 2026-09-03

The first release built to be *shipped* rather than evaluated: a full security
and correctness review ([REVIEW.md](REVIEW.md)), an automated test suite and
CI, a one-command install that is production-safe by default, current
dependencies, and a redesigned interface with four theme packs.

### Security

- **Refresh tokens now rotate and are revoked on sign-out.** Every refresh
  issues a new refresh token and blacklists the old one; `POST /api/auth/logout/`
  revokes the current one server-side. A stolen refresh token is single-use
  and dies with the session (previously valid for its full 7-day life).
- **Authentication events are in the audit trail.** Sign-in, failed sign-in
  (with the reason: bad password, throttled, second factor missing/invalid) and
  sign-out are recorded with the client IP. Passwords and codes never reach the
  log; the login/notification endpoints are excluded from body capture.
- **Audit entries name what changed.** Mutating calls record the request's
  top-level field names (`fields=status,owner`), never values, plus the new
  record's id on create — enough for an auditor to reconstruct *what* was
  touched without the trail leaking document text or secrets.
- **Rate limits are shared across workers.** Throttle counters live in Redis
  when `CACHE_URL` is set (the compose stack sets it). Previously each gunicorn
  worker kept its own counter, so the effective login limit was N× the
  configured rate.
- **Uploads are bounded and typed in the application, not only at nginx.**
  `MAX_UPLOAD_MB` (default 32) is enforced on evidence, versions, templates and
  minutes; empty files and active-content extensions (`.html`, `.svg`, `.exe`,
  `.js`, `.ps1`, …) are refused. `/media/` responses carry a sandboxing CSP.
- **Content-Security-Policy is on by default** in the shipped nginx config
  (`script-src 'self'`; the theme bootstrap moved out of inline script to make
  that possible).
- **Password minimum raised to 12 characters** (PCI DSS v4.0.1 requirement
  8.3.6). Tunable with `PASSWORD_MIN_LENGTH`.
- **Deleting evidence is a manage-level act.** A document's owner may still edit
  it, but deletion now requires *manage* on the folder — a control owner can no
  longer make their own audit trail disappear.
- **Folder tree integrity.** Re-parenting a folder requires *manage* on the
  folder and *edit* on the destination (moving a subtree exposes it to everyone
  granted on the destination's ancestors); a folder can no longer be moved under
  itself; generated framework/category/control folders cannot be deleted,
  renamed or moved through the API; folder names are validated as single path
  segments (no separators, traversal or Windows-reserved characters).
- **Built-in role capability flags are locked** through the API; create a
  custom role instead of rewriting *Viewer*.
- **A non-superuser administrator can no longer reset a superuser's MFA.**
- **Notification dismissals are validated** against the caller's live feed, so
  a client can't grow the receipt table with made-up keys.
- **A development `.env` can no longer put the Docker stack into DEBUG.**
  Compose reads `./.env` both for `${...}` substitution and into the
  containers, and that file is what the *local* installer writes (DEBUG on, a
  dev signing key) — so running `./install.sh` and then `docker compose up`
  produced a DEBUG container signing tokens with the development key. The
  stack now reads `CONFORMITI_DEBUG` / `CONFORMITI_SECRET_KEY`, which a
  development `.env` never contains, and the validator fails the build if the
  old interpolation returns.
- **Docker stack hardened:** the API runs as an unprivileged user; the API/admin
  port is bound to the loopback interface and the admin is proxied through
  nginx; `DJANGO_DEBUG` defaults to *off*; a strong secret key is generated and
  persisted in a volume on first boot (`DJANGO_SECRET_KEY_FILE`); a single
  `BEHIND_TLS` switch controls HTTPS redirect and secure cookies; the browsable
  API is disabled in production.

### Fixed

- **A folder parent cycle hung the whole API.** `Folder.ancestors()` looped
  forever on a cyclic parent chain, which every access check calls. Cycles are
  now rejected at validation and the walk is bounded.
- **Installers and the container ran `makemigrations` at install time**,
  generating unreviewed schema on the target machine. Migrations ship with the
  release and CI fails if they are incomplete.
- **`install.ps1` reported "Setup complete" after failed steps** and did not
  check the Python/Node versions; both installers now stop on the first failing
  command and verify Python 3.11+ / Node 20.19+.
- **The Docker path started in DEBUG with the published placeholder key.**
  `install.sh --docker` / `install.ps1 -Docker` now write a production-style
  `.env` (unique key, DEBUG off) and wait for the API to report healthy.
- **Review reminders ran "24 hours after the worker started."** The daily scan
  is now a fixed-hour cron schedule (`REVIEW_SCAN_HOUR`, default 06:00 local),
  and the worker waits for the API container to be *healthy* so migrations
  exist before beat's first tick.
- Date arithmetic in analytics, reminders and cadence maths now uses the
  configured `TIME_ZONE` (`timezone.localdate()`), not the server's clock.
- **The audit-log filter dropdowns listed every action once per entry.**
  `facets` called `.distinct()` on a queryset still carrying the model's
  `Meta.ordering`, so `-timestamp` joined the SELECT behind DISTINCT and
  defeated it.
- A duplicate evidence link or duplicate group membership returns 400, not 500.
- Access reviews can be filtered by status (`?status=open`).
- Meetings, User audit, Controls and Jira read only the first page of endpoints
  paginated at 50, silently truncating long-running series, minutes, reviews,
  frameworks and boards.

### Added

- **Automated test suite — 80 tests** across every app (auth, MFA, token
  lifecycle, folder RBAC and tree integrity, evidence mapping, access reviews,
  risk import/export, calendar, analytics, audit middleware, review scan, demo
  retirement, secret-key boot guard, SSRF guard) — `python manage.py test`.
- **CI** (GitHub Actions): validator, backend tests on Python 3.11/3.12/3.13
  and on PostgreSQL 16, migration completeness, frontend build + `npm audit`,
  Docker image builds and a boot check against `/api/health/`. Dependabot for
  pip, npm, Docker and Actions.
- **`GET /api/health/`** — unauthenticated, unthrottled liveness/readiness
  endpoint reporting version, database state and whether the demo accounts still
  exist. Used by the container healthchecks, the installers and the login screen.
- **`manage.py remove_demo_data`** retires the demo dataset (deactivates or
  deletes the five demo users, removes the sample documents/risks/minutes/
  events/audit rows, keeps the control libraries) and refuses to run if it would
  leave the install without an administrator. `SEED_DEMO_DATA=false` skips the
  demo entirely; `DJANGO_SUPERUSER_USERNAME/PASSWORD` creates an initial account
  on first boot.
- **Readiness history.** A daily `ReadinessSnapshot` (recorded by Celery beat,
  by `manage.py record_readiness`, or lazily on the first dashboard hit of the
  day) feeds the dashboard's readiness trend and month-over-month delta. A fresh
  install shows one point — history is real, never illustrative.
- **Controls CSV export** (`GET /api/controls/export/`, honours the list
  filters, formula-injection safe).
- **Redesigned interface.** A token-driven design system with four theme packs
  (Audit Ledger, Nimbus, Ledger Dark, Obsidian) and four accent packs plus a
  custom accent colour; every page rebuilt on shared primitives (panels, badges,
  meters, segmented controls, donut/bar/trend charts); a compliance calendar
  with type filters and day detail; expandable control rows with inline
  evidence; keyboard-accessible folder tree, rows and tabs; a bell tray and
  theme picker in the top bar. Write controls are rendered only where the API
  would accept them (auditors on access reviews, evidence unlink per link).
- `LICENSE` (MIT) is in the tree; `CONTRIBUTING.md`; `REVIEW.md` (the audit
  report and release-readiness record); `.gitattributes` (LF for scripts so the
  installers survive Windows checkouts).

### Changed

- Dependencies: Django 5.2 LTS (from 5.0/5.1, both end-of-life), DRF 3.16+,
  SimpleJWT 5.5+, psycopg 3, Celery 5.5, gunicorn 23; React Router 7 (closes the
  two 6.30.x advisories carried since 0.1.0), Vite 7, Tailwind 3.4,
  framer-motion, lucide-react. `npm audit`: 0 vulnerabilities.
- Routes `/account` → `/settings` and `/audit` → `/audit-log` (old paths redirect).
- The static `app-preview.html` was removed; the README screenshots and the
  60-second Docker install replace it.
- Compose no longer requires a `.env`; its defaults are production-safe and
  `.env` overrides them.

### Migration notes (0.1.x → 0.2.0)

1. Pull, then `docker compose up -d --build` (or re-run the installer). The two
   new migrations (`documents.0002`, `analytics.0001`) apply automatically.
2. All existing refresh tokens keep working until they expire; the first
   refresh after upgrade rotates them.
3. If you had set `SECURE_SSL_REDIRECT=false` for an HTTP deployment, replace it
   with `BEHIND_TLS=false` (the old key still works).
4. Before real use: `docker compose exec backend python manage.py remove_demo_data`.

---

## [0.1.1] — 2026-08-07

A second review pass over the areas 0.1.0 never examined — the installers,
container tooling, seeding, email transports, documentation accuracy, and
front-end error/permission/accessibility states.

### Fixed — Docker deployment (data loss)

- **The Docker stack silently ran on SQLite, not PostgreSQL.** `settings.py`
  selects PostgreSQL only when `POSTGRES_DB` is set, but `docker-compose.yml`
  passed the backend and worker only `POSTGRES_HOST`/`POSTGRES_PORT`, and
  `.env.example` ships every `POSTGRES_*` line commented out. So the documented
  `cp .env.example .env && docker compose up` (and both installers' `--docker`
  path) produced: a PostgreSQL container holding nothing; an app database in the
  container's ephemeral layer, **destroyed on every rebuild**; and a worker with
  its own, never-migrated database, so the Celery review-reminder job could
  never see a real document. Compose now supplies the credentials to both
  services directly.
- **Images baked in the developer's database and virtualenv.** With no
  `.dockerignore` in either build context, `COPY . .` copied `backend/db.sqlite3`
  — real user rows and password hashes — plus a 123 MB host virtualenv and
  `node_modules` into the images. Added `.dockerignore` to both.
- **Uploaded evidence 404'd in production.** nginx proxied `/media/` to Django,
  which only registers that route when `DEBUG` is on — so with the documented
  `DJANGO_DEBUG=false`, every document, minute attachment and version download
  failed. nginx now serves `/media/` from the shared volume (keeping the
  attachment/nosniff headers).
- **Document download links dropped the port.** nginx forwarded `Host $host`,
  which strips the port, so Django built absolute URLs like
  `http://localhost/media/...` — broken whenever the app is served on any port
  other than 80. Now forwards `$http_host`.
- **Django admin rendered unstyled.** `collectstatic` ran on every boot but
  nothing served `STATIC_ROOT` under gunicorn. nginx now serves `/static/`.
- **Uploads over 1 MB were rejected** by nginx's default `client_max_body_size`
  before reaching Django. Raised to 32 MB.

### Fixed — security

- **The "refuses to boot on the placeholder secret key" guard never fired.**
  `settings.py` compared `SECRET_KEY` against `dev-insecure-change-me`, but
  `.env.example` ships a *different* placeholder, so the check only caught a
  completely unset key. Since `SIMPLE_JWT` has no separate `SIGNING_KEY`, a
  deployment left on the published placeholder would have had forgeable access
  tokens for any account. The guard now rejects every shipped placeholder and
  any key under 32 characters.
- **Mailbox TLS was unverified.** `IMAP4_SSL`/`POP3_SSL` were constructed
  without an SSL context, which in CPython means no certificate or hostname
  verification. Now uses `ssl.create_default_context()`, with STARTTLS/STLS on
  the non-implicit-TLS path, and applies `MAILBOX_TIMEOUT` to IMAP/POP3.

### Fixed — correctness

- **Folder tree was empty for anyone without root access.** Folders whose
  parent is not visible are now treated as roots of that user's view.
- **Document lists truncated at 50.** The Documents page now follows pagination.
- **IMAP Sent-folder filing always failed** for any folder name containing a
  space because the mailbox name was not quoted; failures are now logged.

### Fixed — accessibility & interface

- Sidebar navigation, account link and Sign out became real buttons inside a
  labelled `<nav>`; sign-in fields got programmatic labels; document actions
  surface server errors; the dashboard survives a single failed panel; "Mark
  reviewed" is gated on capabilities; phones can sign out.

### Fixed — seeded data integrity

- A framework update no longer duplicates the folder tree and orphans documents
  (folders carry `framework`/`category` foreign keys; controls are identified by
  `(framework, control_id)`); folder names are sanitised and length-capped;
  `generate_folder_tree` no longer overwrites `_control.md`.

## [0.1.0] — 2026-07-25

First tagged release. Conformiti builds, boots and runs end-to-end on both
supported paths (local SQLite and the Docker/PostgreSQL stack), with the whole
API surface, the async review-reminder pipeline and every UI route exercised
against a live system. Fixed startup blockers (missing settings import, upload
path length), inert login/MFA throttling, unauthenticated folder/document
listing, Jira SSRF rebind, audit-log suppression via malformed headers,
destructible control catalog, a review scan that aborted on one failed email,
un-editable folder permissions, access-review truncation at 50 rows, risk-import
500s, calendar day-shift bugs and a collapsed dashboard grid.

[0.2.0]: https://github.com/dboudreau00/Conformiti/releases/tag/v0.2.0
[0.1.1]: https://github.com/dboudreau00/Conformiti/releases/tag/v0.1.1
[0.1.0]: https://github.com/dboudreau00/Conformiti/releases/tag/v0.1.0
