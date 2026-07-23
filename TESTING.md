# Direct test script

A start-to-finish pass through the platform. Every expected value below comes
from the seeded demo data, so you can check results exactly. Total time:
~15 minutes. Install details live in `INSTALL.md`; this file assumes the
one-command path.

**Accounts** (all passwords `DemoPass123!`):
`admin` (superuser) · `mia` (Compliance Manager) · `owen` (Control Owner) ·
`aria` (Auditor) · `val` (Viewer)

**Seeded documents** (owner: Owen Owner):

| Document | Review due |
|---|---|
| Incident Response Plan | **3 days overdue** |
| PCI Information Security Policy | in 1 day |
| User Access Provisioning Procedure | in 6 days |
| Backup and Restore Procedure | in 12 days |
| Information Security Policy | in 20 days |
| Access Control Policy | in 45 days |
| Network Segmentation Standard | in 90 days |

---

## 1 · Install & start

```bash
./install.sh        # macOS / Linux / WSL     (Windows: .\install.ps1)
```

**Expect:** green check lines for deps, migrations, "database ready
(SOC 2 · ISO 27001 · PCI DSS seeded)", then both servers start.
Open **http://localhost:5173**.

## 2 · Sign in

Log in as `admin` / `DemoPass123!`.

**Expect:** the Dashboard loads; the sidebar shows Dashboard, Analytics,
Controls, Documents, and an Account → Settings section; the footer shows
"Ada Admin".

## 3 · Dashboard

**Expect:**
- Frameworks stat = **3** (SOC 2 · ISO/IEC 27001 · PCI DSS)
- Documents stat = **7**
- Reviews overdue = **1** (red)
- The calendar shows review-due entries; "Review due: Incident Response Plan"
  is tinted red (overdue); a few audit/task events also appear.
- "Reviews coming up" lists the documents above, most urgent first.

Don't mark anything reviewed yet — Analytics first.

## 4 · Analytics

Open **Analytics**.

**Expect:**
- Overall readiness shows a percentage with a progress bar (>0% — the seed
  marks a portion of controls implemented).
- Framework readiness: three rows (SOC 2, ISO 27001, PCI DSS), each with a
  stacked status bar.
- Control-status donut centers on **217**; document donut centers on **7**.
- Upcoming reviews timeline: six month columns; the current month ≥ 3.
- Ownership coverage: documents with an owner = **7/7**.
- "Most overdue documents" lists **Incident Response Plan — 3d — Owen Owner**.

## 5 · Close the loop on the overdue review

Back on **Dashboard**, click **Mark reviewed** on *Incident Response Plan*.

**Expect:** the row leaves the urgent list, Reviews overdue drops to **0**,
and the calendar entry moves ~6 months out (its cadence is semiannual).
Revisit **Analytics** → the overdue list now says "No overdue documents."

## 6 · Controls

Open **Controls**.

**Expect:** framework chips — SOC 2 (**61**), ISO 27001 (**93**),
PCI DSS (**63**). Control IDs render in monospace.

Change any control's status to **Implemented** via its inline dropdown, then
return to Dashboard: **Controls implemented** has increased by one.

## 7 · Documents

Open **Documents**, expand *SOC 2 → CC6 → CC6.1*, and select its **evidence**
folder (as admin, `my_access` is manage everywhere).

1. **Upload** — name it "Test Evidence", cadence *Quarterly*, owner *Owen*,
   attach any small file. → It appears with an amber/green review badge.
2. **Rename** it to "Test Evidence v1". → Name updates in place.
3. **New version** — upload another file. → Version becomes **v2**.
4. **Mark reviewed** → next review moves ~3 months out.
5. **Folder permissions** (Manage access): grant role **Viewer** → *view* on
   this folder. → It appears in the grants list.

## 8 · Role-based access

Sign out, sign in as `val` / `DemoPass123!` (Viewer).

**Expect:** the Documents tree is only the folders granted to Viewer —
including the folder from step 7.5 — with **no upload form** (view access).
Controls are visible but the Dashboard shows only documents val can see.
Sign out, back in as `admin`.

## 9 · Account settings

Click your name (or **Settings**) → the account sidebar.

1. **Profile:** set Job title = "Platform Tester" → Save. **Expect** "Profile
   saved." Reload the page directly on `/account` — the form repopulates.
2. **Security:** enter a wrong current password → **Expect** "Current password
   is incorrect." (Change it for real only if you want to.)
3. **Role & access:** admin shows every capability checked.

## 10 · Review reminders (console mailer)

In a second terminal:

```bash
cd backend
../.venv/bin/python manage.py send_review_reminders --dry-run
```

**Expect:** `Documents would be notified: 4` (the 1/6/12/20-day documents;
5 if you skipped step 5). Then run it for real:

```bash
../.venv/bin/python manage.py send_review_reminders
```

**Expect:** full reminder emails print to this terminal (console provider),
addressed to owen@example.com + the compliance team. Run it **again** →
`notified: 0` — the dedupe means no document is reminded twice for the same
window.

## 11 · Mailbox mailer — optional, needs a real account

Set in `.env` (Gmail app password works well):

```ini
EMAIL_PROVIDER=mailbox
DEFAULT_FROM_EMAIL=you@example.com
MAILBOX_HOST=imap.gmail.com
MAILBOX_USERNAME=you@example.com
MAILBOX_PASSWORD=your-app-password
MAILBOX_SMTP_HOST=smtp.gmail.com
```

Restart the backend, then:

```bash
../.venv/bin/python manage.py test_mailbox --to you@example.com
```

**Expect:** `IMAP OK (imap.gmail.com:993) — N mailboxes visible`, then a test
email in your inbox — and a copy in the account's **Sent** folder.
`send_review_reminders` now delivers real mail the same way.

## 12 · Docker path — optional

```bash
./install.sh --docker
```

**Expect:** Postgres, Redis, backend, Celery worker, and nginx come up; the
app serves at **http://localhost:8080** with the same data and logins. The
worker runs the review scan daily on its own.

## 13 · User audit (access review grid + CSV)

Open **User audit** (Governance section). Type "Q3 2026 access review" and click
**Start new review**.

**Expect:** a grid with **5 rows** (admin, aria, mia, owen, val) showing each
account's role, last login, folder-grant count and capabilities. Set a decision
on every row (try **Revoke** on `val` — the select turns red), add a note, then:

- **Export CSV** → downloads `access-review-<id>.csv` with a header + 5 data rows,
  decisions and notes included.
- **Complete review** → the badge turns green and the grid becomes read-only
  evidence. (Completing while any row is still Pending is refused with a count.)

## 14 · Meeting cadences

Open **Meetings**.

**Expect two seeded series:** *Security Steering Committee* (3/4 this year,
**On track** — the pro-rated expectation in July is 3) and *Risk Review* (1/2,
**Behind** — both semi-annual sessions were due by now). Select the steering
committee → three minutes listed. Record a new minute dated today → the count
becomes 4/4 and the badge flips to **Complete**.

## 15 · Champion groups

Open **Groups**.

**Expect:** *Security Champions*, owner **Mia Manager**, with 2 members —
Owen (Engineering) and Val (Operations). Add yourself as a champion for a third
department, then remove a member. Create a second group (e.g. "Privacy
Champions") with an owner to see the owned-group pattern.

## 16 · Jira boards — optional, needs a real Atlassian account

Open **Jira** as admin. Fill the connection card: base URL
(`https://your-team.atlassian.net`), account email, and an API token from
id.atlassian.com → Security → API tokens. Save, then **Test connection**.

**Expect:** "Connected to Jira as <your name>." Track a board by its numeric ID
(the number in its Jira URL) → issues render with key, status, assignee and
updated date. The token stays server-side; issue fetches are proxied through
the backend. Wrong credentials produce a readable error, not a blank page.

## 17 · Security spot-checks (optional)

Quick confirmations of the audit fixes (see `SECURITY.md` for the full list):

- **Login throttle:** sign out and submit a wrong password ~10 times quickly →
  after 8/min you get HTTP 429 "Request was throttled," not unlimited attempts.
- **Least privilege on the calendar:** sign in as `val` (Viewer) and try to add a
  calendar event — the API refuses writes (403). As `mia` it succeeds.
- **Folder-ACL confidentiality:** as `val`, `GET /api/folder-permissions/` returns
  only grants on folders val can manage (empty for a plain Viewer), not the whole
  map.
- **CSV injection neutralised:** on your Profile, set your last name to `=1+1`,
  run an access review, export the CSV, and open it — the cell shows `'=1+1`
  as text, not a computed value.
- **Production guard:** set `DJANGO_DEBUG=false` in `.env` with the placeholder
  secret key and start the backend — it refuses to boot until you set a real
  `DJANGO_SECRET_KEY`. (Set `DJANGO_DEBUG=true` again for local testing.)

---

## 18 · Evidence ↔ control mapping

The reverse mapping answers "what evidence proves this control?" in both
directions. The demo data seeds **17 links across 15 controls** so it works
out of the box.

1. Sign in as `mia` → **Controls**. A new **Evidence** column shows a count
   pill per control (e.g. SOC 2 `CC6.1` shows `1 doc`; switch to ISO 27001 and
   `A.5.1` shows `2 docs` — the Information Security Policy *and* the PCI
   Information Security Policy both satisfy it).
2. Click a count pill → an evidence panel opens below the table listing each
   linked document with folder path, status, note, and who linked it.
3. **Bulk attach:** with the panel open, multi-select documents (Ctrl/Cmd-click)
   in "Attach evidence", add an optional note, click Attach. The pill count
   updates immediately and re-opening shows the new rows.
4. **Unlink** removes a row and decrements the pill.
5. Go to **Documents** → open the `CC6.1` folder. The Access Control Policy row
   shows chips (`CC6.1` `A.5.15` `7.1`) — one document satisfying three
   frameworks. Click **Map** on any row to open the editor: remove a chip with
   its ×, or pick "Link a control…" to add one (the select excludes controls
   already linked).
6. **Analytics** → the "Control status" card eyebrow now reads
   `15/217 have evidence` (rises as you link more).
7. **RBAC check:** sign in as `val` (Viewer). Counts and chips only reflect
   documents in folders val can see, and there is no Map button, no attach
   form, and no Unlink — the mapping API refuses val's writes (403).

---

## 19 · Risk register + CSV/XLSX import

The demo seeds **4 risks** covering every state: one *mitigating* with a Jira
key (MFA contractors, rated critical 16), one *open and overdue* (IR plan
review, high 12), one *open vendor* risk (moderate 8), one *closed* pen-test
finding.

1. Sign in as `mia` → **Risks**. The header chips read `3 live · 1 overdue ·
   2 high / critical · 1 closed`. The overdue row's due date is red.
2. Click a row → a detail drawer opens: description, editable status /
   treatment / likelihood / impact / owner / due / Jira fields, a mitigation
   plan with a Save button, and the notes thread. Add a note — the count in
   the table bumps.
3. Set the IR risk's status to **Closed** → the chips update and `closed_at`
   appears in the drawer header. Set it back to Open — `closed_at` clears.
4. **Import:** click *Import CSV/XLSX* and choose
   `docs/sample-risk-import.csv` → the result box reports **4 created,
   0 warnings** (word scales like "High", aliases like "Ticket", and control
   refs `CC6.1` / `A.5.18` all resolve; owners `owen`/`mia` match). Import the
   same file again → **0 created, 4 skipped** (duplicate titles).
   An .xlsx with the same columns imports identically.
5. **Template / Export:** *Template* downloads a starter CSV;
   *Export* downloads the full register (spreadsheet-injection-safe cells).
6. **Permissions:** as `owen` (Control Owner), the risks owned by owen are
   editable in the drawer but *New risk* / *Import* don't appear; as `val`
   (Viewer) everything is read-only and note-adding still works. A direct
   `POST /api/risks/` as val returns 403.

---

## 20 · User management (admin panel)

1. Sign in as `admin` (or `mia`) → **Users** in the Governance nav. The table
   lists all 5 demo accounts with role, last login, and status; a second card
   explains every role's capabilities.
2. **Create:** click *New user*, fill username `tess`, a role of Viewer, and a
   temporary password (8+ chars; the server enforces the password validators —
   try `short` to see the inline error). The new row appears immediately.
3. **Edit permissions:** change tess's role to *Control Owner* from the inline
   select — a confirmation banner appears. Note your own row's role select is
   disabled (you can't change your own role).
4. **Set password / deactivate:** use *Set password* on tess's row, then
   *Deactivate* — the badge flips to inactive and tess can no longer sign in.
   *Activate* restores it. **Delete** removes the row after a confirm.
5. **Lockout guards:** try to deactivate or delete your own account — the API
   refuses with a clear message. With only one active administrator, changing
   that admin's role away is also refused ("last active administrator").
   Superuser rows show a badge and can't be deleted through the API.
6. **Access gate:** sign in as `owen` or `val` and open /users — the page
   shows the capability-needed notice, and direct writes return 403.

---

## 21 · Two-factor authentication (TOTP) + dashboard cards

**Dashboard cards.** Sign in as `mia` → the Dashboard now shows two extra
cards below the top row: **Risk posture** (open + overdue risks from the
register — `3 open · 1 overdue` with the demo data) and **Evidence coverage**
(`7%` · 15/217 controls, with a progress bar and the link count). Both come
from `/analytics/summary/`.

**Enable MFA.** Still as `mia` → **Account → Security → Two-factor
authentication → Enable two-factor**. You'll get a setup key and an
`otpauth://` URI. Add it to any authenticator app (Google Authenticator,
Authy, 1Password) using the key, enter the 6-digit code, and confirm. You're
shown 10 **backup codes** once — download them.

**Re-login with MFA.** Sign out. Sign in with `mia`'s password → you're now
prompted for a code (the tokens aren't issued until it's verified). Enter the
authenticator code to finish. Try a wrong code first to see it rejected; try a
**backup code** to confirm single-use recovery works (it won't work twice).

**Manage / disable.** Back in Account → Security, regenerating backup codes or
turning MFA off both require your password.

**Admin reset (lockout recovery).** As `admin` → **Users**, `mia`'s row now
shows a `2FA on` badge and a **Reset 2FA** button. Reset it → `mia` can enroll
again on next sign-in. (Non-admins calling the endpoint get 403.)

**No effect on non-MFA users.** `owen`, `val`, `aria`, `admin` still log in
with just a password until they choose to enable it — MFA is per-user opt-in.

---

## 22 · Notification bell (per-account feed)

The bell in the top bar shows a feed computed for *you* — from what you own,
what's assigned to you, and your role's capabilities. Nothing is shared; each
person sees a different list.

1. Sign in as `owen` (Control Owner). The bell shows an unread count. Open it —
   because owen owns the seeded documents and risks, expect items like: *Review
   overdue: Incident Response Plan* (red), *Risk remediation overdue: IR plan
   review* (red), and *Review due soon: PCI Information Security Policy* /
   *User Access Provisioning* (amber). Each links to the relevant page when
   clicked.
2. Opening the tray marks everything read (the badge clears). Reload — the count
   stays cleared. Dismiss one with its × — it disappears and won't return.
3. Sign in as `mia` (Compliance Manager). Her feed is different: manager
   **digests** — *N risks overdue across the register*, *202 controls have no
   evidence linked*, *N documents overdue org-wide*, and *Meeting cadence
   behind: Risk Review* (she owns that series). She doesn't see owen's per-item
   document notices.
4. Sign in as `val` (Viewer) with no ownership — the bell is quiet ("You're all
   caught up"), confirming the feed is scoped to assigned parameters.
5. Verify persistence of dismissals across roles is per-user: what owen dismisses
   still shows for whoever else would see it.

Under the hood the feed is derived on each request (see
`backend/notifications/notifications.py`); only read/dismissed state is stored,
so the list always reflects the current state of the program.

---

## 23 · Theming (Blazor theme, dark mode, custom colours)

1. Sign in → **Account → Appearance**. Four theme cards: **Audit Ledger**
   (default light), **Ledger Dark**, **Blazor** (blue accent + the signature
   purple-gradient sidebar), and **Blazor Dark**. Click each → the whole app
   (sidebar, cards, tables, badges, calendar, charts) re-themes instantly.
2. **Custom accent:** click a preset swatch (Blue/Indigo/Violet/Rose…) or the
   colour picker → primary buttons, active nav, links, chips and highlights
   recolour live. Note success/warning/overdue badges stay fixed. **Reset
   accent** returns to the theme default.
3. **Persistence:** reload the page – your theme and accent survive (stored per
   browser); there's no flash of the wrong theme on load. It also applies to the
   **login page** (sign out to confirm).
4. In the static **app-preview.html**, the top bar has the same Theme dropdown +
   accent dots to preview all combinations without installing.

---

## 24 · Audit log viewer (+ dark-mode toggle, error safety)

1. Sign in as `admin` → **Audit log** (≣ in the Governance nav). ✓ The seeded
   trail shows who did what: role changes, evidence links, a revoked folder
   grant — with actor, action badge (create/update/delete), record, detail,
   and IP. Filter by action, record type, user, or time window; search free
   text; **Load more** pages through history.
2. Make a change anywhere (e.g. rename a document) → refresh the Audit log ✓ a
   new `update` entry appears automatically — the trail is written server-side
   by middleware on every mutating API call.
3. ✓ Read-only by design: there is no edit or delete anywhere on the page, and
   the API exposes no write methods. Sign in as `aria` (Auditor) → she can
   read it; as `owen` or `val` → the capability notice shows and the API
   returns 403.
4. **Dark-mode toggle:** the ◐ button in the top bar flips the current theme
   family between light and dark instantly (full picker remains in Account →
   Appearance). ✓ The choice persists on reload.
5. ✓ The browser tab now shows a favicon, and if a page ever hits a render
   error you get a recoverable "Something went wrong" card with Reload — not a
   blank screen.

---

## Reset to a clean slate

```bash
rm backend/db.sqlite3 && rm -rf backend/media
./install.sh
```

Re-seeding is idempotent — frameworks, folders, demo users, and documents are
recreated fresh.

## If something fails

| Symptom | Likely cause / fix |
|---|---|
| Blank page at :5173 | Backend not running — check the first terminal / start `manage.py runserver` |
| Login always fails | Seed didn't run: `cd backend && ../.venv/bin/python manage.py bootstrap_demo` |
| 401s after ~1 hour | Access token expired and refresh failed — sign in again |
| `test_mailbox` auth error | Use an app-specific password; enable IMAP on the account |
| Port in use | Stop the other process, or run the backend on `:8001` and update `vite.config.js` proxy |
