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
- **0.5.0** — SAML 2.0 single sign-on, step-up to a local authenticator on
  SSO logins, PDFs drawn by pdf.js instead of a plugin frame, and the fix for
  the duplicate Content-Disposition header that had broken every download
  through nginx since 0.3.0.
- **0.6.0** — the security questionnaire sent to the vendor to answer by a
  time-boxed link, passkeys / security keys (WebAuthn) as a second factor
  with a clone detector that fails closed, and the PBC request list with
  due-date reminders on every audit package.

## Next (0.6.1)

| Item | Why |
|---|---|
| **Roll-forward**: a prior-package link and a year-over-year scope diff | the column already ships, nullable, so this needs no migration |
| **Backup codes for passkey-only accounts** | today recovery is a second key, the authenticator app, or an administrator; codes belong to the TOTP device |
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
