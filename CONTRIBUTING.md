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
the sample organisation and its five accounts. Work on a branch from `main`,
the development line (installs follow release tags; contributions do not).

Start both servers with the installer:

```bash
./install.sh                                                     # macOS / Linux / WSL
powershell -ExecutionPolicy Bypass -File .\install.ps1           # Windows
```

or by hand, one terminal each, from the repository root:

```bash
cd backend && ../.venv/bin/python manage.py runserver 127.0.0.1:8000
cd frontend && npm run dev            # http://localhost:5173
```

```powershell
cd backend; ..\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
cd frontend; npm.cmd run dev          # http://localhost:5173
```

In Windows PowerShell use `npm.cmd`: a bare `npm` finds `npm.ps1`, which the
default execution policy refuses.

## Before you open a pull request

Run the same gates CI runs:

```bash
./install.sh --test                                              # macOS / Linux / WSL
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Test     # Windows
```

which is shorthand for these, except `node ../tools/jscheck.mjs src` (run from
`frontend/`) and `npm audit`, which only CI runs. Each block starts at the
repository root and runs top to bottom:

```bash
python3 tools/validate.py             # static wiring/contract checks; any bare Python 3.11+ will do
cd backend
../.venv/bin/python manage.py check
../.venv/bin/python manage.py makemigrations --check --dry-run
../.venv/bin/python manage.py test    # the long one; ends with "Ran N tests" and OK
cd ../frontend
npm run build
node ../tools/jscheck.mjs src         # every source file parses, no undeclared name
npm audit --omit=dev --audit-level=high   # the shipped dependencies; CI also reports the full audit
```

```powershell
.venv\Scripts\python.exe tools\validate.py
cd backend
..\.venv\Scripts\python.exe manage.py check
..\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
..\.venv\Scripts\python.exe manage.py test
cd ..\frontend
npm.cmd run build
node ..\tools\jscheck.mjs src
npm.cmd audit --audit-level=high
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
  role + keyboard handlers; inputs have labels. Menus and popovers are the one
  `Popover` in `components/ui`, which brings Esc, focus return and the arrow
  keys with it; do not write another.
- **A new page is wired in `nav.js`.** An entry in `NAV_SECTIONS` (its section
  decides where the shell draws it: the tabs, the Governance menu or the account
  menu) and one in `NAV_LOOKUP`, whose title and caption `PanelTransition` draws
  as the page's `<h1>`. Keep `navSections` a function and `NAV_LOOKUP` a plain
  object: an add-on extends both.
- **Control text is paraphrased.** Do not paste normative ISO/PCI text into the
  seed data: it is copyrighted.

## Project map

```
backend/            Django project (config/) + apps
  accounts/         users, roles, RBAC, workspaces (tenancy), MFA, passkeys,
                    OIDC and SAML sign-in, sessions, demo-data retirement
  compliance/       frameworks, controls, evidence links, seeding, CSV export
  documents/        folders, grants, documents, versions, upload validation
  governance/       risks (+ CSV/XLSX import), access reviews, meetings, groups
  attestations/     evidence packages, sealing, Ed25519 package signing,
                    PBC request lists, auditor grants
  vendors/          vendor register, assurance reports, responsibility matrix,
                    questionnaires (public endpoints keyed by a link token)
  notifications/    review, vendor and PBC reminder scans, digests, email
                    transports, Slack and Teams webhooks, in-app feed
  audit/            audit-trail middleware, auth events, read-only API
  analytics/        dashboard summary + readiness snapshots
  calendar_app/     calendar events + merged feed
  integrations/     Jira client (SSRF-hardened)
  config/           settings, field encryption, outbound request guard,
                    CSV formula safety, health endpoint
  testutils.py      shared test fixtures
frontend/src/
  styles/index.css  theme tokens (4 theme packs, 4 accent packs) + Tailwind
  theme.js          theme/accent state, useTheme()
  components/ui     Panel, Badge, Button, Meter, SegmentedControl, StatCard,
                    Popover (the one menu primitive)
  components/charts Donut, BarChart, TrendLine
  components/layout TopBar and its menus, SideMenu, MobileMenu, PanelTransition
  components/dashboard LeadSchedule, CoverageAtlas, NeedsAttention, calendar,
                    review queue
  pages/            one file per route
tools/validate.py   dependency-free static validator (20 checks)
```

## Commit style

Short, imperative subject lines that describe the change ("Reject folder
parent cycles"), a body only when the *why* is not obvious. No generated-by or
co-authored-by trailers.

## Releases

Bump `backend/config/version.py`, `frontend/package.json` and
`e2e/package.json`, and both version fields in `frontend/package-lock.json`
and in `e2e/package-lock.json` (the top-level one and `packages[""]`, by hand
or with `npm install --package-lock-only` in that directory), update the
README badge, add the CHANGELOG entry, tag `v` followed by the version exactly
as `version.py` writes it (for example `v0.9.5m`), and publish a GitHub
release. `tools/validate.py` refuses a build where these disagree. CI must be
green. Pushing the tag runs `.github/workflows/packages.yml`, which refuses a
tag that disagrees with `version.py` and publishes both images to ghcr.io
under the version, the commit and `latest`, with provenance and an SBOM.
