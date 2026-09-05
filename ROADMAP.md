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
- **0.4.0** — vendor risk management (register, assurance on file, security
  questionnaire, computed posture and rating), a per-vendor shared
  responsibility matrix that is typed, prompted or imported with column and
  value recognition, an onboarding prompt in the notification tray, a RACI
  responsibility matrix for people and vendors, in-browser viewing of PDF,
  image, Word and Excel evidence with a digest the reviewer can check, and
  single sign-on over OpenID Connect configured from the environment.
- **0.4.1** — sample items on a package control (population, sealed items,
  per-item pass/exception/not-tested by the auditor, `samples.csv` in the
  bundle), responsibility matrix export in the vendor's own layout, and a
  bridge-letter reminder when a SOC report lapses.

## Next (0.5.0)

| Item | Why |
|---|---|
| **SAML 2.0** single sign-on (SP-initiated, signed responses) | the providers that still insist on it; OIDC shipped in 0.4.0 |
| **Step-up on SSO logins** — a local TOTP prompt when the provider does not assert a second factor, or always when the operator says so | organisations that cannot enforce MFA at the IdP |
| **Vendor questionnaire sent to the vendor** — a time-boxed link like an audit package grant, answered by them, reviewed by us | 0.4.0 records the answers; the vendor should be able to give them |
| **WebAuthn / passkeys** as a second factor | phishing-resistant MFA. Deferred from 0.3.0: the design's clone detector disabled the passkey and dropped the account to password-only — a fail-open that has to be fixed before it ships |
| **PBC request list** with due-date reminders | the other half of the auditor's workflow |
| **Roll-forward**: a prior-package link and a year-over-year scope diff | the column already ships, nullable, so this needs no migration |
| **Scanner monitoring** — health probe, alerting, `manage.py scan_evidence` | 0.3.0 ships the boundary; this watches it |
| **Cookie transport as the default**, with `__Host-` cookie prefixes | once it has run in the field for a release |

## Later

- Detached signatures over a package manifest, once there is a key-management
  story worth the name — a signing key sitting in the same database as the
  evidence would be theatre.
- Automated evidence collection from cloud/SaaS (AWS, GitHub, Okta, Google
  Workspace) with continuous control tests — and, with it, pulling a
  provider's published responsibility matrix straight into the vendor record.
- Slack/Teams notifications; digest emails.
- Additional frameworks (NIST CSF 2.0, HIPAA, CIS Controls v8) as seed packs.
- Multi-tenancy.
