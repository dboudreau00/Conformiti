# SharePoint integration — specification

Status: **design / not yet implemented.** This spec is implementation-ready but
the integration itself needs network access and a Microsoft Entra app
registration to build and test, so it isn't wired into the running app yet
(the current build stays at "validated, 0 warnings"). Everything below is
scoped so it can be dropped into the existing `integrations` app the same way
the Jira connector was.

---

## 1. Goal

Let Conformiti work with evidence that lives in SharePoint Online:

1. **Connect** to a Microsoft 365 tenant by signing in (the user authenticates
   with their email at Microsoft's own page — see §3 on why this replaces a raw
   password form).
2. **Retain the session** so we don't re-prompt on every action — via the
   OAuth refresh token, persisted securely.
3. **Browse / link** SharePoint documents as evidence for controls (reusing the
   existing control ↔ evidence mapping).
4. **Generate viewer links scoped to specific email addresses** — a read-only
   link that only the named recipients can open, rather than an anonymous
   "anyone with the link" URL.

---

## 2. One correction up front: "email + password login"

SharePoint Online authentication runs through **Microsoft Entra ID** (formerly
Azure AD) using OAuth 2.0 / OpenID Connect. A raw email-and-password form that
signs into SharePoint on the user's behalf is **not a supported or safe option**:

- Microsoft has **deprecated legacy/basic auth** and the Resource Owner Password
  Credentials (ROPC) grant. MSAL still exposes `acquire_token_by_username_password`
  but explicitly marks it deprecated and unsuitable.
- A password form **breaks with MFA and Conditional Access**, which most tenants
  enforce — exactly the environments a compliance product targets.
- It would have us handling the user's Microsoft password directly, which is the
  thing OAuth exists to avoid.

**What "email login + retain the session" actually maps to** — and what this
spec uses:

> The **OAuth 2.0 authorization-code flow**. The user clicks "Connect
> SharePoint," we redirect them to Microsoft's sign-in page where they enter
> **their email** (and password + MFA, handled entirely by Microsoft). Microsoft
> redirects back with a short-lived code; we exchange it for an **access token**
> (≈1 h) plus a **refresh token**. The refresh token is the "retained session":
> we store it and silently mint new access tokens for months without prompting
> again.

This is the same pattern as the deferred OAuth SSO item in `ROADMAP.md`, and the
auth-code half is reusable if/when we add Microsoft SSO for platform login.

---

## 3. Authentication design

### 3.1 App registration (Microsoft Entra admin center)

One-time setup by a tenant admin:

- Register an application → note the **Application (client) ID** and **Directory
  (tenant) ID**.
- Add a **client secret** (or, better, a certificate) — stored server-side only.
- **Redirect URI** (web): `https://<our-host>/api/integrations/sharepoint/callback/`.
- **API permissions (Microsoft Graph, delegated)** with admin consent:
  `openid`, `profile`, `offline_access` (required for the refresh token),
  `User.Read`, `Sites.Read.All`, `Files.Read.All`, and — only if we create
  sharing links — `Sites.ReadWrite.All` / `Files.ReadWrite.All`.
- **Single-tenant** authority (`https://login.microsoftonline.com/<tenant-id>`)
  so only the customer's own directory can authenticate.

For tighter blast radius, prefer **`Sites.Selected`** (app permission, admin
grants access only to named sites) over the tenant-wide `Sites.Read.All` where
the customer's security team wants least privilege. That's a config choice; the
spec supports either.

### 3.2 Library

Use **MSAL for Python** (`msal`) for all token work — do not hand-roll OAuth.
Our Django backend is a **confidential client** (it can hold a secret), so:

```python
import msal

app = msal.ConfidentialClientApplication(
    client_id=conn.client_id,
    client_credential=conn.client_secret,           # from secret store
    authority=f"https://login.microsoftonline.com/{conn.tenant_id}",
    token_cache=load_cache(conn),                    # per-connection, persisted
)
```

Graph REST calls themselves can stay on the standard library (`urllib`), mirroring
the existing Jira client, since the host is the fixed `graph.microsoft.com`. So
the only new dependency is `msal`.

### 3.3 Connect flow (endpoints)

```
POST /api/integrations/sharepoint/connect/     (admin) → { auth_url }
GET  /api/integrations/sharepoint/callback/            → handles redirect, stores tokens
GET  /api/integrations/sharepoint/status/             → { connected, account_email, expires_at, scopes }
POST /api/integrations/sharepoint/disconnect/  (admin) → clears the connection + cache
```

1. **connect** → `flow = app.initiate_auth_code_flow(SCOPES, redirect_uri=...)`.
   Persist `flow` (state + PKCE verifier) keyed to the admin's session; return
   `flow["auth_uri"]`. Front end redirects the browser to it.
2. **callback** → `result = app.acquire_token_by_auth_code_flow(flow, request.GET)`.
   On success we have `access_token`, `id_token_claims` (incl. the signed-in
   **email / `preferred_username`**), and a refresh token now sitting in MSAL's
   cache. Persist the serialized cache (encrypted — §5) and the connected email.

### 3.4 Session retention

MSAL keeps the refresh token inside its `token_cache`; we persist that cache per
connection. On every Graph call:

```python
accounts = app.get_accounts()
result = app.acquire_token_silent(SCOPES, account=accounts[0])
if not result:                      # refresh token expired/revoked
    mark_connection_reauth_required(conn)
    raise SharePointReauthRequired()
save_cache(conn, app.token_cache)   # persist rotation
token = result["access_token"]
```

`acquire_token_silent` returns a cached access token or uses the refresh token to
get a fresh one automatically — no user interaction. Sessions therefore survive
app restarts and last until the refresh token's lifetime elapses or an admin
revokes consent, at which point `status` reports `reauth_required` and the UI
shows a "Reconnect" prompt.

---

## 4. Viewer links scoped to email (the core ask)

To share a SharePoint document as a **read-only link only specific people can
open**, Graph's `createLink` action is called with **`scope: "users"`** and a
**`recipients`** collection of email addresses:

```
POST https://graph.microsoft.com/v1.0/sites/{siteId}/drive/items/{itemId}/createLink
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "type": "view",                         // read-only
  "scope": "users",                       // NOT anonymous — named people only
  "recipients": [
    { "email": "auditor@external-firm.com" },
    { "email": "mia@customer.com" }
  ],
  "retainInheritedPermissions": false,
  "expirationDateTime": "2026-09-30T23:59:59Z"
}
```

The response is a `Permission` whose `link.webUrl` is the shareable viewer URL,
and whose `grantedToIdentitiesV2[].user.email` echoes back the recipients the
link is bound to. Anyone not on that list — even with the URL — is challenged
to sign in and denied. That is precisely "add the email to viewer links,"
done the secure way.

Notes and options:
- `type` can be `view` (read-only), `review`, `blocksDownload` (read-only, no
  download — good for sensitive evidence), or `edit`. Default here: `view`.
- `sendNotification: true` makes Graph email the link to the recipients directly;
  we'll default to **false** and surface the link in-app so the platform stays
  the system of record.
- Creating a link that grants access needs write scope
  (`Sites.ReadWrite.All` / `Files.ReadWrite.All`); read-only browsing needs only
  the `.Read.All` scopes.
- To **revoke**, delete the permission:
  `DELETE /sites/{siteId}/drive/items/{itemId}/permissions/{permId}`.

### 4.1 Two interpretations, both supported

- **Recipient scoping (primary):** the platform user picks who may view (e.g. the
  external auditor's email) and we bind the link to those addresses. This is the
  design above.
- **Requester attribution (optional):** also stamp the **signed-in user's email**
  (from the id-token) onto the stored link record and the audit log, so every
  generated link is traceable to who created it and for whom.

---

## 5. Data model (new, in the `integrations` app)

```
SharePointConnection            (singleton, pk=1, like JiraIntegration)
  tenant_id, client_id
  client_secret_encrypted       # Fernet/KMS-encrypted, write-only in API
  token_cache_encrypted         # serialized MSAL cache, encrypted at rest
  account_email                 # the connected user (from id-token)
  scopes, enabled
  status                        # connected | reauth_required | disconnected
  connected_at, updated_at

SharePointItemLink              # a SharePoint doc used as evidence
  control  FK -> compliance.Control        (nullable)
  document FK -> documents.Document         (nullable; for "SharePoint-backed" docs)
  site_id, drive_id, item_id                # Graph identifiers
  name, web_url, last_synced_at
  linked_by FK, created_at

SharePointViewerLink            # a generated email-scoped share link
  item_link FK -> SharePointItemLink
  permission_id                 # Graph permission id (for revocation)
  web_url                       # the viewer URL
  recipients                    # JSON list of emails the link is bound to
  link_type                     # view | blocksDownload | review
  expires_at, created_by FK, created_at, revoked_at
```

`SharePointItemLink` deliberately reuses the control ↔ evidence concept already
in the app, so SharePoint documents show up alongside uploaded evidence in the
Controls and Documents pages.

---

## 6. Feature endpoints (beyond auth in §3.3)

```
GET  /api/integrations/sharepoint/sites/?q=            # search sites the user can see
GET  /api/integrations/sharepoint/items/?site=&drive=&folder=   # browse a library
POST /api/integrations/sharepoint/link/                # attach an item as evidence
       { site_id, drive_id, item_id, control?, document? }
POST /api/integrations/sharepoint/viewer-link/         # mint an email-scoped link
       { item_link_id, recipients: [email...], type?, expires_at? }
POST /api/integrations/sharepoint/viewer-link/{id}/revoke/
GET  /api/integrations/sharepoint/viewer-links/?item_link=   # list/manage
```

All read endpoints require an authenticated platform user; **link creation and
viewer-link minting require `can_manage_documents`** (consistent with how
evidence and the calendar are gated). Every viewer-link creation and revocation
is written to the existing **audit log** with the recipients and the acting user.

---

## 7. Security considerations

Aligned with `SECURITY.md`; several of these are stronger than the current Jira
connector and we should backport them there.

- **Secrets encrypted at rest.** The client secret and the serialized MSAL token
  cache (which contains the refresh token) are encrypted with a key from env /
  a KMS (Fernet at minimum) — not stored in clear text. *This also fixes the
  documented "Jira token stored in clear text" residual risk if applied there.*
- **Least privilege.** Prefer `Sites.Selected` so the app can only touch sites an
  admin explicitly grants; request write scopes only if viewer-link creation is
  enabled. Read-only deployments never get write scopes.
- **Single-tenant authority** so only the customer directory can authenticate;
  validate the `tid` (tenant) and `aud` claims on the returned id-token.
- **CSRF / replay on the OAuth leg** handled by MSAL's `state` + PKCE + nonce via
  `initiate_auth_code_flow` / `acquire_token_by_auth_code_flow`; the redirect URI
  is allow-listed in Entra.
- **No anonymous links.** The API refuses `scope: "anonymous"`; only `users`
  (email-scoped) or, if explicitly enabled, `organization`. Viewer links default
  to an **expiry** (e.g. 30 days) and `blocksDownload` is offered for sensitive
  evidence.
- **Revocation path.** Deleting our record also deletes the Graph permission, so
  sharing is actually withdrawn, not just hidden.
- **Token handling.** Access tokens are used transiently and never logged;
  Graph calls go only to the fixed `graph.microsoft.com` host over TLS.
- **Reuse the login throttle / audit middleware** already in place.

---

## 8. Frontend UX

A new **SharePoint** page in the Governance nav, mirroring the Jira page:

- **Connection card** (admin): "Connect SharePoint" → redirects to Microsoft;
  once connected shows the **account email**, token expiry, granted scopes, and
  Reconnect / Disconnect. A `reauth_required` state shows a clear "Reconnect"
  banner.
- **Browse & link**: pick a site → library → file, and "Link as evidence" to a
  control (feeds the evidence-coverage metric already on the dashboard).
- **Share panel** on a linked item (and a "Share via SharePoint" action on
  documents): enter one or more recipient emails, choose read-only /
  no-download, set an expiry, and **Create link** → the email-scoped `webUrl` is
  shown to copy, with a list of who it's shared with and a Revoke button.

---

## 9. Phased plan & effort

| Phase | Scope | Est. |
|-------|-------|------|
| 1 | Entra app reg + auth-code connect/callback/status/disconnect + encrypted token cache + session retention | ~1 wk |
| 2 | Browse sites/drives/items + link SharePoint items as control evidence | ~1 wk |
| 3 | Email-scoped viewer links (create / list / revoke) + audit logging + UI share panel | ~1 wk |
| 4 | Hardening: `Sites.Selected`, expiry defaults, `blocksDownload`, re-auth UX, tests against a real tenant | ~0.5–1 wk |

**~3.5–4 weeks**, one engineer, in an environment with outbound network and a
test M365 tenant. New dependency: `msal` (plus a crypto lib for at-rest
encryption, e.g. `cryptography`'s Fernet).

---

## 10. Testing plan (must be live)

Because this talks to Microsoft, the real tests can't run in the current
offline/CI sandbox and need a test tenant:

1. Connect flow end-to-end, including an MFA-enabled account, and confirm the
   stored email matches the signer.
2. Kill the access token (wait or revoke) and confirm `acquire_token_silent`
   silently refreshes — the "retained session" guarantee.
3. Revoke admin consent and confirm the app degrades to `reauth_required`
   instead of erroring.
4. Create a `scope: users` view link, confirm a listed recipient can open it and
   a non-listed user is blocked; confirm expiry and revoke actually take effect.
5. Confirm read-only deployments (no write scopes) can browse/link but cannot
   mint share links.

What *can* be tested offline beforehand: request/response shapes against
recorded fixtures, the encryption round-trip for the token cache, permission
gating, and audit-log writes — following the same fixture-based approach used
for the risk importer and the MFA engine.

---

## 11. Open decisions

- **Delegated vs. app-only + `Sites.Selected`.** Delegated (a user connects)
  gives per-user identity and matches "email login"; app-only is better for
  unattended sync. Recommendation: delegated for v1 (this spec), optional
  app-only sync later.
- **Notifications.** Should an email-scoped link auto-email the recipient
  (`sendNotification: true`) or stay in-app only? Default in-app.
- **Backfill.** Do we mirror SharePoint files as local `Document` rows (with
  review cadences) or link out live? Spec links live and records metadata;
  cadence-tracked mirroring is a possible extension.
