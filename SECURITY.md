# Security

This document records the security audit performed on the platform, the fixes
applied, the hardening that ships by default, and the residual risks you should
weigh before a production deployment.

## Posture at a glance

- **Authentication:** JWT (SimpleJWT). 60-minute access tokens, 7-day refresh,
  both tunable via env. `last_login` is kept current for access-review accuracy.
- **Two-factor auth (optional, per user):** TOTP (RFC 6238) compatible with any
  authenticator app, enforced at login as a second step, with single-use backup
  codes and admin lockout-recovery. Implemented on the standard library and
  verified against the RFC 4226/6238 test vectors (validator check 13).
- **Authorization:** role-capability permission classes on every endpoint, plus
  object-level, inheritance-aware folder access for folders and documents.
- **Transport/headers:** TLS redirect, secure cookies, and HSTS engage
  automatically when `DJANGO_DEBUG=false`; `nosniff`, `X-Frame-Options: DENY`,
  and a referrer policy are always on (Django and nginx).
- **Abuse resistance:** the login endpoint is rate-limited per client; anonymous
  traffic is globally throttled.

## Findings fixed in this audit

| # | Severity | Issue | Fix |
|---|----------|-------|-----|
| 1 | High | `FolderPermissionViewSet` returned **all** folder-permission rows to any authenticated user, disclosing the whole access-control map. | Queryset now limited to folders the caller can manage (full access only for folder-managers / `view_all` / superuser). |
| 2 | High | The same viewset had **no manage-check on update**, so any user could `PATCH` a grant to raise their own access level or repoint it to themselves. | `perform_update` now requires manage rights on both the existing and any destination folder. |
| 3 | High | `CalendarEventViewSet` had no write authorization — a read-only Viewer or Auditor could create, edit, or delete anyone's calendar events. | Added `ManageCalendarOrReadOnly`: read for all, writes require `can_manage_documents`. |
| 4 | High | CSV access-review export wrote user-controlled fields (names, job titles, reviewer notes) verbatim, enabling **spreadsheet formula/CSV injection**. | Cells beginning with `= + - @`, tab, or CR are prefixed with a quote to neutralise them. |
| 5 | High | The Jira client followed HTTP redirects and only rejected private **IP literals**, so a redirect or an internal hostname could reach internal services (**SSRF**). | Redirects are refused; the host is DNS-resolved and every resolved IP must be public; https-only retained. |
| 6 | Medium | `SECRET_KEY` silently fell back to a shipped placeholder. | The app refuses to boot with the placeholder when `DEBUG` is off. |
| 7 | Medium | No production transport/cookie hardening. | Auto-on TLS redirect, `Secure`/`HttpOnly` cookies, `SECURE_PROXY_SSL_HEADER`, opt-in HSTS when `DEBUG` is off. |
| 8 | Medium | No brute-force protection on login. | Per-client scoped throttle on token obtain/refresh (`THROTTLE_LOGIN`, default 8/min) + global anon throttle. |
| 9 | Medium | nginx served uploaded `/media` inline, allowing **stored XSS** via an uploaded `.html`/`.svg`. | `/media` is served `Content-Disposition: attachment` with `nosniff`; security headers added site-wide. |
| 10 | Low | Admin-set user passwords bypassed the password validators. | `UserWriteSerializer` runs `validate_password` on create and update. |
| 11 | Low | `?days=` on the reviews endpoint could 500 on non-numeric input. | Parsed defensively and clamped. |
| 12 | Low | A document could be moved into a folder the user couldn't edit via bare `PATCH`. | Update now checks edit access on the destination folder, like the `move` action. |
| 13 | Low | Audit-log client IP took the most spoofable (leftmost) `X-Forwarded-For` hop. | Uses the proxy-appended (rightmost) hop. |

## Verified and already sound

- No serializer uses `fields = "__all__"`; `UserWriteSerializer` deliberately
  omits `is_superuser`/`is_staff`, so the API cannot mint a Django superuser.
- Self-service profile edits (`PATCH /users/me/`) can't change role or status.
- Access-review rows snapshot decisions server-side; completed reviews are
  read-only.
- The Jira API token is write-only in the API (never returned) and issue fetches
  are proxied server-side so the token never reaches the browser.
- Document/folder object permissions enforce view/edit/manage with inheritance;
  querysets are filtered to visible folders (no IDOR on list or detail).
- ORM is used throughout (no raw SQL / string-built queries).
- MFA is opt-in and safe by construction: the device is created disabled and
  only enabled after a code is confirmed (a half-finished setup never locks
  anyone out); disabling or regenerating codes is password-gated; login OTP
  attempts share the login rate-limit and enrollment has its own (`THROTTLE_MFA`);
  backup codes are stored only as hashes; and admins can reset a user's MFA.
- The audit trail viewer is read-only end to end: entries are written only
  by server-side middleware, the API is a ReadOnlyModelViewSet (no write
  methods exist), and access is gated to administrators, auditors, and
  view-all managers.
- The user-management API has lockout guards: no self-deletion or
  self-deactivation, no self-role-change, superusers untouchable by
  non-superusers and undeletable via the API, and no change may leave the
  organisation with zero active administrators.
- The risk-register importer is manager-only and defensive: 2 MB request cap,
  zip-bomb guard on .xlsx, 1000-row limit, stdlib XML parsing (no external
  entities), and length caps per field; the register CSV export reuses the
  formula-injection sanitiser.

## Residual risks to weigh for production

- **Tokens in `localStorage`.** The SPA stores JWTs in `localStorage`, the common
  SPA pattern, but it means any XSS can read a token. The CSP template in
  `frontend/nginx.conf` (commented) is the main mitigation — enable and tune it.
  For the highest assurance, move to `HttpOnly`, `SameSite` cookie auth with CSRF
  protection; that's an architectural change, not a config flag.
- **Refresh tokens are not rotated or blocklisted.** A stolen refresh token is
  valid until expiry. Consider enabling SimpleJWT rotation + blacklist for
  higher-risk deployments.
- **Jira token at rest.** It's stored in the application database in clear text
  (like most self-hosted integrations). Use a dedicated scoped token, restrict DB
  access, and consider a secrets manager or field encryption if your threat model
  requires it.
- **TOTP secrets are stored in the app database** (like the Jira token). They
  enable a second factor but aren't themselves encrypted at rest; restrict DB
  access and consider field encryption if your threat model requires it.
- **Passkeys (WebAuthn) and OAuth/SAML SSO are not yet implemented.** TOTP MFA
  covers the second-factor requirement today; WebAuthn and SSO are planned and
  called out in ROADMAP.md, deferred deliberately because they need audited
  libraries and browser/IdP integration testing rather than being shipped
  unverified.
- **Uploaded file contents are not scanned.** Files are stored and served as
  attachments (mitigating XSS) but are not virus/type-scanned. Add scanning if you
  accept files from untrusted users.
- **DEBUG defaults to true** for a friction-free first run. Production must set
  `DJANGO_DEBUG=false` (which also unlocks the transport hardening above) and a
  strong `DJANGO_SECRET_KEY`.

## Production checklist

1. `DJANGO_DEBUG=false` and a strong unique `DJANGO_SECRET_KEY`
   (`python -c "import secrets; print(secrets.token_urlsafe(50))"`).
2. Set `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS` to
   your real origins.
3. Terminate TLS; keep `SECURE_SSL_REDIRECT`/secure cookies on and set
   `SECURE_HSTS_SECONDS` once HTTPS is stable.
4. Enable the CSP header in `frontend/nginx.conf` and confirm the app loads.
5. Use Postgres, run behind the provided nginx, and restrict database and
   `/admin/` access.
