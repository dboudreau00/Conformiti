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
- **0.6.1** — roll-forward (next year's package from last year's, with a
  year-over-year diff and a manifest that names its predecessor), backup
  codes owned by the account so passkey-only people have them, a watch on
  the malware scanner with re-scan and quarantine, and cookie transport as
  the default with `__Host-`/`__Secure-` prefixes.
- **0.7.0** — detached Ed25519 signatures over every sealed manifest, from a
  key kept in a file outside the database, with the public key published,
  a standard-library verifier in the bundle, and key rotation.
- **0.8.0** — Slack and Microsoft Teams by incoming webhook (sealed, issued
  and withdrawn packages, the auditor's requests and returns, returned
  questionnaires, scanner outages, quarantines, a daily summary) and a
  per-person daily or weekly digest of the tray by email.
- **0.9.0** — Workspaces: one installation serving several organisations,
  each seeing only its own; superuser switch, archive, per-workspace jobs
  and seeding.

## Next

| Item | Why |
|---|---|
| Per-workspace single sign-on | one IdP per organisation rather than one per installation (`SSO_WORKSPACE` today) |
| Workspace-scoped chat channels | a Slack/Teams webhook per organisation rather than one shared channel with a prefix |

## Later

- Automated evidence collection from cloud/SaaS (AWS, GitHub, Okta, Google
  Workspace) with continuous control tests — and, with it, pulling a
  provider's published responsibility matrix straight into the vendor record.
  Parked until there are accounts to test it against properly.
- Additional frameworks (NIST CSF 2.0, HIPAA, CIS Controls v8) as seed packs.
