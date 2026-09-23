# Contributing

Thanks for helping make Conformiti better. This page is the short version of
how the project is built and what a change needs before it can merge.

## Set up

```bash
./install.sh --setup-only                                              # macOS / Linux / WSL
powershell -ExecutionPolicy Bypass -File .\install.ps1 -SetupOnly      # Windows
```

That creates `.venv`, installs backend and frontend dependencies, migrates a
SQLite database and seeds the control libraries; add `--demo` (`-Demo`) for
the sample organisation and its five accounts. Start the servers with
`./install.sh` (both) or by hand:

```bash
cd backend && ../.venv/bin/python manage.py runserver 127.0.0.1:8000
cd frontend && npm run dev            # http://localhost:5173
```

## Before you open a pull request

Run the same gates CI runs:

```bash
./install.sh --test
```

which is shorthand for these, except `npm audit`, which only CI runs:

```bash
python tools/validate.py                                   # static wiring/contract checks
cd backend && python manage.py check && python manage.py makemigrations --check --dry-run
cd backend && python manage.py test                        # the long one; ends with "Ran N tests" and OK
cd frontend && npm run build && npm audit --audit-level=high
```

Rules of thumb:

- **Migrations ship with the change.** Never run `makemigrations` on a server;
  commit the migration and CI verifies the graph is complete.
- **Every endpoint change comes with a test** in the app's `tests.py`
  (`backend/testutils.py` has the fixtures: roles, five personas, a small
  folder tree, upload helpers).
- **Permissions are enforced in the API, then mirrored in the UI.** A UI that
  hides a button is not a control; a serializer/permission class is.
- **No hard-coded colours in the frontend.** Use the tokens in
  `frontend/src/styles/index.css` (`text-ink`, `bg-surface`, `toneVar(...)`)
  so every theme pack keeps working.
- **Accessibility is not optional:** interactive elements are buttons or carry
  role + keyboard handlers; inputs have labels.
- **Control text is paraphrased.** Do not paste normative ISO/PCI text into the
  seed data: it is copyrighted.

## Project map

```
backend/            Django project (config/) + apps
  accounts/         users, roles, RBAC, MFA, logout, demo-data retirement
  compliance/       frameworks, controls, evidence links, seeding, CSV export
  documents/        folders, grants, documents, versions, upload validation
  governance/       risks (+ CSV/XLSX import), access reviews, meetings, groups
  notifications/    review-reminder scan, email transports, in-app feed
  audit/            audit-trail middleware, auth events, read-only API
  analytics/        dashboard summary + readiness snapshots
  calendar_app/     calendar events + merged feed
  integrations/     Jira client (SSRF-hardened)
  testutils.py      shared test fixtures
frontend/src/
  styles/index.css  theme tokens (4 theme packs, 4 accent packs) + Tailwind
  theme.js          theme/accent state, useTheme()
  components/ui     Panel, Badge, Button, Meter, SegmentedControl, StatCard
  components/charts Donut, BarChart, TrendLine
  components/layout Sidebar, TopBar, PanelTransition
  pages/            one file per route
tools/validate.py   dependency-free static validator (19 checks)
```

## Commit style

Short, imperative subject lines that describe the change ("Reject folder
parent cycles"), a body only when the *why* is not obvious. No generated-by or
co-authored-by trailers.

## Releases

Bump `backend/config/version.py`, `frontend/package.json` and both version
fields in `frontend/package-lock.json` (the top-level one and `packages[""]`,
by hand or with `npm install --package-lock-only` in `frontend/`), update the
README badge, add the CHANGELOG entry, tag `vX.Y.Z`, and publish a GitHub
release. `tools/validate.py` refuses a build where these disagree. CI must be
green.
