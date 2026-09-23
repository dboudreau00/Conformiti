# Getting started: install, verify, exercise every function

One walkthrough from an empty machine to having touched every feature.
Budget 30 to 45 minutes. Deeper references: [INSTALL.md](INSTALL.md),
[USER_GUIDE.md](USER_GUIDE.md), [TESTING.md](TESTING.md), [SECURITY.md](SECURITY.md).

Legend: **⌨ terminal** · **🖱 browser** · **✓ what you should see**

---

## Part A: Install (5 min)

**Docker (recommended):**

```bash
git clone https://github.com/dboudreau00/Conformiti.git && cd Conformiti
./install.sh --docker --demo   # Windows: .\install.ps1 -Docker -Demo
```

✓ The script builds the images, waits for `/api/health/` to say `ok`, and
prints `App http://localhost:8080` and the demo password. The password is
generated on first boot and logged once by the backend, where the script
reads it: `docker compose logs backend | grep "Sign in as"` (PowerShell:
`docker compose logs backend | Select-String "Sign in as"`). If that log no
longer has it, the banner says so and gives
`docker compose exec backend python manage.py changepassword admin`.

`--demo` (`-Demo`) asks for the sample organisation this tour walks through.
It lands in `.env` as `SEED_DEMO_DATA=true`, which is what the stack reads;
with a `.env` already in place the script rewrites a line that disagrees,
and says so. It
is off by default, because a real installation should not carry five shared
accounts, and says so on its own sign-in page while it does. For a
deployment you intend to keep, leave it out and create your administrator with
`docker compose exec backend python manage.py createsuperuser`, or put
`DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_PASSWORD` and
`DJANGO_SUPERUSER_EMAIL` in `.env` before the first boot. Either way the
password must pass the password policy: at least `PASSWORD_MIN_LENGTH`
characters (12 by default), not a common password, not all digits, and not
too close to the username or email. One that fails creates no account:
`createsuperuser` says why, and so does the backend log for the `.env` route.

**Windows:** if PowerShell refuses with *running scripts is disabled on this
system*, run `powershell -ExecutionPolicy Bypass -File .\install.ps1 -Docker -Demo`
instead ([INSTALL.md](INSTALL.md), the scripted variant, explains why).
Windows is supported for development and evaluation; run production on a
Linux host.

**Local dev (no Docker):** `./install.sh --demo` (or `.\install.ps1 -Demo`),
then open **http://localhost:5173**. The demo password is in the installer's
closing *Setup complete* banner (and on the seeding step's line starting
`Sign in as`).

**Verify the build is wired:** `./install.sh --test` (or `.\install.ps1 -Test`)
✓ the validator ends with `PASS` and `0 error(s)`, the backend suite prints
`Ran N tests` and `OK`, and the frontend build prints `✓ built`. Allow about
fifteen minutes; the backend suite is most of it.

## Part B: Sign in (1 min)

🖱 Sign in as `mia`, using the demo password from Part A. The sign-in page
mentions the demo accounts only while they exist. ✓ The Dashboard loads;
the sidebar shows Workspace and Governance sections with live badges (controls
in progress, open risks).

Demo accounts, all sharing that one password: `admin` (superuser) · `mia` (Compliance
Manager) · `owen` (Control Owner) · `aria` (Auditor) · `val` (Viewer).

## Part C: Every function

### 1 · Dashboard 🖱
✓ "Overall readiness" with the big percentage, the control status bar and a
trend line that grows one point per day (a fresh install shows a single point
and the note *History builds from daily snapshots*). ✓ Frameworks / Documents /
Reviews overdue cards, Evidence coverage, Risk posture. ✓ The compliance
calendar with Review/Audit/Task/Other filters; click a day to list its items.
✓ "Reviews coming up" with **Mark reviewed** (managers/owners only).

### 2 · Theme packs 🖱
Top bar → theme picker → try **Audit Ledger**, **Nimbus**, **Ledger Dark**,
**Obsidian**; click the accent dots. ✓ Every surface, chart and badge recolours
instantly and the choice survives a reload. Settings → Appearance also offers a
custom accent colour.

### 3 · Analytics 🖱
✓ Framework readiness bars (SOC 2, ISO 27001, PCI DSS), control and document
status donuts, the six-month review load, ownership coverage, most-overdue
documents.

### 4 · Controls 🖱
Filter by framework and status, search `CC6.1`, expand the row. ✓ Objective,
status and owner selects (managers), linked evidence with **Unlink** only where
you have edit rights, an **Attach evidence** form. Attach the "Access Control
Policy" to `CC6.2` → ✓ the evidence count bumps. **Export CSV** downloads the
register.

### 5 · Documents 🖱
Expand *SOC 2 → CC6 → CC6.1* with the keyboard (arrow keys, Enter). Upload a
file (name, cadence Quarterly, any small file) ✓ it appears with a review badge.
**Rename**, **Version** (v2), **Reviewed** (date moves out), **Map** (link a
control). **Manage access** → grant the *Viewer* role or the user `val` view on
this folder. Create a subfolder; delete it (framework folders cannot be deleted).

### 6 · Role-based access 🖱
Sign out; sign in as `val`. ✓ Only granted folders appear, no upload form, no
"Mark reviewed", no risk creation. Try `/api/folders/` in the browser → only
those folders. Sign back in as `mia`.

### 7 · Risks 🖱
✓ `3 live · 1 overdue · 2 high/critical · 1 closed`. Open a row → change
status, owner, plan; add a note. **Import CSV/XLSX** with
`docs/sample-risk-import.csv` → ✓ *4 created*; import again → ✓ *4 skipped*.
**Export**.

### 8 · User audit 🖱 (as `admin`)
**Start new review** → ✓ one row per account. Record decisions, **Export CSV**
(open it: a name like `=1+1` is stored as text), **Complete review** (refused
while rows are pending). Sign in as `aria` → ✓ read-only: no start/complete,
decisions shown as badges.

### 9 · Meetings · Groups · Jira 🖱
Meetings: ✓ Security Steering Committee on track, Risk Review behind; record
minutes → the cadence meter moves. Groups: add a champion. Jira: configure
with a real Atlassian site if you have one; otherwise ✓ a clear "not
configured" state.

### 10 · Users 🖱 (as `admin`)
Create `tess` (Viewer, password of 12+ characters; `short` is rejected), change
her role, set a password, deactivate, delete. ✓ You cannot deactivate or delete
yourself or strip the last administrator.

### 11 · Two-factor auth 🖱
Settings → Security → **Enable two-factor**: add the key to an authenticator,
confirm the code, download the backup codes. Sign out and in → ✓ a code is
required; a backup code works once. As `admin`, Users → **Reset 2FA**.

### 12 · Notifications 🖱
The bell shows what *you* own or are responsible for (overdue documents and
risks for `owen`; org-wide digests for `mia`; nothing for `val`). Opening marks
read; × dismisses.

### 13 · Audit log 🖱 (as `admin` or `aria`)
✓ Your sign-ins, the failed sign-in you tried earlier, every change above with
the fields it touched, and the IP. Filters and search work; the page has no
edit or delete anywhere (the API returns 405).

## Part D: Email reminders ⌨

```bash
docker compose exec backend python manage.py send_review_reminders --dry-run   # Docker
cd backend && ../.venv/bin/python manage.py send_review_reminders --dry-run     # local
```

✓ `Documents would be notified: N`. Drop `--dry-run` to send (the default
`console` provider prints the emails to the backend log); run again → `0`
(deduplicated). In Docker the `beat` service schedules this daily at
`REVIEW_SCAN_HOUR` and the worker runs it. Real mail: set
`EMAIL_PROVIDER=smtp|mailbox|ses` in `.env` and run `docker compose up -d`,
which recreates the containers with it. To test the transport on its own,
`manage.py test_mailbox --to you@example.com` sends a sample review reminder
through whichever provider is configured (with `mailbox` it checks the
account's sign-in first).

## Part E: Before real users ⌨

1. `.env`: `DJANGO_ALLOWED_HOSTS`, the two origin variables, `BEHIND_TLS=true`
   behind TLS, a real `EMAIL_PROVIDER`, a strong `POSTGRES_PASSWORD`. The
   database was created on first boot with the default password
   (`compliance`), and `POSTGRES_PASSWORD` only applies to a new database
   volume, so change it in the database first, then in `.env`, then recreate:
   `docker compose exec db psql -U compliance -c "ALTER USER compliance PASSWORD 'something-long'"`
   and `docker compose up -d` ([INSTALL.md](INSTALL.md), *Going to production*).
   On the published images, give that `up` the same `-f` files you started
   with, or it rebuilds the stack from source ([INSTALL.md](INSTALL.md),
   *Without a build*).
2. `docker compose exec backend python manage.py createsuperuser`, with a
   password that passes the policy from Part A.
3. `docker compose exec backend python manage.py remove_demo_data`. The
   retirement holds across restarts even while `.env` still says
   `SEED_DEMO_DATA=true` (the backend logs `Demo data not seeded` instead);
   set it to `false` anyway, so `.env` says what the installation does.
4. `curl -s http://localhost:8080/api/health/` → `"demo_accounts": false`.
5. Put `scripts/backup.sh` on cron and copy its output off the machine.
   `scripts/restore.sh <directory>` brings an installation back, here or
   elsewhere; CI runs both on every push. On the published images, set
   `COMPOSE_FILE` and `CONFORMITI_VERSION` (the backup's release) in `.env`
   first: the script takes no `-f` files, so without them the restore
   rebuilds the stack from source or runs `latest`
   ([INSTALL.md](INSTALL.md), *Without a build*).

Residual risks to weigh: [SECURITY.md](SECURITY.md#residual-risks-to-weigh-for-production).
