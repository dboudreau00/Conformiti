# Changelog

All notable changes to Conformiti are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

---

## [0.9.0] — 2026-09-06

One installation, several organisations, each seeing only its own.

### Added

- **Workspaces.** Every organisation-owned row — frameworks and controls,
  folders and documents, risks, vendors, packages and their request lists,
  reviews, meetings, groups, calendar, Jira, readiness history, the audit
  trail, roles and people — belongs to a workspace, and every query is
  scoped to the one the signed-in person works in. Existing installations
  get a single workspace called *Default* holding everything they have;
  nothing changes for them.
- A superuser sees all workspaces under *Settings › Role & access*, creates
  new ones (with the built-in roles, and optionally the shipped framework
  library and folder spine), switches between them (`X-Workspace: <slug>`;
  the SPA remembers the choice) and archives one, which refuses its people
  at sign-in, ends their existing sessions and drops it out of every
  scheduled job. Nothing is deleted.
- `GET/POST /api/workspaces/`, `PATCH /api/workspaces/{id}/`,
  `GET /api/workspaces/current/`; `workspace` and `workspace_detail` on
  `/api/users/…`.
- Scheduled work runs once per workspace: review, vendor and auditor-request
  scans, the daily chat summary (now prefixed with the workspace name when
  there is more than one), readiness snapshots; digests are computed in the
  person's own workspace. `seed_frameworks`, `bootstrap_demo` and
  `remove_demo_data` take `--workspace <slug>`; `seed_frameworks --roles-only`.
- `SSO_WORKSPACE`: which workspace an auto-provisioned single-sign-on
  account joins (default `default`).

### Changed

- Names that were unique across the installation — role, framework key,
  vendor, meeting series, champion group, Jira board, readiness-snapshot
  date — are unique per workspace.
- The login audit entry is written into the account's workspace so its
  administrators can see it.
- An account with no workspace (a superuser created with `createsuperuser`)
  lands in the first active workspace; anyone else in that position is
  refused with 403.

### Upgrading

Ten migrations, one per app. Each adds the column, moves every row into the
Default workspace and then makes the column required, inside one
transaction on PostgreSQL. Budget a few seconds per hundred thousand rows.

---

## [0.8.0] — 2026-09-05

The tray only helps people who open the app. Now it reaches a channel, and
an inbox.

### Added

- **Slack and Microsoft Teams**, by incoming webhook. Set `SLACK_WEBHOOK_URL`
  and/or `TEAMS_WEBHOOK_URL` (https only, configured by an operator and
  nowhere else) and the moments that matter are posted: a package sealed,
  issued or withdrawn; the auditor raising a request or returning an answer;
  a vendor's questionnaire coming back; the malware scanner going quiet or
  recovering; a file quarantined; and a **daily summary** of what is
  outstanding across the workspace. Slack gets Block Kit, Teams an Adaptive
  Card, each with a link back when `PUBLIC_URL` is set. `NOTIFY_EVENTS`
  narrows the list. Posts leave the request on a thread and never block a
  seal on a chat outage; every attempt is recorded and the last few are
  shown to administrators under *Settings › Notifications*, beside a *Send
  a test message* button. Built on `urllib`; no dependency added.
- **Digest emails.** Each person chooses *Off*, *Daily* or *Weekly (Monday)*
  under *Settings › Notifications* and receives their own tray — the same
  items, minus what they dismissed, grouped by severity with links — after
  the morning scan. Nothing is sent when the tray is empty, and never more
  than once a day. `manage.py send_digests` for cron deployments.

---

## [0.7.0] — 2026-09-05

The signature the bundle was missing, with the key-management story that
was the reason for leaving it out.

### Added

- **Detached signatures over the sealed manifest.** Every seal signs
  `manifest.json` (Ed25519) with a key that lives in a **file, never in the
  database**: `SIGNING_KEY_FILE`, generated at 0600 on first use — in the
  compose stack inside the `secrets` volume beside the Django secret key —
  or the key itself in `SIGNING_KEY`. The bundle carries `manifest.sig` and
  `signing-key.pub`; `verify.py` now checks the signature with an Ed25519
  implementation of its own (RFC 8032, standard library only, tested
  against the RFC vectors and the `cryptography` library), and prints the
  key fingerprint to compare with the one the organisation published;
  `openssl pkeyutl` agrees, and the README in the bundle says how. The
  public key is published at `GET /api/signing-keys/` (current and retired,
  with dates) and under Settings › About; each package remembers the key
  that signed it, so a package sealed under a rotated-out key keeps
  verifying. `GET /api/evidence-packages/{id}/signature/` and the existing
  `verify` action report the signature's state; the seal entry in the audit
  trail names the key. `manage.py rotate_signing_key` writes a new key,
  keeps the old file beside it, and marks the old public key retired. With
  no key configured (`SIGNING_ENABLED=false`, or neither location set)
  packages seal unsigned exactly as before, and every screen and bundle
  says so.

### Changed

- The package screen shows "Signed · Ed25519 · key …" (or that the package
  carries no signature); the integrity check fails on a signature that
  does not verify, whatever the file digests say.

---

## [0.6.1] — 2026-09-05

The four items 0.6.0 left on the "next" list: next year's package from last
year's, backup codes that a passkey-only account holds too, a watch on the
malware scanner, and cookie transport as the default.

### Added

- **Roll-forward.** *Roll forward* on a sealed or withdrawn package opens
  next year's draft: the same engagement shape, the same controls
  re-snapshotted as they stand today with today's visible evidence pinned,
  and the old package recorded as the predecessor. Conclusions, samples and
  the request list stay with the year they were made in. Every package with
  a predecessor gets a **Year over year** panel — scope and controls in and
  out, evidence replaced (matched by document, compared by digest), last
  year's exceptions and whether this year has concluded them — computed from
  the two packages' own snapshots, so it works years later against sealed
  rows. `GET /api/evidence-packages/{id}/diff/`,
  `POST /api/evidence-packages/{id}/roll_forward/`; `prior_package` is
  writable on a draft (must be sealed, must not loop). **Manifest version 3**
  names the predecessor and its manifest digest, so a chain of engagements
  verifies end to end; older manifests are unchanged and still verify.
- **Backup codes belong to the account.** Enrolling a first passkey issues
  ten backup codes, shown once; a backup code satisfies the second step
  beside a passkey or the authenticator app, at sign-in and at the SSO
  step-up; *Regenerate backup codes* works for anyone with a second factor.
  Enabling the app after a passkey keeps the codes already held. Removing
  the last factor removes the codes. Existing codes carry over (migration
  `accounts 0006`).
- **Scanner monitoring.** `GET /api/health/` reports the malware scanner
  (`scanning`: enabled, reachable, latency, down since); an hourly task
  emails the compliance team once when clamd stops answering and once when
  it is back; administrators and managers see an outage in the tray, with
  the reminder that uploads are being refused meanwhile. `manage.py
  scan_evidence` re-scans stored files (`--stale 30` by default, `--all`,
  `--probe`, `--dry-run`) because signatures arrive after files do: a file
  that now matches is **quarantined** — kept on disk, refused on every route
  that serves bytes, badged in the document list, counted in the tray, and
  recorded in the audit trail; a later clean re-scan releases it. Uploads
  record their clean verdict; a new version resets it. Settings › About
  shows the scanner's state.

- **The Conformiti identity.** A shield split along its centreline with one
  check struck across it, in four colourways with fixed meanings: Governance
  Blue is the corporate mark (sidebar, sign-in, questionnaire, favicon,
  README); Assurance Green means controls passing; Risk Red is reserved for
  findings and alerts; Policy Purple stands for frameworks and attestations.
  Sources in `assets/brand/` and `frontend/src/brand.js`.

### Changed

- **Cookie transport is the default** (`AUTH_TRANSPORT=cookie`). Over https
  the access cookie is `__Host-conformiti_access` (Path=/), the refresh
  cookie `__Secure-conformiti_refresh` on its narrow path, and the CSRF
  cookie `__Host-csrftoken`; over plain http the plain names remain. Signing
  out also expires the pre-0.6.1 cookie names. **Upgrading signs everyone
  out once**; set `AUTH_TRANSPORT=header` to keep the old behaviour.

---

## [0.6.0] — 2026-09-05

The vendor answers their own questionnaire, passkeys as a second factor with
the clone detector done right, and the auditor's request list — the other
half of the workflow the audit package started.

### Added

- **Questionnaire sent to the vendor.** From the vendor's Questionnaire tab,
  *Send to the vendor* emails their contact a personal, time-boxed link (14
  days by default, 90 at most; a new link supersedes the open one). They
  answer the shipped twelve questions in their browser with no account, save
  a draft as often as they like, and submit once; the answers land as a
  **pending** questionnaire assessment, the owner and the sender are emailed,
  and the tray shows *Returned by …* until someone records the outcome. Only
  the token's hash is stored; the link is shown once to the sender and
  travels in the email. The public endpoints show the questions and the
  vendor's own draft, nothing else, on their own rate limit
  (`THROTTLE_QUESTIONNAIRE`). A link that expires unanswered is flagged to
  the owner. `PUBLIC_URL` and `ORGANISATION_NAME` shape the link and the email.
- **Passkeys and security keys (WebAuthn)** as a second factor, alone or
  beside the authenticator app: enrol from *Settings › Security*, sign in
  with *Use passkey* after the password (or, on single sign-on, at the
  step-up). ES256, RS256 and EdDSA keys; attestation is requested as `none`
  and never trusted; the relying party is the request's host unless
  `WEBAUTHN_RP_ID` / `WEBAUTHN_ORIGINS` pin it; `WEBAUTHN_USER_VERIFICATION`
  can demand a PIN or biometric. The protocol side (CBOR, COSE, both
  ceremonies) is in `accounts/webauthn.py` on the `cryptography` package the
  project already carried — no new dependency — and the test suite drives it
  with a fake authenticator for every algorithm. **The clone detector fails
  closed:** a signature counter that does not advance disables that key and
  refuses the sign-in, and the account keeps requiring a second factor; it is
  recovered with another passkey, the authenticator app, or an
  administrator's reset (which now removes passkeys too). Removing a key
  takes the account password, like turning off the authenticator app.
- **PBC request list** on every package: the lines the auditor has asked
  for ("prepared by client"), raised by the issued auditor from inside the
  package or transcribed by the organisation, each with a control, an
  assignee, a due date and a priority. The organisation answers by attaching
  documents (snapshotted with version and digest, like pinned evidence) and
  marking the line *provided*; the auditor *accepts* or *returns* it with a
  note. Reminders go to the assignee at the review lead-time windows and once
  when overdue, from the same daily scan as document reviews; the tray shows
  what each person owes, managers see the overdue and unowned lines, and the
  auditor sees how many answers await them. A control owner with no package
  access sees exactly the lines assigned to them and answers from there —
  the second, deliberate folder-permission bypass, documented beside the
  first in `attestations/access.py`. CSV export for the auditor's tracker.

### Changed

- The sign-in challenge (`POST /api/auth/token/` with the right password)
  now names the factors on offer (`factors`) and, when a passkey is among
  them, carries the WebAuthn options; the SSO redeem step does the same.
  `mfa_enabled` on a user now means "signing in takes a second factor" —
  authenticator app or passkey.
- `manage.py send_review_reminders` (and the daily Celery task) also chases
  PBC requests.

---

## [0.5.0] — 2026-09-05

Single sign-on for the providers that insist on SAML, a second factor that
travels with SSO, a PDF viewer that never runs the PDF, and one production
bug that had made every download through nginx fail since 0.3.0.

### Added

- **SAML 2.0 single sign-on** (SP-initiated; HTTP-Redirect out, signed
  HTTP-POST Response back). Configured **from the environment only**, like
  OIDC: the provider's signing certificate is the sole trust anchor, there
  is no metadata fetch. Every signature is verified against that certificate
  with asymmetric algorithms only, and **only the element the signature
  covers is read** — a Response carrying a second, unsigned assertion yields
  nothing from it (the wrapping attack). Issuer, audience, destination,
  recipient, `InResponseTo`, validity window with clock skew and bearer
  confirmation are all checked; an assertion id is accepted once, from a
  shared table. The flow state travels in a signed `SameSite=None; Secure`
  cookie, because the provider's POST back is cross-site. Identity-to-account
  rules are the OIDC rules (same code, same audit trail, same tickets):
  verified email links one account, never a privileged one; optional
  provisioning; domain allow-list. `GET /api/auth/saml/metadata/` gives the
  provider our SP metadata. 20 offline tests sign responses with a local
  certificate.
- **Step-up on single sign-on.** `SSO_STEP_UP`: `if_enrolled` (default) asks
  for the person's local authenticator code after an SSO sign-in in which the
  provider did not assert a second factor (OIDC `amr`/`acr`, SAML
  `AuthnContextClassRef` or `authnmethodsreferences`, against
  `SSO_MFA_ASSERTIONS`); `required` refuses a sign-in with neither;
  `off` trusts the provider. The ticket is redeemable only with the code,
  five wrong codes spend it, and the login screen carries the ticket in
  state, never in the URL.
- **PDFs are drawn by pdf.js**, in a worker shipped with this bundle, onto
  canvases in our own page: no frame, no plugin, no PDF JavaScript ever runs,
  and the headless browser the test suite drives renders them too. Zoom and
  paged loading for long documents.

### Fixed

- **Downloads and previews failed in the Docker stack.** nginx's internal
  media location appended `Content-Disposition: attachment` to the header the
  API had already set on the X-Accel path; a response with two
  Content-Disposition headers is refused by Chromium and Firefox, so every
  evidence download and preview through the SPA failed in production since
  0.3.0. The nginx header is gone; the API's stands. Found by the 0.4.0
  review pass, verified against nginx 1.31 and both browsers.
- Office preview: the decompressed-size gate trusted the zip header. A few
  kilobytes of valid, highly compressible XML could expand into a tree many
  times larger than the 40 MB ceiling suggested. Each part is now read in
  bounded chunks and refused when it exceeds 12 MB or 400,000 tags.
- Vendors: a statement typed for a control with no responsibility was
  silently dropped and reported saved; it is now refused, and the grid says
  which rows need a responsibility before Save is enabled. The walkthrough no
  longer declares itself finished after a skip; a vendor's website can be
  cleared.
- `remove_demo_data` now finds the demo vendors, documents and RACI rows
  even when the demo accounts were deleted by hand first, and removes the
  two role-wide folder grants the seeder makes.
- RACI rows created through the API now record who created them.
- signxml's DEBUG output (whole assertions) is silenced.

### Changed

- `signxml` and `lxml` are new dependencies (SAML signature verification);
  `pdfjs-dist` on the frontend.
- The page CSP gains `'wasm-unsafe-eval'` (pdf.js image decoders), `blob:`
  in `img-src` and `worker-src 'self'`.

### Upgrade notes

- Apply migrations (`accounts 0004`). Rebuild the images: the nginx change is
  the one that matters for every deployment, SAML or not.

---

## [0.4.1] — 2026-09-05

The Type II workpaper, and the two loose ends of the vendor story.

### Added

- **Sample items on a package control.** The organisation states each
  control's population (size, source, sampling method) and may list the items
  while the package is a draft; they are sealed into the manifest with the
  pinned artefact that supports each one (`manifest_version` 2). After
  sealing, the issued auditor adds their own selections and records **pass,
  exception or not tested** per item — an exception without a note is
  refused — plus a sampling note, all writable by the auditor alone, like the
  conclusions beside them. `GET/POST/PATCH/DELETE /api/package-samples/`;
  `sample_summary` and the rows on every package control; `samples.csv` and
  new population/sample columns in `controls.csv` in the export bundle; the
  bundle README says which items were sealed and which the auditor added.
  The demo package ships a population and three sampled items, one already
  an exception.
- **Responsibility matrix export in the vendor's own layout.** Confirming an
  import remembers the file's column layout on the vendor; **Export in their
  layout** writes the stated matrix back under their headers — X marks where
  their marks were, our labels in their prose column, statements in their
  statement columns, and any column we never understood left blank rather
  than guessed.
- **Bridge-letter reminder.** When a vendor's most recent SOC 2 report has
  lapsed with no newer report and no bridge letter on file, the notification
  tray tells the owner and the frameworks managers, deep-linked to the
  vendor's assurance tab, and the daily reminder run emails the owner and the
  compliance team **once per lapse**. A new **Bridge letter** assessment kind
  closes the gap when filed. `send_review_reminders` (and the Celery beat
  task) now run both scans.

### Fixed

- Packages page: the frameworks capability was read from the wrong shape of
  the `capabilities` object; it now matches the API.

---

## [0.4.0] — 2026-09-04

The release that brings **third parties** into the picture and lets people
**read evidence without downloading it**. Vendors get a register, the assurance
they have given, and a shared responsibility matrix that can be typed, prompted
or imported from whatever spreadsheet they sent; every control gets a RACI row
that knows when a vendor is the one doing the work; Word, Excel, PDF and image
evidence opens in the browser inside a wrapper that says what it is, what it
satisfies and what its digest is; and sign-in can be delegated to an OpenID
Connect provider, configured where an administrator cannot reach it.

### Added

- **Vendor risk management** (`vendors` app, `/vendors`). A register with
  tier, status, data handled, services in scope, relationship owner and a
  review cadence with an overdue clock. **Assurance on file** per vendor — SOC 2
  Type I/II, ISO 27001 certificate, PCI DSS AOC, penetration test, DPA,
  contract, a copy of their own responsibility matrix, or a **security
  questionnaire** answered in-app from a shipped 12-question set — each with
  period, issue and expiry dates, our conclusion and the filed document.
  Assurance posture (current / partial / expired / unsatisfactory / none) and a
  **risk rating that crosses tier with posture** are computed, never typed. A
  risk can name its vendor. `GET /api/vendors/summary/`; CSV exports of the
  register and of every matrix.
- **Shared responsibility matrix per vendor.** An in-browser grid over every
  control in scope — provider / customer / shared / not applicable, with a
  statement for each side. Three ways to fill it: type into the grid, be
  **walked through the unstated controls** one at a time, or **import the
  vendor's own CSV/XLSX**. The importer recognises columns and values in the
  layouts vendors actually send — an "AWS" column of X marks beside a
  "Customer" column, a prose "Responsibility" column, "Provider statement /
  Merchant statement", references written `Req 8.3.6`, `PCI DSS 8.3.6.` or
  `A5.15` — shows how every column was read, calls out every unmatched
  reference and unrecognised value for correction, and writes nothing until the
  person confirms.
- **Onboarding prompt.** A vendor with no responsibilities stated raises an
  alert in the notification tray for its owner and the frameworks managers,
  deep-linked to its matrix. Critical and high-tier vendors with under half the
  matrix stated, an assurance report expiring within 60 days, and a review
  falling overdue surface the same way.
- **RACI responsibility matrix** (`/responsibilities`). Responsible,
  Accountable, Consulted and Informed per control, for people *and* vendors.
  The control owner is the implied Accountable; a vendor whose matrix says it
  does or shares a control is the implied Responsible. **Exactly one
  Accountable per control** — the API refuses a second. Gaps are counted, and
  readiness scoring's *owner* signal now also accepts an explicit Accountable
  row. CSV export.
- **Open in browser.** PDFs and images (PNG, JPEG, GIF, WebP, BMP) stream
  inline after a magic-byte check — a `report.pdf` that starts with `<html` is
  refused. Word and Excel files are parsed on the server with the standard
  library into headings, runs, list items, tables and sheets, and rendered by
  the SPA from that vocabulary: **no HTML is ever produced from a file**, and no
  third-party viewer sees it. The wrapper shows version, status, folder, the
  controls the document satisfies, and a **SHA-256 computed in the browser from
  the bytes on screen**, which a reviewer can compare with the digest recorded
  in a sealed package. Reads are audited like downloads. Available from the
  Documents page, from a control's linked evidence, and — under the auditor's
  grant, through the package's own preview route — from an audit package.
- **Single sign-on (OpenID Connect).** Authorization code + PKCE against any
  OIDC provider (Okta, Entra ID, Google Workspace, Keycloak…), configured
  **from the environment only**. The 0.3.0 design was held back because a
  provider an administrator could register let them mint a superuser session;
  removing the settable provider is what this design changes. ID tokens are
  verified against the provider's JWKS (issuer, audience, expiry, nonce;
  asymmetric algorithms only). A verified email links exactly one existing
  account — never a superuser or staff account, which are linked only by the
  deliberate `manage.py link_oidc_identity --allow-privileged`. Optional
  auto-provisioning with a default role that is refused if it can manage users;
  optional email-domain allow-list; one-time, session-bound tickets hand the SPA
  its tokens in either transport; every outcome is in the audit trail. 22
  offline tests drive the whole flow against a local RSA key.
- Demo data: four vendors in the states above (a full matrix, a report about to
  lapse, a lapsed one tied to the seeded vendor risk, and a fresh onboarding
  with no matrix), a real PDF and PNG evidence file, and RACI rows.
  `remove_demo_data` retires all of it.
- End-to-end specs for vendors, the RACI matrix and the viewer; new README
  screenshots.

### Changed

- Notification tray links may carry a query string (`/vendors?vendor=…&tab=matrix`).
- `Risk` gains an optional `vendor` foreign key.
- `PyJWT` is a direct dependency (it was already installed through SimpleJWT).

### Upgrade notes

- Apply migrations: `accounts 0003`, `compliance 0004` and `0005`, `vendors
  0001`, `governance 0002`. Nothing else is required. SSO stays off until
  `OIDC_ISSUER`, `OIDC_CLIENT_ID` and `OIDC_CLIENT_SECRET` are all set; see
  `.env.example` and INSTALL.md.

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
- Base images: Python **3.14**, Node **26**, nginx **1.31**; the backend CI matrix
  now includes 3.14 so the image's runtime is a tested Python. GitHub Actions
  bumped to current majors. Backend floors pinned to the exact tested versions.
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
