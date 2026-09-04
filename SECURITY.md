# Security

This document records the security posture Conformiti ships with, the findings
of the two security reviews performed on it (0.1.0 and 0.2.0), the residual
risks you should weigh before hosting real compliance data, and how to report
a vulnerability.

## Reporting a vulnerability

Open a private security advisory on GitHub
(https://github.com/dboudreau00/Conformiti/security/advisories/new) or email
the maintainer listed in the repository profile. Please do not file public
issues for vulnerabilities. You will get an acknowledgement within a week.

## Posture at a glance

- **Authentication:** JWT (SimpleJWT). 60-minute access tokens; 7-day refresh
  tokens that **rotate on every use** and are **blacklisted on rotation and on
  sign-out** (`POST /api/auth/logout/`). `last_login` is kept current for
  access-review accuracy.
- **Two-factor auth (optional, per user):** TOTP (RFC 6238) compatible with any
  authenticator app, enforced at login as a second step, with single-use backup
  codes and admin lockout-recovery. Implemented on the standard library and
  verified against the RFC 4226/6238 test vectors in the test suite.
- **Authorization:** role-capability permission classes on every endpoint, plus
  object-level, inheritance-aware folder access for folders and documents.
  Built-in role flags are immutable through the API. Deletion of evidence and
  restructuring of the folder tree are *manage*-level acts.
- **Audit trail:** every successful mutating API call (actor, action, record,
  changed field names, IP) plus sign-in, failed sign-in (with reason) and
  sign-out. Written by server-side middleware; the API exposes no write methods.
- **Transport/headers:** `nosniff`, `X-Frame-Options: DENY`, referrer policy and
  a Permissions-Policy are always on; the shipped nginx sends a
  Content-Security-Policy (`script-src 'self'`); uploads are served as
  attachments inside a sandboxing CSP. With `DJANGO_DEBUG=false` and
  `BEHIND_TLS=true` (the default off DEBUG), HTTPS redirect, secure cookies and
  optional HSTS engage.
- **Abuse resistance:** per-client login (8/min) and MFA (10/min) throttles and
  a global anonymous throttle, with counters in Redis in the compose stack so
  the limit is shared across workers.
- **Uploads:** size ceiling (`MAX_UPLOAD_MB`, default 32) enforced at nginx and
  in the application; empty files and active-content extensions refused.
- **Supply chain:** pinned floors on current, supported majors (Django 5.2 LTS,
  React Router 7, Vite 7); `npm audit` clean; Dependabot; CI on every push.
- **Containers:** unprivileged user, healthchecks, API bound to loopback and
  fronted by nginx, secret key generated and persisted on first boot, DEBUG off
  by default, demo data removable with one command.

## Findings fixed in the 0.2.0 review

Severity uses the usual scale (High: exploitable for data loss/escalation or
denial of service; Medium: meaningful weakening of a control; Low: hardening).
The full method and evidence are in [REVIEW.md](REVIEW.md).

| # | Severity | Issue | Fix |
|---|----------|-------|-----|
| 1 | High | A folder could be moved under one of its own descendants, creating a parent cycle; `Folder.ancestors()` then looped forever inside every access check — one PATCH from any user with edit on a folder hung the API. | Cycle rejected at validation; ancestor walk bounded; corrupted chains raise instead of spinning. |
| 2 | High | Re-parenting a folder required only *edit* on the folder itself, so a user could move a subtree under a folder they could not see — exposing it to everyone granted on the destination's ancestors. | Moving requires *manage* on the folder and *edit* on the destination; top-level moves require the folders capability; generated framework folders cannot be moved, renamed or deleted. |
| 3 | High | Refresh tokens were neither rotated nor revocable: a stolen refresh token minted access tokens for its full 7-day life, and sign-out was client-side only. | Rotation + blacklist on every refresh; server-side logout endpoint; weekly blacklist pruning. |
| 4 | Medium | Throttle counters lived in a per-process local-memory cache, so with 3 gunicorn workers the login limit was effectively 24/min per worker set, and nothing was shared between containers. | Redis-backed cache when `CACHE_URL` is set (compose sets it). |
| 5 | Medium | A document's owner could delete it with only *view* on the folder ("owners may always edit their own"), letting a control owner remove their own evidence trail. | Delete requires *manage* on the folder; ownership still grants edit. |
| 6 | Medium | No application-level upload limit or type check: the dev server, admin and any direct-to-gunicorn deployment accepted unbounded uploads and stored `.html`/`.svg`/`.exe` as evidence. | Size ceiling and blocked-extension list enforced in serializers for every upload path; `/media/` sandboxed by CSP. |
| 7 | Medium | Authentication events were not in the audit trail, and mutation entries recorded only the path — an auditor could not tell that a failed brute-force ran or which fields of a user were changed. | Login/failed-login/logout events with reason and IP; mutation entries carry changed field names (never values) and created ids. |
| 8 | Medium | The Docker quickstart and both installers' Docker path ran the stack in DEBUG with the published placeholder key (and 0.1.1's guard only fires with DEBUG off). | Compose defaults to DEBUG off with an auto-generated persisted key; installers write a production-style `.env`; the container refuses placeholder keys off DEBUG. |
| 9 | Medium | The API and admin were published on `0.0.0.0:8000` alongside nginx, exposing the browsable API and admin login directly on the LAN. | Port bound to `127.0.0.1`; admin proxied through nginx; browsable API disabled in production. |
| 10 | Low | Built-in role capability flags could be rewritten through `PATCH /roles/{id}/` (e.g. giving *Viewer* `can_manage_users`). | Flags on `is_system` roles are locked; custom roles remain fully editable. |
| 11 | Low | An administrator who is not a superuser could reset a superuser's MFA. | Requires superuser. |
| 12 | Low | Folder names were not validated; `..`, separators and Windows-reserved characters reached the storage layer as path segments (a clean 400 from Django's storage, but a confusing failure at upload time rather than at creation). | Validated as a single path segment at creation and rename. |
| 13 | Low | `POST /notifications/dismiss/` accepted any key, allowing unbounded growth of the receipt table. | Key must be in the caller's live feed. |
| 14 | Low | The inline theme bootstrap in `index.html` prevented a `script-src 'self'` CSP, so the shipped nginx config left CSP commented out. | Bootstrap moved to `/theme-init.js`; CSP enabled by default. |
| 15 | Low | Password minimum of 8 characters is below PCI DSS v4.0.1 §8.3.6 (12). | Default 12 (`PASSWORD_MIN_LENGTH`). |
| 16 | Low | The container ran as root. | Unprivileged `app` user; writable paths owned by it. |
| 17 | High | **A development `.env` put the Docker stack into DEBUG.** Compose reads `./.env` for `${...}` substitution *and* into the containers, and that file is written by the *local* installer with `DJANGO_DEBUG=true` and a development signing key — so `./install.sh` followed by `docker compose up` produced a DEBUG container issuing tokens signed with the dev key, despite the compose default being `false`. Found by booting the stack and asserting `settings.DEBUG` inside it, not by reading the file. | Fixed: the stack reads `CONFORMITI_DEBUG` / `CONFORMITI_SECRET_KEY`, which a development `.env` never contains; validator check 16 fails the build if the old interpolation returns. |

### Findings fixed in the 0.1.0 review (still in force)

ACL map disclosure and privilege escalation through folder grants, missing
calendar write authorization, CSV formula injection, Jira SSRF (redirects, DNS
rebind), inert login/MFA throttles, unauthenticated folder/document lists,
placeholder-secret-key boot, missing transport hardening, stored XSS via
uploaded `.html`, unvalidated admin-set passwords, an unbounded `?days=`
parameter, a document move that bypassed destination checks, and spoofable
audit IPs. See the 0.1.x entries in [CHANGELOG.md](CHANGELOG.md).

## Verified and already sound

- No serializer uses `fields = "__all__"`; `UserWriteSerializer` omits
  `is_superuser`/`is_staff`, so the API cannot mint a Django superuser (tested).
- Self-service profile edits (`PATCH /users/me/`) cannot change role, status
  or superuser (tested).
- Access-review rows snapshot decisions server-side; completed reviews are
  read-only (tested).
- The Jira API token is write-only in the API and issue fetches are proxied
  server-side; base URLs must be `https` to a public host (tested).
- Document/folder object permissions enforce view/edit/manage with inheritance;
  querysets are filtered to visible folders (tested for list, detail, tree,
  evidence links, calendar feed and analytics).
- ORM is used throughout (no raw SQL / string-built queries).
- MFA is opt-in and safe by construction: the device is enabled only after a
  code is confirmed; disabling or regenerating codes is password-gated; backup
  codes are stored only as hashes and are single-use (tested end to end).
- The audit trail viewer is read-only end to end (tested: POST/PATCH/DELETE → 405).
- User-management lockout guards (no self-deletion/deactivation/role change, no
  touching superusers as a non-superuser, never zero active administrators) are
  covered by tests.
- The risk-register importer is manager-only and defensive: 2 MB request cap,
  zip-bomb guard on `.xlsx`, 1000-row limit, stdlib XML parsing, per-field
  length caps; every CSV export goes through the formula-injection sanitiser
  (tested).
- The secret-key guard refuses placeholders and short keys off DEBUG and
  generates/persists a key from `DJANGO_SECRET_KEY_FILE` (tested by booting the
  settings in a subprocess).

## Residual risks to weigh for production

- **Tokens in `localStorage`.** The SPA stores JWTs in `localStorage`, the common
  SPA pattern, so any XSS can read the access token (now short-lived) and the
  refresh token (now single-use and revocable). The shipped CSP is the primary
  mitigation. For the highest assurance, move to `HttpOnly` cookie auth with
  CSRF protection — an architectural change, not a config flag.
- **Jira token and TOTP secrets are stored in the application database** in
  clear text (like most self-hosted integrations). Use a dedicated scoped Jira
  token, restrict DB access, and consider field encryption or a secrets manager
  if your threat model requires it.
- **Passkeys (WebAuthn) and OAuth/SAML SSO are not implemented.** TOTP MFA
  covers the second-factor requirement today; SSO is on the roadmap.
- **Uploaded file contents are not scanned.** Files are typed and size-capped
  and served as attachments, but not virus-scanned. Add scanning if you accept
  files from untrusted users.
- **Usernames and emails are readable by every signed-in user** (`GET /users/`),
  because owner and assignee pickers need them. Acceptable for an internal
  tool; not for a multi-tenant one.
- **`DJANGO_DEBUG` still defaults to true for the *local developer* path** so
  a first `./install.sh` is friction-free. The Docker stack defaults to off.
- **No third-party penetration test has been performed.** The reviews in this
  document were code-level reviews with automated tests; a professional
  assessment is recommended before hosting regulated data.

## Production checklist

1. `DJANGO_DEBUG=false` and a strong unique `DJANGO_SECRET_KEY` (or
   `DJANGO_SECRET_KEY_FILE` on a persistent volume, as compose does).
2. Set `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS` to
   your real origins.
3. Terminate TLS in front of nginx and set `BEHIND_TLS=true`; set
   `SECURE_HSTS_SECONDS` once HTTPS is stable.
4. Use PostgreSQL and Redis (compose provides both) and a real
   `EMAIL_PROVIDER` so review reminders reach owners.
5. Create your own administrator (`createsuperuser` or `DJANGO_SUPERUSER_*`),
   then run `manage.py remove_demo_data`. Confirm `/api/health/` reports
   `"demo_accounts": false`.
6. Back up the database and the media volume nightly; test a restore once.
7. Restrict who can reach `/admin/` (it is proxied through nginx; put it behind
   your reverse proxy's allow-list or VPN).
