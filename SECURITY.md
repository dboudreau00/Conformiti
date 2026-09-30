# Security

The security posture Conformiti ships with, the reviews it has been through,
the residual risks to weigh before hosting real compliance data, and how to
report a vulnerability.

## Reporting a vulnerability

Report a vulnerability privately through GitHub:
https://github.com/dboudreau00/Conformiti/security/advisories/new opens an
advisory that only you and the maintainer can see. Please do not file public
issues for vulnerabilities. You will get an acknowledgement within a week.

## Supported versions

Security fixes are made to the latest 0.9.5 revision only. 0.9.5 was the last
feature release, and every fix since has shipped as a new revision of it
(0.9.5b, 0.9.5c and so on), with its details in
[CHANGELOG.md](CHANGELOG.md). An earlier revision is not patched separately:
upgrade to the latest revision to take a fix.

Please keep a report private until a fixed revision is published. The fix is
then recorded in CHANGELOG.md.

## Reviews

Twelve in total, of which **seven were independent**. Each had its findings
fixed before the release that followed, apart from those its record accepts or
defers with the reasoning: two informational findings of the 0.2.0 review (S-17
and S-18, accepted), one of the 0.9.5h review (L-8, a passkey as proof when
changing a factor, deferred), and two findings of the 0.9.0 review that were
fixed only in part (H-14, where the throttle key was fixed but no per-account
lockout was added, and H-16, where a new upload version still clears
quarantine). [REVIEWS.md](REVIEWS.md) holds the method, every finding and its
status today, and a section on what was deliberately left alone.

Here each review is named by the release it reviewed. In REVIEWS.md a review
is named by the release that closed it, as the code comments cite it, so the
0.9.5e review below is the "0.9.5f review" there.

| Review | | Findings | Record | Closed in |
|---|---|---|---|---|
| 0.1.0, first pass | internal | 13 named below | below | 0.1.1 |
| 0.2.0, line by line | internal | 34 (19 security: 17 fixed, 2 accepted) | [REVIEWS.md](REVIEWS.md), 0.2.0 review | 0.2.0 |
| 0.9.0, adversarial | **independent** | 50 confirmed of 69 candidates (2 fixed in part) | [REVIEWS.md](REVIEWS.md), 0.9.0 review | 0.9.1 to 0.9.4 |
| 0.9.4, source review | **independent** | not counted; every real one fixed | [CHANGELOG.md](CHANGELOG.md) | 0.9.5 |
| 0.9.5, source review | **independent** | 9, plus 2 found while fixing, all fixed | [REVIEWS.md](REVIEWS.md), 0.9.5 review | 0.9.5b |
| 0.9.5e, source review | **independent** | 14, plus 3 raised in passing, all fixed | [REVIEWS.md](REVIEWS.md), 0.9.5f review | 0.9.5f |
| 0.9.5g, source review | **independent** | 14: 13 fixed, 1 deferred | [REVIEWS.md](REVIEWS.md), 0.9.5h review | 0.9.5h |
| 0.9.5h, source review | **independent** | 3, all fixed | [REVIEWS.md](REVIEWS.md), 0.9.5i review | 0.9.5i |
| 0.9.5j, code review | internal | 155 upheld of 161 reported | [CHANGELOG.md](CHANGELOG.md) | 0.9.5k |
| 0.9.5l, post-release install check | internal, run with automated agents | 2 | [CHANGELOG.md](CHANGELOG.md) | 0.9.5m |
| 0.9.5m, release review | **independent** | 3 (one bug, two suggestions), all closed | [CHANGELOG.md](CHANGELOG.md) | 0.9.5ma |
| 0.9.5ma, documentation audit | internal, run with automated agents | every document held to the code; 19 code defects fixed | [CHANGELOG.md](CHANGELOG.md) | 0.9.5mb (11); the other 8 unreleased |

The independent reviews up to 0.9.5h are the substantial ones. The 0.9.0
review attacked tenancy, authentication, single sign-on, file ingest,
cryptography, background jobs and deployment as separate exercises, and
every candidate was then
attacked again by three reviewers asking whether it was real, whether the
cited code said what was claimed, and whether something already mitigated it.
The 0.9.5 review found nine, of which the one that mattered was a chat webhook
URL, a credential, readable by every signed-in account including an issued
external auditor.

## Workspace isolation (0.9.0)

Several organisations may share one installation. Isolation is enforced in
the ORM layer (`accounts/tenancy.py`): every organisation-owned table has a
`workspace` column and the default manager scopes every query to the
workspace of the signed-in person, including primary-key lookups (a foreign
row is a 404) and the querysets behind serializer fields (a foreign foreign
key is a 400). There is no per-request opt-out short of calling
`tenancy.unscoped()` by name. The filter applies while a workspace is active,
which every signed-in request has (a person with no workspace is refused).
With none active (unauthenticated endpoints, management commands and
scheduled jobs) there is no filter at all, so each of those paths has to
scope itself: the public questionnaire and the signing-key endpoint name
their workspace (`tenancy.scoped`), and the scheduled jobs that touch an
organisation's records walk every workspace in turn
(`tenancy.for_each_workspace`). A superuser may switch workspaces; nobody
else's `X-Workspace` header is honoured. Each release's suite includes
`accounts/tests_tenancy.py`, which stands a second organisation beside the
first and checks the collection lists, by-id fetches, cross-workspace
references, the header, the archive rules and the scheduled jobs from its
point of view.

## Posture at a glance

- **Authentication:** JWT (SimpleJWT, HS256, signed with the Django secret
  key: see *Residual risks*). 60-minute access tokens (`JWT_ACCESS_MINUTES`);
  7-day refresh tokens (`JWT_REFRESH_DAYS`) that **rotate on every use** and
  are **blacklisted on rotation and on sign-out**. The browser signs out
  through `POST /api/auth/token/clear/`, which receives the refresh cookie on
  its narrow path and revokes that token and, while the access cookie is
  still valid, every other refresh token the account holds. An API client
  revokes its own token with `POST /api/auth/logout/`, sending it as
  `refresh` in the body; in cookie mode that endpoint receives no refresh
  cookie and revokes nothing. Each rotation starts a new 7-day window, so the
  refresh lifetime works as a 7-day idle limit and there is no absolute
  session limit: a session that renews at least once a week has no fixed
  end. Signing out revokes refresh tokens only; an access token already
  issued keeps working until it expires. A password change, a password set
  by an administrator (through the API, or on the Django admin's password
  page from 0.9.5mb) and an MFA reset also refuse the access tokens issued
  before them, and a deactivated account is refused on its
  next request. The Django admin keeps its own session cookie (two weeks,
  Django's default), which signing out of the application does not end.
  `last_login` records the last interactive sign-in (password or single
  sign-on), not renewals.
- **Two-factor auth (optional, per user):** TOTP (RFC 6238) compatible with any
  authenticator app, enforced at login as a second step, with single-use backup
  codes and admin lockout-recovery. Implemented on the standard library and
  verified against the RFC 4226/6238 test vectors in the test suite. It is
  each person's choice: no setting requires a second factor for password
  sign-ins, administrators included (`SSO_STEP_UP` applies to single sign-on
  only).
- **Passkeys / security keys (WebAuthn, optional, per user):** a second
  factor after the password, alone or beside TOTP. The relying-party side
  (CBOR, COSE keys, both ceremonies) is in `accounts/webauthn.py` on the
  `cryptography` package, small enough to read; ES256, RS256 and EdDSA;
  challenges are 32 random bytes kept in a database row that answers once
  and expires in five minutes; origin, relying-party id, ceremony type and
  user presence are all checked, user verification when configured.
  Attestation is requested as `none` and never verified: a second factor
  needs the same key to sign next time, not the authenticator's make. **The
  signature counter is enforced and fails closed** for authenticators that
  keep one: a counter that does not advance marks the key as possibly cloned
  and refuses the sign-in, while the account still requires a second factor
  (its other passkey, the authenticator app, a backup code, or an
  administrator's reset). An authenticator that keeps no counter reports
  zero every time, as many synced passkeys do; that is accepted, so such a
  key can never be flagged this way. Adding or removing a key takes proof
  that the account is yours: the password, a code from the authenticator
  app, or an unspent backup code (an account with neither a password nor a
  factor, such as one provisioned by single sign-on, makes its first
  enrolment without one). Every enrolment, refusal and removal is in the
  audit trail.
- **Single sign-on (optional, OpenID Connect):** authorization code + PKCE;
  `state` and `nonce` held server-side in the session; ID tokens verified
  against the provider's JWKS for signature (asymmetric algorithms only: an
  `HS256` token signed with the client secret is refused), issuer, audience,
  expiry and nonce; provider endpoints reached over https only, without
  following redirects, with a bounded body. The provider is configured **from
  the environment only**: there is deliberately no screen or API for it,
  because a provider an administrator could register is a provider they could
  point at themselves. A verified email links exactly one existing account of
  the workspace single sign-on serves (`SSO_WORKSPACE`) and **never a
  superuser, a staff account or an account whose role can manage users**.
  The same test runs again at every sign-in, so an account promoted after it
  was linked is refused. Those accounts are linked only by an operator
  running `manage.py link_oidc_identity --allow-privileged`. Auto-provisioning
  is off by default and refuses a default role that can manage users. The
  SPA receives its tokens through a one-time ticket bound to the browser
  session that ran the flow. Every outcome (linked, provisioned, refused and
  why) is in the audit trail.
- **Single sign-on over SAML 2.0 (optional):** SP-initiated, signed
  HTTP-POST responses only. The provider's signing certificate from the
  environment is the sole trust anchor: no metadata fetch, no certificate
  taken from the message. Signatures are verified with asymmetric algorithms
  only, and **only the element the signature covers is read**, so a Response
  carrying an extra unsigned assertion yields nothing from it. Issuer,
  audience, destination, recipient, `InResponseTo`, the validity window
  (with clock skew) and bearer confirmation are all checked; assertion ids
  are accepted once, from a shared table. XML is parsed with entities and
  DTDs refused and no network. The sign-in state travels in a signed
  `SameSite=None; Secure` cookie because the provider's POST is cross-site.
  Account rules are the OIDC rules, in the same code, except that an email
  address in a validly signed assertion counts as verified: there is no
  SAML equivalent of `OIDC_REQUIRE_VERIFIED_EMAIL`.
- **Step-up on SSO (default on when enrolled):** when the provider did not
  assert a second factor and the person has a local authenticator, the
  tokens are withheld until its code is given; `SSO_STEP_UP=required` refuses
  a sign-in with neither. Five wrong codes spend the ticket.
- **Evidence preview never renders a file as HTML.** Images stream inline
  only when their first bytes say so and are shown from a `blob:` URL in an
  `<img>`. **PDFs are drawn by pdf.js onto canvases** in a worker shipped
  with the bundle, scripting off: no frame, no plugin, no PDF JavaScript.
  Word and Excel are parsed on the server with the standard library
  (zip bomb and size limits, no external entities) into a small structured
  vocabulary the SPA renders itself. No third-party viewer is involved.
- **Secrets at rest:** the four columns that must be readable by the server
  (the TOTP shared secret, the Jira API token, and each workspace's Slack and
  Teams webhook URLs) are encrypted with AES-256-GCM under a rotatable key
  ring (`manage.py rotate_field_keys`). The associated data binds each
  ciphertext to its own row and column, so a value lifted from a database
  dump and written into another row is inert. Passwords, MFA backup codes
  and questionnaire link tokens are hashed. Two kinds of live credential are
  stored as they are, because the frameworks keep them that way: every
  outstanding refresh token (the whole token, in
  `token_blacklist_outstandingtoken`, valid for up to 7 days and renewable)
  and every Django session key (`django_session`, which is what an admin
  sign-in holds). A copy of the database, a backup included, lets its holder
  resume those sessions until they expire or are revoked, so treat dumps and
  backups as credentials.
- **Evidence is read through the API, never off the filesystem.** Uploaded
  files are served by `GET /api/documents/<id>/download/`, which resolves folder
  access first and writes an audit row; nginx marks the media volume `internal`,
  so the bytes can only be entered through an `X-Accel-Redirect` from the API.
  No serializer publishes a storage path. (Before 0.3.0 the volume was a plain
  alias and upload paths were guessable.) With `DJANGO_DEBUG=true` (the local
  development path) Django also serves `/media/` itself, with no access check
  and no audit row, so never put real evidence on a development server.
- **Authorization:** role-capability permission classes on every endpoint, plus
  object-level, inheritance-aware folder access for folders and documents.
  Built-in role flags are immutable through the API. Deletion of evidence and
  restructuring of the folder tree are *manage*-level acts.
- **Audit trail:** every successful mutating API call and every change
  saved in the Django admin (actor, action, record, changed field names, the
  client's address) plus sign-in, failed sign-in (with reason) and sign-out,
  for the application, single sign-on and the Django admin. A sign-in refused
  by the rate limit is recorded once per client a minute, so a flood of them
  is not a flood of writes. Turning the authenticator app on or off,
  regenerating backup codes, adding or removing a passkey, an MFA reset and a
  password set by an administrator are recorded as their own events. Written
  server-side; nobody edits or deletes an entry, a superuser included: the API
  has no write method, the Django admin shows the trail read-only, and a
  workspace (which owns its trail) cannot be deleted there. The client's
  address is found along `X-Forwarded-For` as `NUM_PROXIES` says, as the rate
  limits find it, so it is only as right as that setting. Requests the API
  refuses are not recorded, failed sign-ins apart. Anyone with write access to
  the database can still change the trail. Keep `/admin/` to the few people
  who need it (checklist item 7).
- **Transport/headers:** Django sends `nosniff`, `X-Frame-Options: DENY` and
  a same-origin referrer policy on every API and admin response. The shipped
  nginx adds them, a Permissions-Policy (`geolocation=(), microphone=(),
  camera=()`) and a Content-Security-Policy (`default-src 'self'; script-src
  'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'`, images also
  from `data:` and `blob:`, `object-src 'none'`, `frame-ancestors 'none'`)
  to the application and API responses. `'wasm-unsafe-eval'` is for the PDF
  viewer's WebAssembly image decoders and permits no JavaScript eval. Hashed
  assets under `/assets/` and `/static/` carry only `nosniff`, and a web
  server of your own sends the Permissions-Policy and the CSP only if you
  add them. Uploads are served as attachments inside a sandboxing CSP.
  Nothing is loaded from a third party at page load (no font, script or
  stylesheet from a CDN), so the login screen and the public vendor
  questionnaire tell nobody the address of your installation. With
  `DJANGO_DEBUG=false` and `BEHIND_TLS=true`, HTTPS redirect, `Secure`
  cookies with the `__Host-` and `__Secure-` prefixes, and optional HSTS
  engage. The code defaults `BEHIND_TLS` to on when DEBUG is off, but the
  published image, `docker-compose.yml` and both installers' Docker path set
  it to `false`, because the stack serves plain HTTP (port 8080 by default,
  on every interface) until a TLS terminator is put in front. Until you set
  `BEHIND_TLS=true`, the Docker stack issues cookies without `Secure` and
  without the prefixes, and redirects nothing. The redirect applies to what
  Django answers (`/api/`, `/admin/`); let the terminator redirect the rest.
- **Abuse resistance:** limits per client address on sign-in (8/min,
  `THROTTLE_LOGIN`, which also counts the second factor typed at sign-in and
  the single sign-on steps), token refresh (30/min), the public
  questionnaire (20/min) and other unauthenticated requests (30/min, from
  which the health, session, sign-out and sign-in configuration endpoints
  are exempt), and a per-account limit (10/min, `THROTTLE_MFA`) on enrolling,
  confirming, removing and regenerating a second factor. There is no
  per-account lockout: attempts against one account from many addresses are
  limited only per address, so watch the `login_failed` rows in the audit
  trail. Counters live in Redis in the compose stack so the limit is shared
  across workers. Without Docker, `CACHE_URL` must point at Redis for the
  same effect; unset, each gunicorn worker counts on its own.
- **Uploads:** a size ceiling enforced in the application (`MAX_UPLOAD_MB`,
  default 32) and at nginx (`client_max_body_size 32m` in
  `frontend/nginx.conf`, which does not follow `MAX_UPLOAD_MB`: change both
  together); empty files refused. Refused by extension: executables and
  scripts, web pages (`.html`, `.svg`, `.mht` and similar), macro-enabled and
  legacy Office formats, and `.rtf`. Refused by content: any file carrying
  the legacy Office (OLE2) signature, whatever it is called, and `.docx`,
  `.xlsx` and `.pptx` files (and their template and show variants) that
  carry macros or embedded OLE objects. It is a list of what is refused, not
  of what is allowed: any other type is stored and downloaded as an
  attachment. Files arrive through the API only: the Django admin takes
  none, and cannot change a document's scan verdict or clear its quarantine.
- **Optional malware scanning.** `docker compose --profile scanning up -d` plus
  `CONFORMITI_SCANNING=true` (on bare metal, `CLAMAV_ENABLED=true` with
  `CLAMAV_HOST` and `CLAMAV_PORT` pointing at your clamd:
  `CONFORMITI_SCANNING` means nothing outside Docker, and setting it there
  turns nothing on) sends every uploaded file to a ClamAV daemon before
  it is stored: documents, new versions, meeting minutes and form templates.
  Scanning happens *after* the folder permission check, so an unauthorised
  caller can neither use it as a signature-set oracle nor tie the scanner up.
  When it is enabled it fails **closed**: if the scanner cannot be reached the
  upload is refused, because "is evidence scanned?" must not depend on whether
  the daemon happened to answer. There is deliberately no fail-open switch.
- **Supply chain:** Python dependencies are minimum versions on current,
  supported majors (Django held to the 5.2 LTS line), with no lock file or
  hashes, so an image built later can resolve newer releases; a published
  image keeps the versions it was built with. The frontend (React 19, React
  Router 7, Vite 8) is locked by `package-lock.json`, and CI fails on an
  `npm audit` finding of high severity or above. CI runs no vulnerability
  scan of the Python dependencies or the images; Dependabot proposes updates
  for both. Base images are referenced by tag, not by digest. CI runs on
  every push to main and on every pull request.
- **Containers:** the API, worker and beat run as an unprivileged `app` user
  (uid 10001), which owns the application code as well as the paths it
  writes. The web container is the stock nginx image, whose master process
  runs as root and whose workers run as `nginx`. The shipped compose file
  sets no read-only root filesystem, dropped capabilities,
  `no-new-privileges` or resource limits on any service; add them in an
  override if your baseline requires them. Healthchecks, API bound to
  loopback and fronted by nginx, secret key generated and persisted on first
  boot, DEBUG off by default, demo data removable with one command.

## Findings fixed in the 0.2.0 review

Severity uses the usual scale (High: exploitable for data loss/escalation or
denial of service; Medium: meaningful weakening of a control; Low: hardening).
The full method and evidence are in [REVIEWS.md](REVIEWS.md).

| # | Severity | Issue | Fix |
|---|----------|-------|-----|
| 1 | High | A folder could be moved under one of its own descendants, creating a parent cycle; `Folder.ancestors()` then looped forever inside every access check: one PATCH from any user with edit on a folder hung the API. | Cycle rejected at validation; ancestor walk bounded; corrupted chains raise instead of spinning. |
| 2 | High | Re-parenting a folder required only *edit* on the folder itself, so a user could move a subtree under a folder they could not see, exposing it to everyone granted on the destination's ancestors. | Moving requires *manage* on the folder and *edit* on the destination; top-level moves require the folders capability; generated framework folders cannot be moved, renamed or deleted. |
| 3 | High | Refresh tokens were neither rotated nor revocable: a stolen refresh token minted access tokens for its full 7-day life, and sign-out was client-side only. | Rotation + blacklist on every refresh; server-side logout endpoint; weekly blacklist pruning. |
| 4 | Medium | Throttle counters lived in a per-process local-memory cache, so with 3 gunicorn workers the login limit was effectively 24/min per worker set, and nothing was shared between containers. | Redis-backed cache when `CACHE_URL` is set (compose sets it). |
| 5 | Medium | A document's owner could delete it with only *view* on the folder ("owners may always edit their own"), letting a control owner remove their own evidence trail. | Delete requires *manage* on the folder; ownership still grants edit. |
| 6 | Medium | No application-level upload limit or type check: the dev server, admin and any direct-to-gunicorn deployment accepted unbounded uploads and stored `.html`/`.svg`/`.exe` as evidence. | Size ceiling and blocked-extension list enforced in serializers for every upload path; `/media/` sandboxed by CSP. |
| 7 | Medium | Authentication events were not in the audit trail, and mutation entries recorded only the path: an auditor could not tell that a failed brute-force ran or which fields of a user were changed. | Login/failed-login/logout events with reason and IP; mutation entries carry changed field names (never values) and created ids. |
| 8 | Medium | The Docker quickstart and both installers' Docker path ran the stack in DEBUG with the published placeholder key (and 0.1.1's guard only fires with DEBUG off). | Compose defaults to DEBUG off with an auto-generated persisted key; installers write a production-style `.env`; the container refuses placeholder keys off DEBUG. |
| 9 | Medium | The API and admin were published on `0.0.0.0:8000` alongside nginx, exposing the browsable API and admin login directly on the LAN. | Port bound to `127.0.0.1`; admin proxied through nginx; browsable API disabled in production. |
| 10 | Low | Built-in role capability flags could be rewritten through `PATCH /roles/{id}/` (e.g. giving *Viewer* `can_manage_users`). | Flags on `is_system` roles are locked; custom roles remain fully editable. |
| 11 | Low | An administrator who is not a superuser could reset a superuser's MFA. | Requires superuser. |
| 12 | Low | Folder names were not validated; `..`, separators and Windows-reserved characters reached the storage layer as path segments (a clean 400 from Django's storage, but a confusing failure at upload time rather than at creation). | Validated as a single path segment at creation and rename. |
| 13 | Low | `POST /notifications/dismiss/` accepted any key, allowing unbounded growth of the receipt table. | Key must be in the caller's live feed. |
| 14 | Low | The inline theme bootstrap in `index.html` prevented a `script-src 'self'` CSP, so the shipped nginx config left CSP commented out. | Bootstrap moved to `/theme-init.js`; CSP enabled by default. |
| 15 | Low | Password minimum of 8 characters is below PCI DSS v4.0.1 §8.3.6 (12). | Default 12 (`PASSWORD_MIN_LENGTH`). |
| 16 | Low | The container ran as root. | Unprivileged `app` user; writable paths owned by it. |
| 17 | High | **A development `.env` put the Docker stack into DEBUG.** Compose reads `./.env` for `${...}` substitution *and* into the containers, and that file is written by the *local* installer with `DJANGO_DEBUG=true` and a development signing key, so `./install.sh` followed by `docker compose up` produced a DEBUG container issuing tokens signed with the dev key, despite the compose default being `false`. Found by booting the stack and asserting `settings.DEBUG` inside it, not by reading the file. | Fixed: the stack reads `CONFORMITI_DEBUG` / `CONFORMITI_SECRET_KEY`, which a development `.env` never contains; validator check 16 fails the build if the old interpolation returns. |

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
- Access-review rows snapshot decisions server-side; a completed review is
  read-only and cannot be deleted, in the API and in the Django admin
  (tested).
- The Jira API token is write-only in the API and issue fetches are proxied
  server-side; base URLs must be `https` to a public host (tested). If the
  server's environment sets an egress proxy (`HTTPS_PROXY`) that does not
  exclude the Jira host, host names go to the proxy unresolved: the
  public-address check and the address pin apply only when no proxy is in
  use (a literal private address is still refused). The proxy is then what
  keeps a tenant administrator's Jira URL off your internal network, so
  configure it to refuse private destinations. The same holds for the chat
  webhooks (whose host allow-list still applies) and the OpenID Connect
  provider's endpoints.
- Document/folder object permissions enforce view/edit/manage with inheritance;
  querysets are filtered to visible folders (tested for list, detail, tree,
  evidence links, calendar feed and analytics).
- Request handling uses the ORM throughout. The only hand-written SQL is the
  health check's `SELECT 1` and the field-encryption migration helpers, which
  build their statements from fixed table and column names quoted by the
  database backend and pass every value as a parameter.
- MFA is opt-in and safe by construction: the device is enabled only after a
  code is confirmed; enrolling a factor, disabling one or regenerating codes
  asks for the password, a code from the authenticator app or a backup code
  (an account with neither a password nor a factor, such as one provisioned
  by single sign-on, may make its first enrolment without one); backup
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
  shipped nginx serves. `AUTH_TRANSPORT=header` restores the 0.2.x to 0.6.0
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
  Encryption at rest defends against a stolen database dump on its own, not
  against an attacker who also has the application's key. `scripts/backup.sh`
  writes `secrets.tgz` (the field-encryption key ring, the Django secret key
  and the package-signing key) into the same directory as `db.sql.gz`, and
  the bare-metal list in INSTALL.md backs the key files up with the database
  too, so whoever holds a backup made that way can decrypt the encrypted
  columns, sign packages and mint sign-in tokens. Keep the keys apart from
  the rest, or encrypt the backup, if you need that separation. If the key
  ring is derived from `DJANGO_SECRET_KEY`, one secret protects both, and
  changing that key without moving the ring first makes enrolled
  authenticators unreadable
  ([INSTALL.md](INSTALL.md#backups-on-bare-metal) shows the move). Keep them
  separate for a stronger separation, and use a secrets manager if your
  threat model needs it.
  It also does not stop an attacker who can *write* to the database: the read
  path deliberately accepts legacy plaintext so an upgrade cannot lock you out.
- **Back up the encryption key with the database.** Without it, enrolled
  authenticators cannot be read. That degrades safely rather than dangerously:
  the secret is never destroyed, MFA is still demanded at login, no
  authenticator code is accepted while its secret cannot be read (before
  0.9.5mb the unreadable secret acted as an empty key, whose codes anyone can
  compute), users can sign in with their (deliberately unencrypted)
  single-use backup codes, and an
  administrator can reset a user's enrollment. Restoring the key restores the
  secrets. A saved Jira token and each workspace's Slack and Teams webhook
  URLs would have to be re-entered.
- **An evidence package is a deliberate, narrow disclosure, and one of two
  places folder permissions are bypassed (the other is an assignee's view of
  a PBC request, below).** A live grant on a sealed package lets its auditor
  read exactly the artefacts pinned into it, and nothing else
  through that grant (what the Auditor role reads without one is in its own
  item below). That bypass lives in one module (`attestations/access.py`)
  so it can be reviewed in one sitting. Packaging cannot launder access: a
  document can only be pinned by someone who could already see its folder.
  Grants are per user (never per role), time-boxed, revocable in one click,
  and re-evaluated on every request, so deactivating or demoting the account
  closes it immediately.
  Every file that leaves is recorded before it leaves. The Django admin shows
  a package, its rows, its pinned evidence and its grants read-only.
- **The Auditor role reads two things without a package grant, by
  decision.** Any active account whose role is an auditor role can read
  every access-review snapshot of its workspace (each account's username,
  name, email, job title, role, last sign-in, capabilities and folder
  grants) and the whole audit trail (every person's actions and their
  details, which include the names of downloaded documents, and the IP
  address recorded with each entry), whether or not a package is issued to
  it. An access review is an audit artefact and the trail is what an auditor
  is there to read; [REVIEWS.md](REVIEWS.md) records the reasoning. Folder
  permissions given to the Auditor role, or to the auditor's own account,
  are ordinary folder grants: they do not expire with the engagement, are
  not withdrawn with a package grant, and a grant to the role reaches every
  account that holds it. Issue one auditor account per engagement, keep its
  folder grants narrow, and deactivate it when the engagement ends.
- **A sealed package is signed, and the signature is only as good as the
  key.** Since 0.7.0 every manifest is signed (Ed25519, detached). The
  installation's key lives in a file (`SIGNING_KEY_FILE`, 0600, in the
  `secrets` volume) or the environment, never in the database, so a database
  dump or a SQL injection yields the evidence and every digest but not the
  key; a backup made with `scripts/backup.sh` does include it, in
  `secrets.tgz`. Each workspace signs with its own key, derived from the
  installation key and the workspace's slug, so that one file protects every
  organisation's signatures and whoever holds it can sign for any of them;
  a rotation changes every workspace's key, and changing a workspace's slug
  changes its signing identity. The public keys are published
  (`/api/signing-keys/`, Settings › About), the bundle carries its own, and
  the shipped `verify.py` checks the signature with the standard library
  alone. `/api/signing-keys/` is unauthenticated on purpose, so a bundle can
  be checked without an account; with several organisations it asks for
  `?workspace=<slug>`, and it still tells an organisation that has signed
  something apart from one that has not. The `signing` block of
  `/api/health/` names the key that signs an organisation's packages when the
  installation serves one, and none (`per_workspace`) when it serves several;
  Settings › About shows the key of the workspace you are signed in to. Until
  0.9.5mb both showed the installation key, which signs nothing sealed inside
  a workspace. What the signature
  proves: the manifest was signed by whoever held the key at sealing. What
  it cannot prove: that the key was never copied. Protect the secrets
  volume as you would the Django secret key, rotate with
  `manage.py rotate_signing_key` if in doubt (old packages keep verifying
  under the key they carry), and keep publishing the digest out of band;
  the `seal` entry in the audit trail is the other half of the binding. A
  package sealed with no key configured is unsigned, and every screen and
  the bundle's README say so.
- **An SSO login still rests on the identity provider.** Step-up asks for a
  local authenticator only when one is enrolled (or, with
  `SSO_STEP_UP=required`, refuses otherwise); a person with no local
  authenticator is as strong as the provider's assertion. A compromised
  provider or tenant administrator can sign in as any non-privileged account
  of the workspace single sign-on serves (`SSO_WORKSPACE`) whose email
  address it asserts: with `OIDC_LINK_BY_EMAIL` and `SAML_LINK_BY_EMAIL` on,
  which is the default, an account not yet linked is linked on that first
  sign-in, and with auto-provisioning on it can create new ones. Set both to
  false to link only through `manage.py link_oidc_identity`. SAML carries no
  verified-email flag, so an address in a signed assertion is taken as
  verified. Superusers, staff and accounts whose role manages users are never
  linked by email, and the provider cannot be changed from inside the app.
  SAML requests are not signed (responses are).
- **A passkey is not the only way into a passkey-only account.** Enrolling
  the first second factor, passkey or authenticator app, issues ten
  single-use backup codes; they belong to the account rather than to any one
  factor, and any unused one signs in in place of the passkey. A person whose
  single passkey is lost or flagged as cloned signs in with a backup code, a
  second key or the authenticator app, or needs an administrator's reset,
  which also ends their sessions. The settings screen says so before they
  rely on one key.
- **The questionnaire link is a bearer credential.** Whoever holds an open
  link can read the twelve questions, the vendor's own draft, the vendor's
  and your organisation's names, the sender's name, the address it was sent
  to, the covering message, the expiry and the respondent's name, and submit
  once, and nothing else; a link that is no longer open shows only its
  state. It is 32 random bytes, stored only as a hash, expires (14 days by
  default, 90 at most), is superseded by the next send, and can be
  withdrawn; the public endpoints have their own rate limit. It goes out by
  email, so it is as private as the vendor's mailbox. It also travels in the
  URL path (`/questionnaire/<token>` and `/api/questionnaire/<token>/`), so
  the access logs of the shipped nginx and gunicorn record it in full for as
  long as the link is live: treat those logs as holding live links, or mask
  the path in your log format.
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
- **The spreadsheet importers are not scanned.** `POST /api/risks/import/` and
  a vendor's responsibility-matrix import
  (`POST /api/vendors/<id>/matrix/parse/`) read the uploaded file with
  `upload.read()` and never write it to storage, so there is nothing to serve
  back. Both need the frameworks capability and go through the same parser,
  bounded by a 2 MB cap, a zip-bomb guard and stdlib XML parsing. Stated here
  rather than silently skipped.
- **The user directory is readable by every signed-in member of the same
  workspace** (`GET /api/users/`), because owner and assignee pickers need
  it. Each row carries the username, name, email, job title, role and
  capabilities, whether the account is active, whether it is a superuser,
  whether it has a second factor, and its last sign-in: enough to pick out
  the administrators who have no second factor. An external auditor is
  refused the list, but reads the same names and addresses in access-review
  snapshots and the audit trail. Since 0.9.0 the list stops at the workspace
  boundary; within one organisation it is the whole directory.
- **`DJANGO_DEBUG` still defaults to true for the *local developer* path** so
  a first `./install.sh` is friction-free (the installer writes a random key
  and binds the development server to 127.0.0.1). The Docker stack and the
  published image default to off. Never let a reachable server run with
  DEBUG on: the secret-key guard does not run, so with no key set, or with
  the placeholder from `.env.example`, the tokens are signed with a key
  published in this repository and anyone can mint one; uploaded files are
  served at `/media/` with no access check and no audit row; and the
  browsable API and Django session authentication are on for every API
  route.
- **The Django secret key signs every session token.** Access and refresh
  tokens are HS256 JWTs signed with `DJANGO_SECRET_KEY` (in the Docker
  stack, the key generated into the `secrets` volume); there is no separate
  signing key. Anyone who reads it (the `secrets` volume, the environment,
  or a backup of either, `secrets.tgz` included) can mint a token for any
  account, a superuser included, without its password or second factor.
  Protect it at least as well as the package-signing key. Changing it signs
  everyone out, and if the field-encryption ring is derived from it, move
  the ring first ([INSTALL.md](INSTALL.md#backups-on-bare-metal) shows the
  move).
- **`/api/health/` answers anyone.** It is unauthenticated and unthrottled
  so container healthchecks and load balancers can poll it, and the sign-in
  page reads it for its demo-account and first-administrator notices. It
  reports the exact version, whether the database answers, whether the demo
  accounts are still active, whether any account can sign in yet, whether
  malware scanning is on and reachable, and the installation signing key's
  id and fingerprint; its first call also creates the signing key file when
  none exists. Refuse it to outside callers at your reverse proxy if that
  disclosure matters more to you than those notices.
- **No third-party penetration test has been performed.** The reviews in this
  document were code-level reviews with automated tests; a professional
  assessment is recommended before hosting regulated data.

## Production checklist

1. Bare metal: `DJANGO_DEBUG=false` and a strong unique `DJANGO_SECRET_KEY`
   (or `DJANGO_SECRET_KEY_FILE` on a persistent volume). Docker: nothing to
   set, because the stack ignores all three in `.env` on purpose: DEBUG is
   off and the key is generated into the `secrets` volume (override them
   only with `CONFORMITI_DEBUG` and `CONFORMITI_SECRET_KEY`).
2. Set `DJANGO_ALLOWED_HOSTS` (your public host name(s); the Docker stack
   adds its own internal names itself), `CORS_ALLOWED_ORIGINS` and
   `CSRF_TRUSTED_ORIGINS` to your real origins. Set `PUBLIC_URL` to the
   address people outside reach you at: questionnaire links, digests and
   chat posts are built from it, and sending a questionnaire is refused
   until it is set.
3. Terminate TLS in front of nginx and set `BEHIND_TLS=true` and
   `NUM_PROXIES` to match; set `SECURE_HSTS_SECONDS` once HTTPS is stable.
4. Use PostgreSQL and Redis (compose provides both; without Docker, point
   `CACHE_URL` at Redis too) and a real `EMAIL_PROVIDER` so review reminders
   reach owners. On Docker, set `POSTGRES_PASSWORD` to a long random value
   and `REDIS_PASSWORD` (letters and digits) in `.env` before the first
   start: otherwise the stack uses the published database password
   `compliance`, which the database keeps from its first start (a later
   change in `.env` does not reach it), and a Redis with no password, which
   carries the job queue and the rate-limit counters. Neither service
   publishes a port, so only containers on the stack's network can reach
   them, but nothing else stands between them and anything you run there.
5. Create your own administrator (`createsuperuser` or `DJANGO_SUPERUSER_*`),
   then run `manage.py remove_demo_data`. Confirm `/api/health/` reports
   `"demo_accounts":false`.
6. Back up nightly and test a restore once: on Docker `scripts/backup.sh`
   (the database and the media, secrets and tree volumes); without Docker,
   the list in [INSTALL.md](INSTALL.md#backups-on-bare-metal), whose key
   files matter as much as the database.
7. Restrict who can reach `/admin/` (it is proxied through nginx; put it behind
   your reverse proxy's allow-list or VPN).
