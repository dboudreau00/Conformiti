# Architecture

## Apps

| App | Responsibility |
|---|---|
| `accounts` | Custom `User`, `Role` (capability flags), RBAC permission classes, TOTP MFA + backup codes, passkeys (`webauthn.py` protocol + `passkeys.py` glue, `WebAuthnCredential`/`WebAuthnChallenge`), OIDC + SAML single sign-on, sign-out (token revocation), demo-data retirement, blacklist pruning task |
| `compliance` | `Framework`, `ControlCategory`, `Control`, `ControlMapping` (crosswalk), `ControlEvidence` (evidence ↔ control links), seed + on-disk folder tree, controls CSV export |
| `documents` | `Folder` (self-parent tree with cycle guard), `FolderPermission`, `Document` (+ scan verdict / quarantine), `DocumentVersion`, `FormTemplate`, upload validation, clamd client (`clamav.py`), scanning boundary (`scanning.py`) and the scanner watch + re-scan sweep (`monitor.py`, `manage.py scan_evidence`, `ScannerStatus`) |
| `governance` | `Risk` + `RiskNote` (+ CSV/XLSX importer), `AccessReview` + snapshot items, `MeetingSeries` + minutes, `ChampionGroup` + members |
| `vendors` | `Vendor` (tier, posture, computed risk rating), `VendorAssessment` (reports, AOCs, questionnaires, filed documents), `SharedResponsibility` (per-vendor matrix) + the CSV/XLSX recogniser (`matrix.py`), `QuestionnaireInvite` + the public token endpoints (`questionnaire.py`, `public_views.py`) |
| `attestations` | `EvidencePackage` → `PackageControl` → `PackageEvidence` / `PackageSample` snapshots, `PackageGrant` (the folder-permission bypass, `access.py`), manifest + bundle, `PbcRequest` / `PbcItem` (the auditor's request list, `pbc_views.py`), roll-forward + year-over-year diff (`rollforward.py`), detached Ed25519 manifest signatures from a file-held key + `SigningKey` registry (`signing.py`, `manage.py rotate_signing_key`), stdlib verifier shipped in every bundle (`verifier.py`) |
| `notifications` | review/vendor/PBC reminder scans + scanner watch (Celery tasks / management commands), email transports (console, SMTP, mailbox, SES), derived per-user in-app feed + receipts, per-person digest emails (`send_digests`), Slack/Teams incoming webhooks with a delivery log (`webhooks.py`, `WebhookDelivery`) |
| `audit` | `AuditLog`, request middleware (mutations with field names), explicit auth events, read-only viewer API |
| `analytics` | dashboard summary endpoint, `ReadinessSnapshot` history + trend |
| `calendar_app` | `CalendarEvent` + merged review/audit/task feed |
| `integrations` | Jira Cloud client (https-only, public-IP pinned, no redirects) |
| `config` | settings, URLs, health endpoint, version, CSV sanitiser |

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
AuditLog → optional User          ReadinessSnapshot (one per day)
NotificationReceipt (user, key)   MfaDevice 1─* MfaBackupCode
JiraIntegration (singleton), JiraBoard
```

## RBAC resolution

`Folder.effective_access(user)` returns the highest of:

1. `manage` if superuser or `role.can_manage_folders`
2. `view` if `role.can_view_all`
3. `manage` if the user owns the folder
4. the highest `FolderPermission` for the user or their role on this folder
   **or any ancestor** (inheritance)

Auditor roles are then capped at `view`. Documents inherit their folder's
access; a document owner may always *edit* their own document, but deleting
requires `manage` on the folder. Restructuring the tree (re-parenting) requires
`manage` on the folder and `edit` on the destination; the generated framework
folders are immutable through the API.

`documents.access.accessible_folder_ids(user)` resolves the same rules in a
handful of queries and scopes every list, tree, feed, evidence count and
analytics figure.

## Authentication

- `POST /api/auth/token/` → access (60 min) + refresh (7 d). Accounts with a
  second factor get `{"mfa_required": true, "factors": {...}, "passkey"?: {...}}`
  until an `otp` (authenticator/backup code) or a `passkey` assertion is
  supplied; passkey challenges live in `WebAuthnChallenge` rows that answer once.
- `POST /api/auth/token/refresh/` rotates the refresh token and blacklists the
  old one; `POST /api/auth/logout/` blacklists the current one.
- Session auth remains for the Django admin and (in DEBUG) the browsable API.
- Login, failed login (with reason) and logout are audit events.

## Review-alert flow

```
Document.last_reviewed + cadence ─▶ next_review_date
        │
   daily scan at REVIEW_SCAN_HOUR (Celery beat) — or cron: send_review_reminders
        │
   for each lead in REVIEW_ALERT_LEAD_DAYS (30,14,7,1) not yet sent:
        └▶ email_service.send_templated_email()
              ├─ EMAIL_PROVIDER=ses     → boto3
              ├─ EMAIL_PROVIDER=mailbox → SMTP (+ IMAP Sent copy)
              ├─ EMAIL_PROVIDER=smtp    → Django SMTP backend
              └─ EMAIL_PROVIDER=console → stdout
        │
   record lead in Document.reminders_sent  (dedupe); overdue → one notice + status=expired
```

## Audit trail

`audit.middleware.AuditLogMiddleware` reads the top-level field names of a
JSON/form body *before* the view runs (values are never recorded; password,
token and code keys are dropped), then, after a successful mutating response,
writes `{user, action, object_type, object_id, "METHOD /path fields=a,b", ip}`.
`/api/auth/*`, `/api/notifications/*` and `/api/health/` are excluded; auth
events are written explicitly by `audit.events`.

## Frontend

React 18 SPA (Vite 7). `App.jsx` mounts the shell (`Sidebar`, `TopBar`,
`ShellContext` with the signed-in user, health record and live badge counts)
and routes; every page is a `PanelTransition` panel built from the primitives
in `components/ui` and `components/charts`. Styling is Tailwind over the token
system in `styles/index.css`: a theme pack (`data-theme`) and an accent pack or
custom colour (`data-accent`) on `<html>`, applied before first paint by
`public/theme-init.js` and managed by `theme.js`. The axios client attaches the
access token, refreshes once on 401 (storing the rotated refresh token) and
revokes on sign-out.

## Deployment topology (compose)

```
browser ─▶ nginx (frontend, :8080) ─┬─▶ gunicorn (backend, 127.0.0.1:8000)  ─▶ PostgreSQL
                                     │        ▲  healthcheck /api/health/     └▶ Redis (cache + broker)
                                     ├─ /static, /media from shared volumes
                                     └─ CSP, security headers, 32 MB body cap
celery worker + beat (worker) ──────────────────────────────────────────────▶ Redis / PostgreSQL / email
volumes: pgdata · media · static · secrets (DJANGO_SECRET_KEY_FILE) · tree
```
