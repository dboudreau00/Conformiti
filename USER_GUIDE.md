# Conformiti — Installation & Usage Guide

This is the in-depth manual: what the platform is, how to install it three
different ways, every configuration key, and how to actually use each feature
day to day. If you just want the fast path, `GETTING_STARTED.md` compresses
install-and-verify into ~60 minutes; `TESTING.md` is the step-by-step
verification script. This guide goes deeper on both installation and usage.

---

# Part I — What you're running

## 1. Overview

The platform is a self-hosted compliance management system in the style of
Vanta: it tracks **security frameworks** (SOC 2, ISO 27001:2022, PCI DSS
v4.0.1 — 217 controls ship pre-loaded), the **evidence** that satisfies them,
the **documents** that need periodic review, the **risks** you're carrying,
and the **people and processes** (access reviews, governance meetings) that
auditors ask about. It is a Django 5 + DRF API with a React 18 single-page
app, backed by SQLite (local) or PostgreSQL (hosted).

## 2. Core concepts

**Framework → Category → Control.** A framework (e.g. SOC 2) contains
categories, which contain controls (e.g. `CC6.1`). Each control has a status
(implementing, implemented, etc.) and an evidence count.

**Documents and folders.** Documents (policies, procedures, exported logs)
live in folders. Folders are typically named for the control they evidence
(`CC6.1`), and folder-level permissions decide who can see what. Documents
carry a **review cadence** and a **next review date** — the engine that drives
reminders.

**Evidence links.** A many-to-many mapping between controls and documents.
One document can satisfy several controls across frameworks (an Access
Control Policy might cover SOC 2 `CC6.1`, ISO `A.5.15`, and PCI `7.1`); one
control can require several documents. Both directions are editable in the UI.

**Risks.** Register entries scored on a 5×5 **likelihood × impact** matrix.
The product (1–25) maps to a rating band: low, moderate, high, critical. Risks
have a status (open, mitigating, accepted, closed), a treatment, an owner, an
optional linked control and Jira key, a due date, and a note trail.

**Access reviews.** Point-in-time snapshots of every account, where an
administrator records a keep / modify / revoke decision per user — the
periodic user-access review that SOC 2 and ISO both expect.

**Audit trail.** Middleware writes an immutable log entry for every mutating
API call (who, what, which record, from which IP). Read-only by design.

**Notifications.** Two channels driven by the same underlying facts: an
in-app bell whose feed is computed per user from their ownership and role,
and email reminders for document reviews.

## 3. Roles and permissions

Five built-in roles. Capabilities are what actually gate the API; the table
shows what each role can do.

| Role | Manage users | Manage frameworks | Manage documents | Manage folders | View all | Auditor |
|---|---|---|---|---|---|---|
| Administrator | ✓ | ✓ | ✓ | ✓ | ✓ | – |
| Compliance Manager | – | ✓ | ✓ | ✓ | ✓ | – |
| Control Owner | – | – | ✓ (granted folders) | – | – | – |
| Auditor | – | – | – | – | ✓ (read-only) | ✓ |
| Viewer | – | – | – | – | – | – |

Viewers and Control Owners see only folders explicitly shared with them
(folder grants are set on the Documents page). Auditors can read everything,
including the audit trail and access reviews, but can change nothing. The
demo tenant ships with one of each: `admin`, `mia`, `owen`, `aria`, `val` —
all with password `DemoPass123!`.

---

# Part II — Installation

## 4. Prerequisites

For a local install: **Python 3.11 or 3.12** (with `venv` and `pip`),
**Node.js 20+ / npm 10+**, and free ports **8000** (API) and **5173** (web).
No accounts or credentials are required — SQLite, console email, and local
file storage are the defaults. Docker path: **Docker Engine 24+ with Compose
v2** instead of Python/Node. Full details, including the hosted-beta list,
are in `PREREQUISITES.md`.

Unzip the deliverable and enter the folder. Everything below runs from the
repo root (`conformiti/`).

```bash
unzip conformiti.zip && cd conformiti
cp .env.example .env        # safe local defaults; edit later as needed
```

## 5. Path A — one-command installer (recommended first run)

macOS / Linux / WSL:

```bash
./install.sh
```

Windows PowerShell:

```powershell
.\install.ps1
```

What the installer does, in order: verifies Python and Node versions; creates
a virtualenv at `.venv/` in the repo root; installs `backend/requirements.txt`;
runs `makemigrations` + `migrate` for all apps; seeds the demo tenant
(`bootstrap_demo`: 5 users, 217 controls, 7 documents on review cadences,
4 risks, meetings, groups, evidence links, and a starter audit trail);
installs frontend npm packages; then starts **both dev servers** — Django on
`http://127.0.0.1:8000`, Vite on `http://localhost:5173`.

Expected success markers: the seed output listing demo users, then both
servers' startup lines. Open `http://localhost:5173` and sign in.

Re-running on an existing install? Delete `backend/db.sqlite3` first so the
schema and seed are recreated cleanly (see §25 for the full reset).

## 6. Path B — Docker Compose (closest to production)

```bash
docker compose up --build
```

Brings up five services: `db` (Postgres 16), `redis`, `backend` (gunicorn,
migrations + seed run by `entrypoint.sh`), `worker`
(`celery -A config worker -B` — the `-B` embeds the beat scheduler, which is
what makes review reminders fire daily), and `nginx` serving the built SPA.

Ports: the API is on `http://localhost:8000`, and the **web UI is on
`http://localhost:8080`** (nginx maps 8080→80). Sign in at 8080.

To run one-off commands inside Docker:

```bash
docker compose exec backend python manage.py send_review_reminders --dry-run
```

## 7. Path C — manual install (full control)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend
python manage.py makemigrations accounts compliance documents calendar_app notifications audit governance integrations
python manage.py migrate
python manage.py bootstrap_demo          # optional demo tenant
python manage.py runserver 127.0.0.1:8000
# in a second terminal:
cd frontend && npm install && npm run dev
```

For a clean production tenant instead of the demo, skip `bootstrap_demo` and
create your own account: `python manage.py createsuperuser`. The framework
libraries load on first migrate either way.

## 8. Configuration reference (`.env`)

Everything has a safe local default; you only edit `.env` to change behavior.
Grouped by purpose:

**Core Django.** `DJANGO_SECRET_KEY` (generate with
`python -c "import secrets; print(secrets.token_urlsafe(50))"`; with
`DJANGO_DEBUG=false` the app **refuses to boot** on the placeholder value),
`DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`,
`CORS_ALLOWED_ORIGINS`, `TIME_ZONE`, and `COMPLIANCE_TREE_ROOT` (where the
generated evidence tree lives; defaults to `./compliance-data`).

**Security tuning.** When `DJANGO_DEBUG=false`, TLS/cookie hardening turns on
automatically; override with `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`,
`CSRF_COOKIE_SECURE` only if TLS isn't terminated yet, and enable
`SECURE_HSTS_SECONDS=31536000` once you're fully on HTTPS. Rate limits:
`THROTTLE_LOGIN=8/min` (password brute-force), `THROTTLE_ANON=30/min`,
`THROTTLE_MFA=10/min`. Token lifetimes: `JWT_ACCESS_MINUTES=60`,
`JWT_REFRESH_DAYS=7`.

**Database.** Leave the `POSTGRES_*` keys unset to use SQLite locally. Set
`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`,
`POSTGRES_PORT` for Postgres (the compose file wires these for you).

**Email.** `EMAIL_PROVIDER` is one of `console | smtp | mailbox | ses`;
plus `DEFAULT_FROM_EMAIL`, `COMPLIANCE_TEAM_EMAIL` (cc'd on every reminder),
and `REVIEW_ALERT_LEAD_DAYS=30,14,7,1` (when reminders fire, in days before
the review date). Provider-specific keys: SMTP uses `EMAIL_HOST`, `EMAIL_PORT`,
`EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`. SES uses
`AWS_SES_REGION` with credentials from the standard AWS chain. The `mailbox`
provider drives a normal inbox (e.g. Gmail with an app password): the four
`MAILBOX_HOST/PORT/USERNAME/PASSWORD` lines usually suffice — IMAP verifies
the account and files a copy in Sent (`MAILBOX_SAVE_SENT`), SMTP does the
sending, and the `MAILBOX_SMTP_*` keys default from the mailbox values.

**Storage.** `USE_S3=false` keeps documents on local disk; set it `true` with
`AWS_STORAGE_BUCKET_NAME` and `AWS_REGION` for S3.

**Background jobs.** `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` (Redis;
pre-wired in compose).

## 9. Verify the install

```bash
python3 tools/validate.py
```

runs the 14-check static validator (syntax, wiring, API surface, CSS, deps,
demo data, importer/MFA regressions, reminder chain) and should print
`PASS — 0 error(s), 0 warning(s)`. Then sign in as each demo role once — that
exercises auth, RBAC, and the seed end to end. `VALIDATION.md` documents what
each check covers.

## 10. Installation troubleshooting

**Port already in use** — something else holds 8000 or 5173; stop it or run
`python manage.py runserver 127.0.0.1:8001` and adjust the Vite proxy.
**`python3: command not found` / wrong version** — install 3.11+ and ensure
it's first on PATH; on Ubuntu also `sudo apt install python3-venv`.
**npm install fails** — check Node is 20+ (`node -v`); delete
`frontend/node_modules` and retry.
**Re-run says tables already exist / seed duplicates** — you re-ran on an old
database: delete `backend/db.sqlite3` and run the installer again.
**Docker: web UI "connection refused" on 80** — the SPA is on **8080**, not 80.
**Backend won't boot with `DJANGO_DEBUG=false`** — that's the secret-key
guard working; set a real `DJANGO_SECRET_KEY`.
**Reminder emails "sent" but nothing arrives** — you're on the default
`console` provider (they print to the backend terminal); configure a real
provider (§17).

---

# Part III — Using the platform

## 11. First login and orientation

Sign in at `http://localhost:5173` (Docker: `:8080`). The shell is a dark
sidebar with grouped navigation (Workspace, Governance, Account), and a top
bar with the page title, the **◐ dark-mode toggle**, and the **notification
bell**. Start as `mia` (Compliance Manager) for the richest view: the
Dashboard shows framework stats, controls implemented, documents, overdue
reviews, **risk posture** and **evidence coverage** cards, a compliance
calendar, and the upcoming-review list.

A tip before you install anything: `app-preview.html` in the repo root is a
clickable static preview of all 12 screens (with the live theme switcher) —
useful for showing colleagues what they're getting.

## 12. Setting up your own organization

Working order for a real tenant:

1. Create your superuser (§7), sign in, and open **Users**.
2. Create accounts for your team with roles from §3 and a temporary password
   each (8+ characters; the server enforces the validators). Hand passwords
   over securely; users change them in Account → Security.
3. Grant folder access: on **Documents**, select a folder → manage its
   permissions to give Control Owners and Viewers exactly the folders they
   need. Managers and Auditors see everything already.
4. Have everyone enable **two-factor** (§21) — you can see who has it on from
   the Users screen's 2FA column.
5. Retire the demo accounts before anyone else gets the URL (§26).

## 13. Frameworks and controls

**Controls** lists all three frameworks behind chips; switch chips to change
framework. Each row shows the control id, objective, status, and an
**evidence pill** with its linked-document count. Click the pill to open the
evidence drawer: linked documents are listed, and (with document rights) you
can multi-select more documents and **Attach**, or **Unlink** one. Update a
control's implementation status as work lands — the Dashboard and Analytics
percentages recompute from it.

## 14. The document lifecycle

Documents is the day-to-day heart of the system. The folder tree (left)
reflects your control structure; the table (right) shows the selected
folder's documents with owner, review cadence, next review date, and the
**satisfies** chips naming the controls each document evidences.

Typical flows: **Upload** adds a file into the selected folder — set an owner
and a review cadence (the next review date computes from it). **Version**
uploads a new revision (v2, v3…) while keeping history. **Reviewed** stamps
today and rolls the next review date forward one cadence — this is the button
that keeps you out of the overdue list. **Map** edits the control links
inline. **Rename** and **Move** behave as expected, and moving is
permission-checked at both ends.

When a review date passes without a Reviewed click, the document flips to
**Expired**, turns red in every list, triggers the owner's overdue reminder,
and drags the dashboard's overdue counter up — deliberately noisy.

## 15. Evidence, both directions

From a control: open its evidence drawer (§13). From a document: use **Map**
(§14). The same links power the **evidence coverage** card on the Dashboard,
the `with evidence` figures in Analytics, and the manager digest ("N controls
have no evidence linked") in the bell — so linking evidence is what moves
your coverage numbers.

## 16. The risk register

**Risks** opens with summary chips (`live · overdue · high/critical · closed`)
that double as filters. Create a risk with the **New risk** form: title,
type, likelihood and impact (1–5 each) — the score and rating band compute
live. Click any row to open the drawer: change status or treatment, assign an
owner, link a control, set a due date, record the mitigation plan, and add
timestamped notes. Closing a risk stamps `closed_at`.

**Importing.** *Import CSV/XLSX* accepts files up to 2 MB / 1,000 rows,
dedupes by title (re-importing the same file creates nothing), and is
manager-only. Column headers are matched loosely; the canonical set and their
accepted aliases:

| Field | Accepted headers |
|---|---|
| Title *(required)* | title, risk, risk title, name |
| Description | description, details, summary |
| Status | status, state |
| Type | type, risk type, category, source |
| Treatment | treatment, response, risk response |
| Likelihood | likelihood, probability |
| Impact | impact, severity |
| Owner | owner, assigned to, assignee, risk owner |
| Control | control, control id, related control |
| Due date | due, due date, target date, remediation due |
| Identified | identified, identified on, date identified, raised |
| Jira key | jira, jira key, ticket, issue |
| Mitigation plan | mitigation, mitigation plan, plan, remediation |
| Note | note, notes, comment, comments |

Likelihood/impact accept numbers 1–5 or common words (low, medium, high,
very high, critical…). Dates accept ISO dates and Excel serials. **Template**
downloads a starter CSV; `docs/sample-risk-import.csv` is a working example;
**Export** writes the current register out (formula-injection-sanitized).

## 17. Review reminders and notifications

**In-app (the bell).** The feed is computed per user on every fetch: your own
overdue/soon documents and risks, events assigned to you, meeting series
you run that are behind cadence — plus, by role, manager digests (risks
overdue org-wide, evidence gaps, review backlog) and open access reviews for
admins/auditors. Opening the tray marks items read; × dismisses one for good;
each item deep-links to its page. It polls every 60 seconds.

**Email.** The daily scan emails each document's **owner** (cc
`COMPLIANCE_TEAM_EMAIL`) at each lead window in `REVIEW_ALERT_LEAD_DAYS`
(default 30/14/7/1 days before) and once when overdue — which also marks the
document Expired. Each window sends exactly once per review cycle; clicking
**Reviewed** resets the cycle.

How sending happens: under Docker it's automatic (the worker's embedded beat
runs the scan daily). On bare metal, either run a Celery worker with `-B`, or
cron the management command:

```
0 8 * * *  cd /path/to/conformiti/backend && ../.venv/bin/python manage.py send_review_reminders
```

Testing the pipeline safely: `--dry-run` prints what would send; with the
default `console` provider a real run prints the fully rendered emails to the
terminal; `python manage.py test_mailbox --to you@example.com` checks mailbox
credentials end to end. Switch `EMAIL_PROVIDER` (§8) when you're ready for
real delivery.

## 18. Calendar and meetings

The Dashboard calendar aggregates review due dates and calendar events;
managers can add events (audits, deadlines) with assignees — assigned events
feed that person's bell. **Meetings** tracks governance series (e.g. Security
Steering) against a required-per-year cadence with an on-track/behind bar;
record each occurrence as a minute (date, title, attendees, optional file) —
this is the evidence trail for "does management actually meet" questions.

## 19. Access reviews (User audit)

Quarterly (or per your policy), an administrator opens **User audit → Start
new review**. The platform snapshots every account with its role and last
login; you record keep / modify / revoke per row, add notes, **Export CSV**
for the audit binder, and **Complete review**. Completed reviews stay listed
as point-in-time records. Auditors can read reviews but not decide.

## 20. The audit log

**Audit log** (admins, auditors, and view-all managers) shows the immutable
trail: when, actor, action (create/update/delete), record, human-readable
detail, and source IP. Filter by action, record type, user, or time window;
search free text; **Load more** pages back through history. Entries are
written server-side on every mutating API call — there is no way to add,
edit, or remove one from the app, which is the point.

## 21. Your account: profile, password, MFA, appearance

**Profile** edits your name, email, and job title. **Security** changes your
password (current password required) and manages **two-factor
authentication**: Enable → add the setup key or `otpauth://` URI to any
authenticator app (Google Authenticator, Authy, 1Password, Microsoft
Authenticator) → confirm a 6-digit code → **save the 10 backup codes shown
once** (downloadable as .txt). From then on, sign-in asks for a code after
your password; a backup code works exactly once. Disabling MFA or
regenerating codes requires your password. Locked out with a lost device? An
administrator uses **Reset 2FA** on your row in Users, and you re-enroll.

**Appearance** picks your theme — Audit Ledger or Blazor, each in light and
dark — and an accent color (presets or any hex; the palette derives
automatically, and status colors stay fixed so red still means overdue). The
◐ button in the top bar flips light/dark instantly. Choices persist per
browser.

## 22. Jira integration

On **Jira** (admin): enter your Atlassian Cloud base URL, account email, and
a scoped API token → **Test** verifies connectivity → **Save**. Add a board
id to list its issues alongside your risks (risks can carry a `jira_key`).
The connector is SSRF-hardened and optional — without credentials the page
shows a clean empty state.

## 23. Analytics

**Analytics** is the read-only rollup: per-framework readiness, control
status distribution (with the evidence-coverage figure), and a six-month
review timeline. Use it for leadership updates; use the Dashboard for your
own working view.

---

# Part IV — Administration and operations

## 24. Managing users over time

The **Users** screen handles the lifecycle: create (role + temp password),
change roles inline, **Set password** (recovery), **Deactivate** (blocks
sign-in, keeps history — prefer this over delete), **Activate**, **Delete**
(confirm-gated), and **Reset 2FA**. The API enforces lockout guards you can
rely on: nobody can deactivate or delete themselves, change their own role,
touch a superuser without being one, delete a superuser at all, or make any
change that would leave zero active administrators. Every action lands in the
audit log.

## 25. Data operations

**Reset to a clean slate (local):** stop the servers, delete
`backend/db.sqlite3`, re-run the installer — schema, seed, and demo tenant
are recreated.

**Backups (hosted):** nightly `pg_dump` of Postgres plus a copy of the
uploaded-files directory (or the S3 bucket if `USE_S3=true`), and test a
restore once before you need it.

**Getting data out:** risk register → Export (CSV); access reviews → Export
CSV per review; documents are plain files on disk/S3.

## 26. Going to production / beta

The condensed checklist (full version in `PREREQUISITES.md` and
`SECURITY.md`): set `DJANGO_DEBUG=false` with a strong `DJANGO_SECRET_KEY`;
set real `DJANGO_ALLOWED_HOSTS` / `CORS_ALLOWED_ORIGINS` /
`CSRF_TRUSTED_ORIGINS`; run Postgres + Redis (compose provides both);
terminate TLS and enable HSTS once stable; configure a real `EMAIL_PROVIDER`;
create your own superuser and **remove or rotate every demo account**
(`DemoPass123!` must not reach a shared URL); re-run `tools/validate.py` and
the TESTING §17 security spot-checks against the deployed URL. `SECURITY.md`
lists the residual risks to consciously accept (JWTs in localStorage, no
refresh-token rotation, Jira/TOTP secrets at rest in the DB).

## 27. Where everything lives

```
conformiti/
├── app-preview.html      # clickable static preview (open in a browser)
├── install.sh / install.ps1 / docker-compose.yml
├── .env.example          # full configuration reference (copy to .env)
├── backend/              # Django apps: accounts, compliance, documents,
│                         # calendar_app, notifications, audit, analytics,
│                         # governance, integrations
├── frontend/             # React 18 + Vite SPA (src/pages, src/components,
│                         # src/styles/app.css, src/theme.js)
├── tools/validate.py     # 14-check static validator (run any time)
└── docs/                 # ARCHITECTURE.md, SHAREPOINT_INTEGRATION.md,
                          # EXECUTIVE_SUMMARY.txt, sample-risk-import.csv
```

Companion documents: `README.md` (overview + API surface),
`GETTING_STARTED.md` (fast install-and-verify), `TESTING.md` (24-step test
script), `PREREQUISITES.md`, `VALIDATION.md`, `SECURITY.md`, `ROADMAP.md`,
`FEATURE_COMPARISON.md`.
