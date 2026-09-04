# Roadmap

## Shipped

- **0.1.0** — runnable MVP: three control libraries, evidence tree, document
  lifecycle and reminders, risk register with CSV/XLSX import, access reviews,
  meetings, champion groups, Jira, MFA, audit trail, analytics, theming.
- **0.1.1** — Docker data-loss fix, TLS on the mailbox transport, seed
  integrity, accessibility of the shell.
- **0.2.0** — full security review with fixes (rotating/revocable tokens,
  auth audit events, folder-tree integrity, upload gates, hardened
  containers), 80-test suite and CI, production-safe one-command install,
  readiness history, controls export, current dependencies, and the redesigned
  interface with four theme packs.

## Next (0.3)

| Item | Why |
|---|---|
| **Cookie-based sessions** (`HttpOnly`, `SameSite`, CSRF) as an alternative to `localStorage` JWTs | removes the last XSS→token risk |
| **SSO** — OIDC first (Entra ID, Okta, Google), SAML after | every customer beyond a pilot asks for it |
| **WebAuthn / passkeys** as a second factor | phishing-resistant MFA |
| **Evidence virus scanning** (ClamAV sidecar) | uploads from untrusted users |
| **Per-control readiness scoring** (evidence freshness, owner, test date) instead of binary implemented/not | closer to what auditors actually ask |
| **End-to-end browser tests** in CI (Playwright) | the walkthrough in TESTING.md is manual today |
| **Field encryption** for TOTP secrets and the Jira token | defence in depth for the database |

## Later

- Automated evidence collection from cloud/SaaS (AWS, GitHub, Okta, Google
  Workspace) with continuous control tests.
- Vendor risk management (questionnaires, SOC report tracking).
- Slack/Teams notifications; digest emails.
- Formal attestations and auditor workspace with read-only export bundles.
- Additional frameworks (NIST CSF 2.0, HIPAA, CIS Controls v8) as seed packs.
- Multi-tenancy.
