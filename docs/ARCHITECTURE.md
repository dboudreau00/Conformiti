# Architecture

## Apps

| App | Responsibility |
|---|---|
| `accounts` | Custom `User`, `Role` (capability flags), RBAC permission classes, TOTP MFA + backup codes, passkeys (`webauthn.py` protocol + `passkeys.py` glue, `WebAuthnCredential`/`WebAuthnChallenge`), OIDC + SAML single sign-on, sign-out (token revocation), demo-data retirement, blacklist pruning task |
| `compliance` | `Framework`, `ControlCategory`, `Control`, `ControlMapping` (crosswalk), `ControlEvidence` (evidence ↔ control links), seed + on-disk folder tree, controls CSV export, the read-only atlas of every control and its crosswalk themes (`GET /api/controls/atlas/`) |
| `documents` | `Folder` (self-parent tree with cycle guard), `FolderPermission`, `Document` (+ scan verdict / quarantine), `DocumentVersion`, `FormTemplate`, upload validation, clamd client (`clamav.py`), scanning boundary (`scanning.py`) and the scanner watch + re-scan sweep (`monitor.py`, `manage.py scan_evidence`, `ScannerStatus`) |
| `governance` | `Risk` + `RiskNote` (+ CSV/XLSX importer), `AccessReview` + snapshot items, `MeetingSeries` + minutes, `ChampionGroup` + members |
| `vendors` | `Vendor` (tier, posture, computed risk rating), `VendorAssessment` (reports, AOCs, questionnaires, filed documents), `SharedResponsibility` (per-vendor matrix) + the CSV/XLSX recogniser (`matrix.py`), `QuestionnaireInvite` + the public token endpoints (`questionnaire.py`, `public_views.py`) |
| `attestations` | `EvidencePackage` → `PackageControl` → `PackageEvidence` / `PackageSample` snapshots, `PackageGrant` (the first of two folder-permission bypasses, `access.py`), manifest + bundle, `PbcRequest` / `PbcItem` (the auditor's request list, `pbc_views.py`; the second bypass, also in `access.py`), roll-forward + year-over-year diff (`rollforward.py`), detached Ed25519 signatures over the manifest and the bundle's `SHA256SUMS`, each workspace signing with a key derived from one installation key held in a file (`SIGNING_KEY_FILE`) or the environment (`SIGNING_KEY`), never in the database, + `SigningKey` registry of the public keys (`signing.py`, `manage.py rotate_signing_key`; `SIGNING_ENABLED=false` seals unsigned), stdlib verifier shipped in every bundle (`verifier.py`) |
| `notifications` | review/vendor/PBC reminder scans + scanner watch (Celery tasks / management commands), email transports (console, SMTP, mailbox, SES), derived per-user in-app feed + receipts, per-person digest emails (`send_digests`), Slack/Teams incoming webhooks with a delivery log (`webhooks.py`, `WebhookDelivery`) |
| `audit` | `AuditLog`, request middleware (mutations with field names), explicit auth events, read-only viewer API |
| `analytics` | dashboard summary endpoint (readiness, the evidence figures and each framework's counts, evidence linked and score), `ReadinessSnapshot` history + trend |
| `calendar_app` | `CalendarEvent` + merged review/audit/task feed |
| `integrations` | Jira client (https only, any public host, the resolved address checked and the connection pinned to it, redirects refused; through an egress proxy the proxy resolves and connects) |
| `config` | settings, URLs, health endpoint, version, CSV sanitiser, field encryption (`fieldcrypto.py`), and the one safe way to make an outbound request (`outbound.py`: host allow-lists, address checks, a pinned connection, refused redirects, proxies honoured) |

## Data model (essentials)

```
Framework 1─* ControlCategory 1─* Control *─* ControlMapping
                                     │ 1─* ControlEvidence *─1 Document
User(Role) ─owns→ Control / Folder / Document / Risk

Folder (self-parent tree; framework/category/control FKs on seeded nodes)
   │ 1─* Document 1─* DocumentVersion
   │        └─ owner, review_cadence, next_review_date, reminders_sent
   └─ FolderPermission (role|user → view/edit/manage, inherited downward)

Risk 1─* RiskNote                AccessReview 1─* AccessReviewItem (snapshot)
MeetingSeries 1─* MeetingMinute  ChampionGroup 1─* GroupMember
CalendarEvent → optional Document / Control / assignee
AuditLog → optional User          ReadinessSnapshot (one per day, per workspace)
NotificationReceipt (user, key)   User 1─1 MfaDevice, User 1─* MfaBackupCode,
                                  User 1─* WebAuthnCredential
JiraIntegration (one per workspace), JiraBoard
```

## Workspaces (multi-tenancy)

`accounts.Workspace` is the tenant. Every organisation-owned model inherits
`accounts.tenancy.TenantModel`: a `workspace` foreign key and a manager whose
querysets carry `WHERE workspace_id = <active>` whenever a workspace is
active. The active workspace is a context variable:

- `WorkspaceMiddleware` installs a per-request resolver that reads the
  workspace off the authenticated person the first time a tenant query
  runs (DRF authenticates inside the view, after middleware, so it has to
  be lazy). A superuser may name another workspace in `X-Workspace`. The
  variable is restored when the request ends.
- Tasks and commands activate one with `tenancy.scoped(ws)` and walk them
  all with `tenancy.for_each_workspace()`.
- A row saved without a workspace takes it from its declared parent
  (`tenant_parent = "folder"`) or from the active workspace, and refuses
  otherwise (`NoActiveWorkspace`).
- The filter is re-applied whenever a queryset is chained, so a queryset
  built at import time (`queryset = Model.objects.all()` on a viewset) is
  scoped the moment DRF calls `.all()`. Pinning never widens.
- No active workspace means no filter: right for migrations,
  `createsuperuser` and jobs that walk every workspace. A signed-in
  account with no workspace is refused (403). An unauthenticated request
  has no workspace either, so the endpoints that serve one (sign-in and
  refresh, single sign-on, the vendor questionnaire link, the published
  signing keys, health) run with no filter and confine themselves: sign-in
  to the account it authenticates, the questionnaire to the workspace of
  the invitation its token names, the signing keys to `?workspace=`, health
  to installation-level flags that name no tenant. `tenancy.unscoped()` is
  the explicit escape hatch.

Not tenant-scoped: `Workspace` itself, per-person authentication state
(passkeys and their challenges, TOTP, backup codes, SSO identities, issued
and revoked refresh tokens), the SAML replay record, the signing-key
registry (its workspace column is filtered explicitly), the scanner status
row, notification receipts and webhook deliveries. An audit entry for an
event that belongs to no workspace carries none and is shown to
superusers only.

## RBAC resolution

`Folder.effective_access(user)` returns the highest of:

1. `manage` if superuser or `role.can_manage_folders`
2. `view` if `role.can_view_all`
3. `manage` if the user owns the folder
4. the highest `FolderPermission` for the user or their role on this folder
   **or any ancestor** (inheritance)

An external auditor holds none of the role's capability flags, whatever the
role stores, so rules 1 and 2 never apply to one, and is then capped at
`view`. Documents inherit their folder's access; a document owner may edit
their own document (an external auditor never may), but deleting requires
`manage` on the folder. Restructuring the tree (re-parenting) requires
`manage` on the folder and `edit` on the destination; the generated framework
folders cannot be moved, renamed or deleted through the API.

Folder access is bypassed in exactly two places, both in
`attestations/access.py`. An external auditor with a live grant reads the
evidence pinned into the package issued to them. A package's request list,
with the documents attached in answer, is readable by whoever can read the
package and, for each line, by the person it is assigned to (an external
auditor reads it only through the grant). Evidence can be pinned or attached
only by someone who can already see its folder.

`documents.access.accessible_folder_ids(user)` resolves the same rules in a
handful of queries and scopes every folder and document list, the tree, the
calendar feed, the register's evidence counts and the dashboard's document
figures. The dashboard's control, evidence-coverage, risk and readiness
figures are organisation-wide counts that name nothing, shown to every
member of the workspace except an external auditor. The dashboard's coverage
atlas is a read of the control library instead, `GET /api/controls/atlas/`,
under the register's own permissions and workspace scope (an external auditor
is refused). It names controls, and its per-control score and band are the
caller's own, as the register shows them: the evidence behind a score counts
only the folders the caller can see, where the headline counts every folder.
It is one response in a fixed number of queries, however many controls there
are, with the crosswalk as themes listing control ids and every record keyed by
its numeric id, because a control reference is not unique across frameworks.

## Authentication

- `POST /api/auth/token/` checks the password first. An account with a
  second factor gets `{"mfa_required": true, "factors": {...}, "passkey"?: {...}}`
  until an `otp` (authenticator or backup code) or a `passkey` assertion is
  supplied; passkey challenges live in `WebAuthnChallenge` rows that answer
  once. Only then are an access token (60 min, `JWT_ACCESS_MINUTES`) and a
  refresh token (7 d, `JWT_REFRESH_DAYS`) minted.
- `AUTH_TRANSPORT=cookie` (the default) answers `{"authenticated": true}` and
  sets both tokens as HttpOnly, SameSite=Lax cookies, the refresh cookie only
  on `/api/auth/token/`, named `__Host-conformiti_access` and
  `__Secure-conformiti_refresh` when the cookies are Secure
  (`AUTH_COOKIE_SECURE`, which follows `BEHIND_TLS`). An unsafe request
  authenticated by the cookie, and the login, refresh and sign-out endpoints
  themselves, must carry Django's CSRF token. `AUTH_TRANSPORT=header` returns
  the tokens in the body for the client to send as `Authorization: Bearer`,
  which both modes accept.
- `POST /api/auth/token/refresh/` rotates the refresh token and blacklists the
  old one.
- The SPA signs out with `POST /api/auth/token/clear/`, which revokes every
  refresh token the account holds and expires the cookies; `POST
  /api/auth/logout/` blacklists the refresh token in its body. An access
  token already issued stays valid until it expires. A password change, a
  password set by an administrator and an MFA reset also refuse every access
  token issued before them (`sessions_valid_from`).
- Single sign-on (OIDC, SAML) ends in a one-time ticket redeemed at
  `POST /api/auth/oidc/redeem/`, with the same second-factor step.
- Session auth remains for the Django admin (which also asks for the second
  factor) and, in DEBUG, the browsable API.
- Login, failed login (with reason) and logout are audit events.

## Review-alert flow

```
Document.last_reviewed + cadence ─▶ next_review_date
        │
   daily scan at REVIEW_SCAN_HOUR (Celery beat), or cron: send_review_reminders
        │
   per document, the nearest lead in REVIEW_ALERT_LEAD_DAYS (30,14,7,1) it has
   newly entered (one email per document per run, to owner + compliance mailbox):
        └▶ email_service.send_templated_email()
              ├─ EMAIL_PROVIDER=ses     → boto3
              ├─ EMAIL_PROVIDER=mailbox → SMTP (+ IMAP Sent copy)
              ├─ EMAIL_PROVIDER=smtp    → Django SMTP backend
              └─ EMAIL_PROVIDER=console → stdout
        │
   claim lead in Document.reminders_sent before sending (dedupe; a failed send
   hands it back for the next run); overdue → one notice + status=expired
```

## Audit trail

`audit.middleware.AuditLogMiddleware` reads the top-level field names of a
JSON/form body *before* the view runs (values are never recorded; the names
password, current_password, new_password, api_token, otp, code and secret are
dropped), then, after an authenticated mutating request under `/api/` answers
below 400, writes `{user, action, object_type, object_id,
"METHOD /path fields=a,b", ip}`. `/api/auth/*`, `/api/notifications/*` and
`/api/health/` are excluded; sign-in, failed sign-in and sign-out, passkey
enrolment, removal and refusals, MFA resets, evidence downloads, package
reads and exports, and malware detections and quarantines are written
explicitly by `audit.events` and the scanner. Under `/admin/` the
middleware writes each change the Django admin saved (a POST it answered
with a redirect: an add, a change, a delete or a bulk action, with the field
names), and the admin's sign-in form writes its sign-ins and refusals. The
admin shows the trail, evidence packages and completed access reviews
read-only, and takes no uploaded file. The trail is read through `GET /api/audit-log/`
by administrators, view-all managers and the Auditor role, and that endpoint
has no write surface.

## Frontend

React 19 SPA (Vite 8). `App.jsx` mounts the shell and routes. The shell is
one sticky `TopBar` (`components/layout`): the Workspace tabs, a
`GovernanceMenu`, a `SearchPalette` opened by Ctrl K or Cmd K, an
`AppearanceMenu`, the notification bell and a `UserMenu`; a `SideMenu`; and,
under 768px, a `MobileMenu` sheet in place of the tabs and the side menu. The
bar, the side menu and the routes each sit in their own `ErrorBoundary`, so a
fault in the chrome leaves the page working. `ShellContext` carries the
signed-in user, health record and live badge counts.

`nav.js` is the one model of what a person may see. `navSections(me)` returns
the sections (the external auditor's reduced set included) and `shellNav(me)`
places them by section id when it renders: `workspace` into the tabs,
`governance` into the Governance menu, `account` into the account menu, and
every other section into the side menu, which is drawn only when it has items,
so a core installation and an external auditor have none. It reads section ids
and never a flag on the signed-in user, so an add-on that wraps `navSections`
and `NAV_LOOKUP` has its sections placed with no change in the core. The page
title and caption come from `NAV_LOOKUP` and are drawn by `PanelTransition` as
the page's `<h1>`.

Menus and popovers (Governance, Appearance, the bell, the account menu, the
phone sheet) are one primitive, `components/ui/Popover.jsx`: a press outside or
Escape closes, focus moves in and returns to the trigger, and menus take the
arrow keys. The palette searches only through the list endpoints the pages
themselves use (`/controls/`, `/documents/` and `/users/` with `?search=`). It
does not ask an external auditor for the two the API refuses, and a 403 from
either simply leaves that group out, so it never shows what the API would not.

The dashboard reads `/analytics/summary/` and the upcoming reviews, and
requests `/controls/atlas/` on its own, so a slow or refused atlas leaves the
rest of the page standing.

Every page is a `PanelTransition` panel built from the primitives in
`components/ui` and `components/charts`. Styling is Tailwind over the token
system in `styles/index.css`: a theme pack (`data-theme`) and an accent pack or
custom colour (`data-accent`) on `<html>`, applied before first paint by
`public/theme-init.js` and managed by `theme.js`. The axios client sends
`X-Workspace` when a superuser has chosen a workspace. In cookie mode (the
default) the browser carries the HttpOnly cookies and the client adds Django's
CSRF token to unsafe requests; in header mode it attaches the access token
from localStorage. Either way it refreshes once on a 401 (in header mode
storing the rotated refresh token) and revokes on sign-out.

## Deployment topology (compose)

```
browser ─▶ nginx (frontend, :8080) ─┬─▶ gunicorn (backend, :8000) ─┬─▶ PostgreSQL
                                    │        ▲                     └─▶ Redis (cache + broker)
                                    │        healthcheck /api/health/, and the host's
                                    │        127.0.0.1:8000 for debugging (skips nginx)
                                    ├─ /static from the shared volume; evidence only
                                    │   by X-Accel-Redirect from the API (internal
                                    │   /protected-media/), never by URL
                                    └─ CSP, security headers, 32 MB body cap
celery beat (the schedule) ─▶ Redis ─▶ celery worker ─▶ PostgreSQL / email
volumes: pgdata · media · static · secrets (the Django secret key, which also
         signs the tokens, the field-encryption key ring and the package-signing
         key; protect and back up as one) · tree · clamdb (scanning profile only)
```

Outbound connections are made by the API and the worker alike, and only to
what is configured: mail (SMTP, the mailbox account or SES), Slack and Teams
incoming webhooks, and clamd on port 3310 (the optional `scanning` profile).
The API alone calls Jira and the single sign-on provider. Webhook, Jira and
provider calls are HTTPS through `config/outbound.py`; mail and clamd are not.

Inside its container gunicorn listens on 0.0.0.0:8000 so nginx can reach it
over the compose network; the host publishes that port on 127.0.0.1 only
(`CONFORMITI_API_PORT` moves it), and a request sent there skips nginx's
headers and body cap.
