# Validation

Three layers, all of them run in CI on every push. Locally, one command runs
the validator, the backend suite and the frontend build:

```bash
./install.sh --test                                              # macOS / Linux / WSL
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Test     # Windows
```

## 1. Static validator: `python tools/validate.py`

Dependency-free (standard library only), so it runs on a bare checkout before
anything is installed. Exits non-zero on any error. Nineteen checks:

| # | Check |
|---|---|
| 1 | Every backend `.py` parses |
| 2 | App wiring: all 11 local apps installed and routed; every app with models ships `migrations/0001_initial.py`; **no install path runs `makemigrations`** |
| 3 | Every DRF ViewSet is registered in a router |
| 4 | JSX/JS structural validity (full tag-tree parse) |
| 5 | Shell wiring: every page imported and routed in `App.jsx`, every `nav.js` link has a Route and a title/caption, every page is a `PanelTransition` page |
| 6 | Every frontend API call (`api.*`, `fetchAll`, `downloadFile`) resolves to a registered backend route prefix |
| 7 | All frontend relative imports resolve |
| 8 | Theme system: four theme packs and four accent packs, every token present, no hard-coded colours in pages (warning) |
| 9 | Every third-party backend import is in `requirements.txt` |
| 10 | Deploy artifacts: compose contexts exist, `entrypoint.sh` present, every env key `settings.py` reads is documented in `.env.example` |
| 11 | Demo-data integrity: every control id the bootstrap references exists in the framework JSON |
| 12 | Risk-importer regression (inline fixture + `docs/sample-risk-import.csv`) |
| 13 | MFA engine against the RFC 4226 / 6238 test vectors |
| 14 | Review-reminder wiring: beat task → registered task, Celery app import, cron command, templates, provider branches, model fields |
| 15 | Tests + CI: every app has a `tests.py`, the CI workflow and `LICENSE` exist |
| 16 | Compose isolation: the Docker stack cannot inherit `DJANGO_DEBUG` or a signing key from a local development `.env` |
| 17 | Malware scanning: the clamd protocol cases, the EICAR fixture, and the upload limits agreed between clamd and nginx |
| 18 | Offsite assets: no page loads anything from a third party |
| 19 | Version lock: the same version in six places, `version.py`, `package.json`, both version fields in `package-lock.json` (the top-level one and `packages[""]`), the README badge and the changelog heading |

Check 15 counts the test functions in each app's `tests.py` only, so the
number it prints is smaller than the `Ran N tests` of the suite below. Both
are correct; they count different things.

## 2. Backend test suite: `python manage.py test`

Runs on SQLite by default; CI runs it on Python 3.11 to 3.14 and once more
against PostgreSQL 16. What it covers:

- **Tenancy.** ORM-level workspace scoping, the fail-loud unscoped read,
  `X-Workspace` ignored for everyone but a superuser, per-workspace seeding,
  signing keys and chat channels.
- **Authentication.** Token pair and rotation, blacklist on sign-out, cookie
  and header transports, per-client throttles, TOTP and backup codes spent
  once, WebAuthn against virtual authenticators, OIDC and SAML against locally
  signed assertions, step-up on SSO, admin reset.
- **Authorisation.** The external auditor's reachable surface, enumerated by
  walking the routers rather than by a hand-written list; folder inheritance,
  auditor cap, grant rules, self-lockout and last-administrator guards.
- **Documents and evidence.** Upload gates and blocked extensions, versions,
  review horizons, X-Accel serving, preview sniffing, malware quarantine.
- **Audit packages.** Sealing under a row lock, hash-pinned evidence, issue
  and withdrawal, PBC requests, samples, roll-forward, Ed25519 signatures
  against RFC 8032 vectors and the standalone verifier.
- **Governance.** Access reviews including applied revocations, risk import
  and export safety, meetings, RACI, vendors, questionnaires by link.
- **Notifications.** Reminder claims that cannot double-send or be lost,
  digests, and the outbound path: host allow-lists, address checks, refused
  redirects.
- **Deployment.** Secret-key boot guard, seed and demo bootstrap and
  retirement, field encryption and key rotation across every encrypted column.

## 3. Frontend and containers

- `npm run build` (Vite 8) must succeed; `npm audit --audit-level=high` clean.
- Both Docker images build; the API image boots standalone and answers
  `/api/health/`, the endpoint the compose healthchecks and installers poll.
- The compose job exercises the stack end to end: sign in through nginx,
  upload, download through X-Accel, back up, `down -v`, restore, and confirm
  the same bytes and the same signing key come back.
- The **Playwright suite**, run twice in CI, once per auth transport. See
  [e2e/README.md](e2e/README.md).

## Still manual

- The browser walkthrough in [TESTING.md](TESTING.md), for the things a
  scripted suite reads past: contrast in every theme pack, keyboard order,
  whether a message is actually intelligible.
- Real email delivery (`manage.py test_mailbox --to you@…`) and Jira, both of
  which need real accounts.
- Load testing.
