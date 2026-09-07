# Security

This document records the security posture Conformiti ships with, the findings
of the two security reviews performed on it (0.1.0 and 0.2.0), the residual
risks you should weigh before hosting real compliance data, and how to report
a vulnerability.

## Workspace isolation (0.9.0)

Several organisations may share one installation. Isolation is enforced in
the ORM layer (`accounts/tenancy.py`): every organisation-owned table has a
`workspace` column and the default manager scopes every query to the
workspace of the signed-in person, including primary-key lookups (a foreign
row is a 404) and the querysets behind serializer fields (a foreign foreign
key is a 400). There is no per-request opt-out short of calling
`tenancy.unscoped()` by name. A superuser may switch workspaces; nobody
else's `X-Workspace` header is honoured. Each release's suite includes
`accounts/tests_tenancy.py`, which stands a second organisation beside the
first and checks the collection lists, by-id fetches, cross-workspace
references, the header, the archive rules and the scheduled jobs from its
point of view.

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
- **Passkeys / security keys (WebAuthn, optional, per user):** a second
  factor after the password, alone or beside TOTP. The relying-party side
  (CBOR, COSE keys, both ceremonies) is in `accounts/webauthn.py` on the
  `cryptography` package, small enough to read; ES256, RS256 and EdDSA;
  challenges are 32 random bytes kept in a database row that answers once
  and expires in five minutes; origin, relying-party id, ceremony type and
  user presence are all checked, user verification when configured.
  Attestation is requested as `none` and never verified — a second factor
  needs the same key to sign next time, not the authenticator's make. **The
  signature counter is enforced and fails closed:** a counter that does not
  advance marks the key as possibly cloned and refuses the sign-in, while
  the account still requires a second factor (its other passkey, the
  authenticator app, or an administrator's reset). Removing a key takes the
  account password. Every enrolment, refusal and removal is in the audit trail.
- **Single sign-on (optional, OpenID Connect):** authorization code + PKCE;
  `state` and `nonce` held server-side in the session; ID tokens verified
  against the provider's JWKS for signature (asymmetric algorithms only — an
  `HS256` token signed with the client secret is refused), issuer, audience,
  expiry and nonce; provider endpoints reached over https only, without
  following redirects, with a bounded body. The provider is configured **from
  the environment only** — there is deliberately no screen or API for it,
  because a provider an administrator could register is a provider they could
  point at themselves. A verified email links exactly one existing account and
  **never a superuser or staff account**; those are linked only by an operator
  running `manage.py link_oidc_identity --allow-privileged`. Auto-provisioning
  is off by default and refuses a default role that can manage users. The
  SPA receives its tokens through a one-time ticket bound to the browser
  session that ran the flow. Every outcome — linked, provisioned, refused and
  why — is in the audit trail.
- **Single sign-on over SAML 2.0 (optional):** SP-initiated, signed
  HTTP-POST responses only. The provider's signing certificate from the
  environment is the sole trust anchor — no metadata fetch, no certificate
  taken from the message. Signatures are verified with asymmetric algorithms
  only, and **only the element the signature covers is read**, so a Response
  carrying an extra unsigned assertion yields nothing from it. Issuer,
  audience, destination, recipient, `InResponseTo`, the validity window
  (with clock skew) and bearer confirmation are all checked; assertion ids
  are accepted once, from a shared table. XML is parsed with entities and
  DTDs refused and no network. The sign-in state travels in a signed
  `SameSite=None; Secure` cookie because the provider's POST is cross-site.
  Account rules are the OIDC rules, in the same code.
- **Step-up on SSO (default on when enrolled):** when the provider did not
  assert a second factor and the person has a local authenticator, the
  tokens are withheld until its code is given; `SSO_STEP_UP=required` refuses
  a sign-in with neither. Five wrong codes spend the ticket.
- **Evidence preview never renders a file as HTML.** Images stream inline
  only when their first bytes say so and are shown from a `blob:` URL in an
  `<img>`. **PDFs are drawn by pdf.js onto canvases** in a worker shipped
  with the bundle, scripting off — no frame, no plugin, no PDF JavaScript.
  Word and Excel are parsed on the server with the standard library
  (zip bomb and size limits, no external entities) into a small structured
  vocabulary the SPA renders itself. No third-party viewer is involved.
- **Secrets at rest:** the two columns that must be readable by the server —
  the TOTP shared secret and the Jira API token — are encrypted with
  AES-256-GCM under a rotatable key ring (`manage.py rotate_field_keys`). The
  associated data binds each ciphertext to its own row and column, so a value
  lifted from a database dump and written into another row is inert. Everything
  else secret is hashed, not encrypted: passwords and MFA backup codes.
- **Evidence is read through the API, never off the filesystem.** Uploaded
  files are served by `GET /api/documents/<id>/download/`, which resolves folder
  access first and writes an audit row; nginx marks the media volume `internal`,
  so the bytes can only be entered through an `X-Accel-Redirect` from the API.
  No serializer publishes a storage path. (Before 0.3.0 the volume was a plain
  alias and upload paths were guessable.)
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
- **Optional malware scanning.** `docker compose --profile scanning up -d` plus
  `CONFORMITI_SCANNING=true` sends every uploaded file to a ClamAV daemon before
  it is stored — documents, new versions, meeting minutes and form templates.
  Scanning happens *after* the folder permission check, so an unauthorised
  caller can neither use it as a signature-set oracle nor tie the scanner up.
  When it is enabled it fails **closed**: if the scanner cannot be reached the
  upload is refused, because "is evidence scanned?" must not depend on whether
  the daemon happened to answer. There is deliberately no fail-open switch.
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

- **Cookie transport is the default since 0.6.1.** The tokens travel as
  `HttpOnly`, `SameSite=Lax` cookies that script cannot read, with Django's
  CSRF check on unsafe methods; over https the access cookie is
  `__Host-conformiti_access` (host-bound, `Path=/`, no `Domain`, so a sibling
  subdomain cannot plant one), the refresh cookie `__Secure-conformiti_refresh`
  on its narrow `/api/auth/token/` path, and the CSRF cookie
  `__Host-csrftoken`. Be clear about the size of the win: XSS can still act as
  the user while the page is open, because the browser attaches the cookie for
  it. What it can no longer do is *exfiltrate* a credential that keeps working
  after the tab closes. Same-origin deployments only, which is what the
  shipped nginx serves. `AUTH_TRANSPORT=header` restores the 0.2.x–0.6.0
  behaviour (tokens in `localStorage`); switching signs everyone out once, and
  both modes accept a Bearer header, so API clients are unaffected. The
  end-to-end suite runs against both transports in CI.
- **Quarantine keeps the bytes.** A stored document the re-scan flags is
  refused on every route that serves it (download, preview, versions, pinned
  package evidence, PBC attachments) but stays on disk for the investigation;
  deleting it is a person's decision. `manage.py scan_evidence` is only as
  good as the definitions clamd holds, and a file the scanner could not
  inspect is recorded as *error*, never as clean.
- **The field-encryption key is only as protected as where you put it.**
  Encryption at rest defends against a stolen dump or backup, not against an
  attacker who already has the application's key. If the key ring is derived
  from `DJANGO_SECRET_KEY`, one secret protects both; keep them separate for a
  stronger separation, and use a secrets manager if your threat model needs it.
  It also does not stop an attacker who can *write* to the database — the read
  path deliberately accepts legacy plaintext so an upgrade cannot lock you out.
- **Back up the encryption key with the database.** Without it, enrolled
  authenticators cannot be read. That degrades safely rather than dangerously:
  the secret is never destroyed, MFA is still demanded at login, users can sign
  in with their (deliberately unencrypted) single-use backup codes, and an
  administrator can reset a user's enrollment. Restoring the key restores the
  secrets. A saved Jira token would have to be re-entered.
- **An evidence package is a deliberate, narrow disclosure — and the only
  place folder permissions are bypassed.** An auditor holding a live grant on a
  sealed package can read exactly the artefacts pinned into it, and nothing
  else. That bypass lives in one module (`attestations/access.py`) so it can be
  reviewed in one sitting. Packaging cannot launder access: a document can only
  be pinned by someone who could already see its folder. Grants are per user
  (never per role), time-boxed, revocable in one click, and re-evaluated on
  every request, so deactivating or demoting the account closes it immediately.
  Every file that leaves is recorded before it leaves.
- **A sealed package is signed, and the signature is only as good as the
  key.** Since 0.7.0 every manifest is signed (Ed25519, detached) with a key
  that lives in a file (`SIGNING_KEY_FILE`, 0600, in the `secrets` volume)
  or the environment — never in the database, so a dump, a backup or a SQL
  injection yields the evidence and every digest but not the key. The
  public key is published (`/api/signing-keys/`, Settings › About), the
  bundle carries it, and the shipped `verify.py` checks the signature with
  the standard library alone. What the signature proves: the manifest was
  signed by whoever held the key at sealing. What it cannot prove: that the
  key was never copied — protect the secrets volume as you would the Django
  secret key, rotate with `manage.py rotate_signing_key` if in doubt (old
  packages keep verifying under the key they carry), and keep publishing
  the digest out of band; the `seal` entry in the audit trail is the other
  half of the binding. A package sealed with no key configured is unsigned,
  and every screen and the bundle's README say so.
- **An SSO login still rests on the identity provider.** Step-up asks for a
  local authenticator only when one is enrolled (or, with
  `SSO_STEP_UP=required`, refuses otherwise); a person with no local
  authenticator is as strong as the provider's assertion. A compromised IdP
  tenant administrator can sign in as any linked non-privileged user — which
  is why administrator accounts are never linked by email and why the
  provider cannot be changed from inside the app. SAML requests are not
  signed (responses are).
- **A passkey-only account has no backup codes.** Codes belong to the TOTP
  device; a person whose single passkey is lost or flagged as cloned needs a
  second key, the authenticator app, or an administrator's reset. The
  settings screen says so before they rely on one key.
- **The questionnaire link is a bearer credential.** Whoever holds it can
  read the twelve questions, the vendor's own draft and the vendor's name,
  and submit once — nothing else. It is 32 random bytes, stored only as a
  hash, expires (14 days by default, 90 at most), is superseded by the next
  send, and can be withdrawn; the public endpoints have their own rate
  limit. It goes out by email, so it is as private as the vendor's mailbox.
- **Naming an assignee on a PBC request is a disclosure.** The person
  assigned sees that line, the package's name, and every document attached
  to it (which they could attach only from folders they can already see),
  even with no package access. This is the second folder-permission bypass
  in the product and sits beside the first in `attestations/access.py`.
- **Office preview parses untrusted files on the server.** Word and Excel
  previews go through `zipfile` and `xml.etree` with hard ceilings (40 MB
  unzipped as declared, 12 MB per part as actually read, 400,000 tags per
  part, 3,000 blocks, 12 sheets of 1,000×64 cells, 512 KB of text) and
  Python's expat, which does not resolve external entities. The parsing is
  bounded and stdlib-only rather than sandboxed; if you accept uploads from
  people you do not control, keep malware scanning on, and note that the
  preview endpoint runs in the API process.
- **Malware scanning is off unless you turn it on.** Without the scanning
  profile, files are typed, size-capped and served as attachments, but not
  scanned. Turn it on if you accept files from people you do not control.
- **The risk-register importer is not scanned.** `POST /api/risks/import/` reads
  the uploaded spreadsheet with `upload.read()` and never writes it to storage,
  so there is nothing to serve back; it is manager-only and already bounded by
  a 2 MB cap, a zip-bomb guard and stdlib XML parsing. Stated here rather than
  silently skipped.
- **Usernames and emails are readable by every signed-in user of the same
  workspace** (`GET /users/`), because owner and assignee pickers need them.
  Since 0.9.0 the list stops at the workspace boundary; within one
  organisation it is the whole directory.
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
