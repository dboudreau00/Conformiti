# Validation

Conformiti ships with three layers of verification. All of them run in CI on
every push and can be run locally with one command:

```bash
./install.sh --test        # or: .\install.ps1 -Test
```

## 1. Static validator — `python tools/validate.py`

Dependency-free (stdlib only), so it runs on a bare checkout before anything
is installed. Exits non-zero on any error. 17 checks:

| # | Check |
|---|---|
| 1 | Every backend `.py` parses |
| 2 | App wiring: all 9 local apps installed and routed; every app with models ships `migrations/0001_initial.py`; **no install path runs `makemigrations`** |
| 3 | Every DRF ViewSet is registered in a router |
| 4 | JSX/JS structural validity (full tag-tree parse) |
| 5 | Shell wiring: every page imported and routed in `App.jsx`, every `nav.js` link has a Route and a title/caption, every page is a `PanelTransition` page |
| 6 | Every frontend API call (`api.*`, `fetchAll`, `downloadFile`) resolves to a registered backend route prefix |
| 7 | All frontend relative imports resolve |
| 8 | Theme system: four theme packs and four accent packs defined, every token present, retired `app.css` gone, no hard-coded colours in pages (warning) |
| 9 | Every third-party backend import is in `requirements.txt` |
| 10 | Deploy artifacts: compose contexts exist, `entrypoint.sh` present, every env key `settings.py` reads is documented in `.env.example` |
| 11 | Demo-data integrity: every control id the bootstrap references exists in the framework JSON |
| 12 | Risk-importer regression (inline fixture + `docs/sample-risk-import.csv`) |
| 13 | MFA engine against the RFC 4226 / 6238 test vectors |
| 14 | Review-reminder wiring: beat task → registered task, Celery app import, cron command, templates, provider branches, model fields |
| 15 | Tests + CI: every app has a `tests.py`, the CI workflow and `LICENSE` exist |
| 16 | Compose isolation: the Docker stack cannot inherit `DJANGO_DEBUG` or a signing key from a local development `.env` |

## 2. Backend test suite — `python manage.py test`

215 tests, ~3 min on SQLite (also run against PostgreSQL 16 in CI). Coverage by
theme:

- **Authentication:** token pair, bad password, inactive user, per-client
  throttle, health endpoint open and unthrottled, refresh rotation + blacklist,
  server-side logout, MFA enrollment → challenge → code/backup code → disable,
  RFC vectors, admin reset.
- **User administration:** read vs write gates, password validators on
  admin-set passwords, no API path to superuser/staff, self-lockout guards,
  last-administrator guard, superuser protection, profile-patch escalation,
  built-in role flag lock.
- **Folders and documents:** visibility and inheritance, mid-tree roots,
  auditor cap, ACL-map scoping, grant rules, parent cycles, corrupted chains,
  folder-name validation, seeded-folder immutability, move/delete rules,
  upload gates, owner edit vs delete, move destination checks, versions,
  mark-reviewed, review horizon, size ceiling, blocked extensions,
  unauthenticated access.
- **Controls and evidence:** read/patch gates, catalog immutability,
  visibility-scoped counts, link permissions and `can_unlink`, bulk attach
  skips, choices scoping, seed idempotence and documented counts, CSV export
  safety.
- **Governance:** access-review lifecycle, auditor read-only, completion rules,
  snapshot stability, CSV injection; risk permissions, closed_at bookkeeping,
  import/dedupe/warnings, malformed files, export safety, summary; meeting
  cadence, minute uploads, group membership.
- **Audit trail:** field-name capture, sensitive-key exclusion, failed/read
  requests not logged, notification state not logged, forwarded-IP handling,
  read-only API and gating.
- **Notifications:** per-user feed scoping, mark-read, dismiss validation;
  review scan windows, dedupe, overdue marking, reset on review, resilience to
  a failing send.
- **Calendar and analytics:** write gates, visibility-scoped feed, summary
  shape, daily snapshot, trend maths, `record_readiness`.
- **Deployment:** secret-key boot guard (placeholder, short, file-generated
  and stable across boots), full seed + demo bootstrap + `remove_demo_data`
  guard, Jira config gating and SSRF host rules.

## 3. Frontend and containers

- `npm run build` (Vite 7) must succeed; `npm audit --audit-level=high` must be
  clean.
- Both Docker images build; the API image boots standalone and answers
  `/api/health/` (SQLite, no services) — the same endpoint the compose
  healthchecks and the installers poll.

## What is still manual

- The end-to-end browser walkthrough in [TESTING.md](TESTING.md) (every
  route, two roles, light and dark packs). There are no browser-driven tests in
  CI yet.
- Real email delivery (`manage.py test_mailbox --to you@…`) and the Jira
  integration need real accounts.
- Load testing.
