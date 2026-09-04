# Getting started — install, verify, exercise every function

One walkthrough from an empty machine to having touched every feature.
Budget 30–45 minutes. Deeper references: [INSTALL.md](INSTALL.md),
[USER_GUIDE.md](USER_GUIDE.md), [TESTING.md](TESTING.md), [SECURITY.md](SECURITY.md).

Legend: **⌨ terminal** · **🖱 browser** · **✓ what you should see**

---

## Part A — Install (5 min)

**Docker (recommended):**

```bash
git clone https://github.com/dboudreau00/Conformiti.git && cd Conformiti
./install.sh --docker            # Windows: .\install.ps1 -Docker
```

✓ The script builds the images, waits for `/api/health/` to say `ok`, and
prints `App http://localhost:8080` with the demo credentials.

**Local dev (no Docker):** `./install.sh` (or `.\install.ps1`) → open
**http://localhost:5173**.

**Verify the build is wired (30 s):** `./install.sh --test` ✓ validator
`PASS — 0 error(s)`, `Ran 213 tests … OK`, `✓ built`.

## Part B — Sign in (1 min)

🖱 Sign in as `mia` / `DemoPass123!` (the login page shows the demo hint only
while demo accounts exist). ✓ The Dashboard loads; the sidebar shows Workspace
and Governance sections with live badges (controls in progress, open risks).

Demo accounts, all `DemoPass123!`: `admin` (superuser) · `mia` (Compliance
Manager) · `owen` (Control Owner) · `aria` (Auditor) · `val` (Viewer).

## Part C — Every function

### 1 · Dashboard 🖱
✓ "Overall readiness" with the big percentage, the control status bar and a
trend line that grows one point per day (a fresh install shows a single point
and the note *History builds from daily snapshots*). ✓ Frameworks / Documents /
Reviews overdue cards, Evidence coverage, Risk posture. ✓ The compliance
calendar with Review/Audit/Task/Other filters — click a day to list its items.
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
Create `tess` (Viewer, password of 12+ characters — `short` is rejected), change
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

## Part D — Email reminders ⌨

```bash
docker compose exec backend python manage.py send_review_reminders --dry-run   # Docker
cd backend && ../.venv/bin/python manage.py send_review_reminders --dry-run     # local
```

✓ `Documents would be notified: N`. Drop `--dry-run` to send (the default
`console` provider prints the emails to the backend log); run again → `0`
(deduplicated). In Docker the worker does this daily at `REVIEW_SCAN_HOUR`.
Real mail: set `EMAIL_PROVIDER=smtp|mailbox|ses` in `.env` and restart;
`manage.py test_mailbox --to you@example.com` checks a mailbox account.

## Part E — Before real users ⌨

1. `.env`: `DJANGO_ALLOWED_HOSTS`, the two origin variables, `BEHIND_TLS=true`
   behind TLS, a real `EMAIL_PROVIDER`, a strong `POSTGRES_PASSWORD`.
2. `docker compose exec backend python manage.py createsuperuser`
3. `docker compose exec backend python manage.py remove_demo_data`
4. `curl -s http://localhost:8080/api/health/` → `"demo_accounts": false`.
5. Back up the `pgdata` and `media` volumes.

Residual risks to weigh: [SECURITY.md](SECURITY.md#residual-risks-to-weigh-for-production).
