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
- **0.3.0** — audit packages (sealed, hash-pinned evidence issued to a named
  external auditor, with a self-verifying export bundle), per-control readiness
  scoring, field encryption for the TOTP secret and the Jira token,
  authenticated evidence downloads, optional ClamAV scanning, opt-in HttpOnly
  cookie authentication, and an end-to-end browser suite run against both
  transports in CI.

## Next (0.3.1)

| Item | Why |
|---|---|
| **Sample rows on a package item** (identifier, population reference, pass/fail, exception note) | the one thing between this and a Type II operating-effectiveness workpaper |
| **WebAuthn / passkeys** as a second factor | phishing-resistant MFA. Deferred from 0.3.0: the design's clone detector disabled the passkey and dropped the account to password-only — a fail-open that has to be fixed before it ships |
| **PBC request list** with due-date reminders | the other half of the auditor's workflow |
| **Roll-forward**: a prior-package link and a year-over-year scope diff | the column already ships, nullable, so this needs no migration |
| **Scanner monitoring** — health probe, alerting, `manage.py scan_evidence` | 0.3.0 ships the boundary; this watches it |
| **Cookie transport as the default**, with `__Host-` cookie prefixes | once it has run in the field for a release |

## Later

- **SSO — OIDC first (Entra ID, Okta, Google), SAML after.** Designed and
  deliberately held: the design let a non-superuser administrator register a
  provider they control, assert a superuser's email and receive a superuser
  session. Needs a redesign around provider trust, not a patch.
- Detached signatures over a package manifest, once there is a key-management
  story worth the name — a signing key sitting in the same database as the
  evidence would be theatre.
- Automated evidence collection from cloud/SaaS (AWS, GitHub, Okta, Google
  Workspace) with continuous control tests.
- Vendor risk management (questionnaires, SOC report tracking).
- Slack/Teams notifications; digest emails.
- Additional frameworks (NIST CSF 2.0, HIPAA, CIS Controls v8) as seed packs.
- Multi-tenancy.
