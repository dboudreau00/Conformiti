# Getting started — install & test every function

One walkthrough from an empty machine to exercising every feature. It folds the
install steps and all 22 test scenarios into a single ordered flow. Budget
~45–60 minutes. Deeper per-topic notes live in `INSTALL.md`, `TESTING.md`,
`PREREQUISITES.md`, and `SECURITY.md`.

Legend: **⌨ = run in a terminal**, **🖱 = do in the browser**, **✓ = what you
should see**.

---

## Part A — Prerequisites (5 min)

Alpha/local needs only:
- **Python 3.11 or 3.12** with `venv` + `pip`
- **Node.js 20+** and **npm 10+**
- Free ports **8000** (API) and **5173** (web)
- No external accounts required — SQLite, console email, and local storage are
  the defaults.

(Optional, to exercise real email/Jira later: SMTP or SES creds, or an
IMAP/POP3 mailbox; an Atlassian Cloud site + API token.)

Full detail incl. the beta/hosted list: `PREREQUISITES.md`.

---

## Part B — Install (10 min)

### Option 1 — one-command installer (recommended for alpha)

⌨ macOS / Linux / WSL:
```bash
unzip conformiti.zip && cd conformiti
cp .env.example .env
./install.sh
```
⌨ Windows (PowerShell):
```powershell
Expand-Archive conformiti.zip; cd conformiti
Copy-Item .env.example .env
.\install.ps1
```
The installer creates the virtualenv, installs backend + frontend deps, runs
migrations, seeds demo data, and starts both servers.

✓ Backend on `http://localhost:8000`, web app on `http://localhost:5173`.
✓ Console shows the demo users being created.

> Re-running on an existing install? Delete `backend/db.sqlite3` first so the
> seed + any new tables are recreated cleanly.

### Option 2 — Docker (closer to production)

⌨:
```bash
cd conformiti
cp .env.example .env
docker compose up --build
```
✓ Brings up Postgres 16, Redis, the API, a Celery worker (with beat), and nginx
serving the built SPA. The worker running is what makes email reminders fire on
schedule (Part R).

### Verify the build is wired (30 sec)

⌨:
```bash
python3 tools/validate.py
```
✓ `PASS — 0 error(s), 0 warning(s)` across 14 checks (syntax, app/route wiring,
API surface, imports, CSS, deps, deploy, demo data, importer, MFA vectors, and
the review-reminder chain).

---

## Part C — Sign in (2 min)

🖱 Open `http://localhost:5173`. Demo accounts — all password **`DemoPass123!`**:

| User | Role | Use it to test |
|------|------|----------------|
| `admin` | Administrator (superuser) | user management, everything |
| `mia` | Compliance Manager | frameworks, docs, risks, manager digests |
| `owen` | Control Owner | owned documents/risks, evidence |
| `aria` | Auditor | read-only + access reviews |
| `val` | Viewer | least-privilege / negative checks |

✓ Sign in as `mia` to start.

---

## Test each function

Work top-to-bottom; each step names the account to use.

### 1 · Dashboard  🖱 as `mia`
Landing page. ✓ Four stat cards (frameworks, controls implemented, documents,
reviews overdue), plus **Risk posture** (`3 open · 1 overdue`) and **Evidence
coverage** (`7%` · 15/217) cards, a compliance calendar, and an "upcoming
reviews" list.

### 2 · Analytics  🖱 Analytics
✓ Per-framework readiness donuts/bars; control-status card eyebrow reads
`15/217 have evidence`; a 6-month review timeline.

### 3 · Controls + evidence mapping  🖱 Controls
✓ Framework chips (SOC 2 / ISO 27001 / PCI). Each control row has an **Evidence**
count pill. 🖱 Click `CC6.1`'s pill → a drawer lists the linked Access Control
Policy. 🖱 Multi-select documents in "Attach evidence" + **Attach** → count
updates live; **Unlink** decrements it.

### 4 · Documents (upload / version / review / map)  🖱 Documents
🖱 Open folder `CC6.1`. ✓ The Access Control Policy row shows chips
`CC6.1 A.5.15 7.1`. 🖱 **Map** → add/remove control links inline. 🖱 Upload a
file, then **Version** (adds v2), **Rename**, **Reviewed** (pushes the next
review date out). ✓ As `val`, folders you lack access to don't appear.

### 5 · Evidence reverse mapping  🖱 Controls ↔ Documents
✓ Switch to ISO 27001: `A.5.1` shows **2 docs** (Information Security Policy +
PCI Information Security Policy) — one document satisfying several frameworks.

### 6 · Risk register + CSV/XLSX import  🖱 Risks (as `mia`)
✓ Header chips `3 live · 1 overdue · 2 high/critical · 1 closed`. 🖱 Click a row
→ edit status/owner/plan and add a note. 🖱 **Import CSV/XLSX** →
`docs/sample-risk-import.csv` → **4 created, 0 warnings**; import again → **0
created, 4 skipped** (dedupe). 🖱 **Template** and **Export** download CSVs.

### 7 · User audit (access review)  🖱 User audit (as `admin`)
🖱 **Start new review** → a grid snapshots all users. 🖱 Set decisions
(keep/modify/revoke), **Export CSV**, then **Complete review**.

### 8 · Meetings  🖱 Meetings
✓ Series list with cadence bars — Security Steering **3/4 on track**, Risk Review
**1/2 behind**. 🖱 Select a series → add a minute (date/title/attendees/file).

### 9 · Groups  🖱 Groups
✓ Security Champions with members owen (Engineering) + val (Operations). 🖱 Add
a member; create a group.

### 10 · Jira (optional — needs Atlassian)  🖱 Jira (as `admin`)
🖱 Enter base URL / email / API token → **Test** → **Save**. 🖱 Add a board id →
select it to list issues. ✓ Without creds, a clear empty state (no crash).

### 11 · User management (admin panel)  🖱 Users (as `admin`)
🖱 **New user** (role + temp password ≥8 chars — try `short` to see validation).
🖱 Change a user's role inline; **Set password**, **Deactivate/Activate**,
**Delete**. ✓ Lockout guards: you can't deactivate/delete yourself or strip the
last admin; superusers can't be deleted via the API. 🖱 As `val`, /users shows a
"needs manage-users" notice.

### 12 · Two-factor auth (MFA)  🖱 Account → Security (as `mia`)
🖱 **Enable two-factor** → add the setup key/`otpauth://` to any authenticator
(Google Authenticator, Authy, 1Password) → enter the 6-digit code → save the 10
**backup codes**. 🖱 Sign out and back in → you're prompted for a code; a wrong
code is rejected, a backup code works once. 🖱 As `admin`, the Users page shows a
`2FA on` badge and **Reset 2FA** for lockout recovery.

### 13 · Notification bell (in-app alerts)  🖱 top bar
🖱 As `owen`, open the bell → overdue/soon items for **his** documents and risks,
each deep-linking to the page; opening marks them read; **×** dismisses one.
✓ As `mia`, the feed is manager **digests** instead (N risks overdue, 202
controls without evidence, cadence behind). ✓ As `val`, "You're all caught up."

### 14 · Audit log  🖱 Audit log (as `admin` or `aria`)
✓ Immutable trail of every change: actor, action, record, detail, IP — with
filters, search, and Load more. Make any change (rename a document) → a new
`update` entry appears. `owen`/`val` get the capability notice (403 on the
API). Bonus: the ◐ top-bar button toggles dark mode instantly.

---

## Part R — Email review reminders (the "document expiring / review due" alerts)

Both channels are wired: the **in-app bell** (step 13) and **email**. Documents
are foldered per control, so a reminder about a document is a reminder about that
control's evidence. Reminders go to the **document owner** + the compliance-team
address, at **30 / 14 / 7 / 1 days** before the review date and once when
**overdue** (which also flips the document to *Expired*). Each window is sent
once (deduped), so re-running is safe.

### R1 · See what would send, without emailing  ⌨
```bash
cd backend
../.venv/bin/python manage.py send_review_reminders --dry-run     # installer layout
# or inside Docker:  docker compose exec backend python manage.py send_review_reminders --dry-run
```
✓ `Review scan complete. Documents would be notified: N` (with the seed data,
the overdue IR Plan plus the ones due within 30 days).

### R2 · Actually send them to your terminal (no mail server needed)  ⌨
The default `EMAIL_PROVIDER=console` prints the rendered emails to stdout.
```bash
../.venv/bin/python manage.py send_review_reminders
```
✓ Full HTML+text reminder emails print to the console, addressed to each
document's owner. ✓ Re-run immediately → `notified: 0` (dedupe working).

### R3 · Send real email  ✏ edit `.env`, then repeat R2
Pick one provider and set its keys, then restart the backend:
```ini
EMAIL_PROVIDER=smtp        # or ses, or mailbox
DEFAULT_FROM_EMAIL=compliance@yourdomain.com
COMPLIANCE_TEAM_EMAIL=grc@yourdomain.com
# smtp:  EMAIL_HOST / EMAIL_PORT / EMAIL_HOST_USER / EMAIL_HOST_PASSWORD / EMAIL_USE_TLS
# ses:   AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SES_REGION
# mailbox: MAILBOX_IMAP_HOST / MAILBOX_SMTP_HOST / MAILBOX_USER / MAILBOX_PASSWORD
REVIEW_ALERT_LEAD_DAYS=30,14,7,1     # tune the lead windows if you like
```
⌨ Mailbox provider has its own connectivity check:
`../.venv/bin/python manage.py test_mailbox`.

### R4 · Automatic daily sending
- **Docker:** already automatic — the `worker` service runs
  `celery -A config worker -B`, and beat runs `scan_document_reviews` daily.
- **Bare metal without Celery:** add a crontab —
  `0 8 * * *  cd /app/backend && ../.venv/bin/python manage.py send_review_reminders`.

### R5 · Trigger a fresh reminder on demand
🖱 On any document, set the review cadence and click **Reviewed** to reset its
date, or lower `REVIEW_ALERT_LEAD_DAYS`; ⌨ re-run R2 to see that document's
reminder go out (its dedupe state resets when the next review date changes).

---

## Part S — Security spot-checks (optional, 5 min)

⌨ / 🖱 (see `TESTING.md` §17):
- **Login throttle:** ~10 rapid wrong passwords → HTTP 429 after 8/min.
- **Least privilege:** as `val`, adding a calendar event or writing to
  `/api/folder-permissions/` is refused (403).
- **CSV-injection safe:** set your last name to `=1+1`, export a review/register
  CSV → the cell shows `'=1+1` as text.
- **Prod guard:** set `DJANGO_DEBUG=false` with the placeholder key → the backend
  refuses to boot until you set a strong `DJANGO_SECRET_KEY`.

---

## Part P — Before a hosted beta

1. `DJANGO_DEBUG=false` + strong `DJANGO_SECRET_KEY`
   (`python -c "import secrets; print(secrets.token_urlsafe(50))"`).
2. Set `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`.
3. Use Postgres + Redis (Docker compose provides both); terminate TLS; enable
   HSTS via `SECURE_HSTS_SECONDS` once HTTPS is stable.
4. Configure a real `EMAIL_PROVIDER` so reminders actually send (Part R).
5. Create your own superuser and **remove/rotate the demo accounts** —
   `DemoPass123!` must not reach beta.
6. Re-run `python3 tools/validate.py` and the Part S checks against the deployed
   URL.

Residual risks to accept or mitigate (JWTs in localStorage, no refresh-token
rotation, Jira token at rest) are documented in `SECURITY.md`.
