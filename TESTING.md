# Testing

Two layers: the automated gates (run them first) and a manual browser
walkthrough with exact expected values from the seeded demo data.

## Automated

```bash
./install.sh --test                                              # macOS / Linux / WSL
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Test     # Windows
```

Runs, in order: `tools/validate.py` (20 static checks), `manage.py check`,
`makemigrations --check`, the backend suite (by far the longest step on
SQLite), and a production frontend build. CI runs the same plus the
undeclared-name check on the frontend source, the installer runs on Windows
and Linux, the PostgreSQL job, `npm audit`, the Docker boot check, the compose
backup-and-restore rehearsal and the Playwright suite. Details:
[VALIDATION.md](VALIDATION.md).

To run one module or test:

```bash
cd backend
../.venv/bin/python manage.py test documents                       # one app
../.venv/bin/python manage.py test accounts.tests.MfaTests         # one class
```

## Manual walkthrough (~30 min)

Needs the demo dataset, which is **not** seeded by default: on the local path
use `./install.sh --demo` (Windows:
`powershell -ExecutionPolicy Bypass -File .\install.ps1 -Demo`) or
`manage.py bootstrap_demo`; on the Docker stack set `SEED_DEMO_DATA=true` in
`.env` or use `./install.sh --docker --demo`. All demo accounts share the
password the seeding step printed; set `DEMO_PASSWORD` before seeding to pin
it (it must meet the password policy). Seeded documents (owner Owen Owner):

| Document | Review due |
|---|---|
| Incident Response Plan | **3 days overdue** |
| PCI Information Security Policy | in 1 day |
| User Access Provisioning Procedure | in 6 days |
| Backup and Restore Procedure | in 12 days |
| Information Security Policy | in 20 days |
| Access Control Policy | in 45 days |
| Network Segmentation Standard | in 90 days |
| Penetration Test Report | in 120 days |
| Data Centre Badge Reader Photo | in 200 days |

Seeded risks: 4 (3 live · 1 overdue · 2 high/critical · 1 closed). Evidence
links: 22 across 20 controls. Meetings: Security Steering Committee 3/4,
Risk Review 1/2.

### 1 · Sign-in and shell
- Sign in as `admin`. **Expect:** Dashboard, its title at the top of the page
  and one bar above it: the tabs *Dashboard*, *Analytics*, *Controls* (a badge
  with the in-progress count) and *Documents*, then *Governance*. Open
  *Governance*. **Expect:** a two-column panel of the ten pages (Users, User
  audit, Audit packages, Vendors, Responsibility matrix, Audit log, Meetings,
  Champion groups, Risks, Jira) with the badges *Risks* 3 and *User audit* 1
  (the seeded quarterly access review, still open with `val` pending). The
  arrow keys step through the pages and **Esc** closes the panel and returns
  focus to its button. Open one: the button now reads *Governance* and that
  page's name.
- Enter a wrong password repeatedly. **Expect:** *Too many attempts* (HTTP 429)
  on the ninth sign-in request from your address inside one minute, counting
  the successful one above. The limit is `THROTTLE_LOGIN`, 8 a minute per
  client address, not per account. Wait a minute.
- Top bar → **Appearance**: switch theme packs and accents. **Expect:** instant
  recolour, persisted on reload, applied to the login page too.
- Account menu (your initials, top right). **Expect:** your name and role,
  *Settings* and *Sign out*.
- **Ctrl K** (**Cmd K** on a Mac), or the search field. Type `CC6.1`. **Expect:**
  a *Controls* group with `CC6.1`. Type `owen`: a *People* group with Owen
  Owner. Type `zzzz`: *Nothing matches*. **Up**, **Down**, **Enter** and **Esc**
  work. As `aria`: no *Controls* or *People* group, and no request to
  `/api/controls/` or `/api/users/` (an auditor is refused both).
- Keyboard: on a fresh page load the first **Tab** shows *Skip to content*;
  **Enter** moves focus to the page without changing the address.
- Widths. **Expect:** at 1366 by 768 and 1024 by 768 nothing scrolls sideways
  and no label overlaps another; under 768 pixels the tabs are replaced by a
  *Menu* button that opens a sheet listing Workspace, Governance and Account;
  at 1180 pixels or narrower the search field is an icon.

### 2 · Dashboard
**Expect:** the title *Dashboard* at the top of the page, not in the bar.
*Readiness score* out of 100, and beneath it the share of controls marked
implemented, matching *Overall readiness* on *Analytics*, the six-month trend
and the four readiness bands.

**Lead schedule**, beside it: three framework rows in name order and a *Total*
row (a single rule above it, a double rule below); the panel header says
3 frameworks.

| Row | Under the name: controls, not applicable | Applicable | Implemented | In progress | Not started | Evidence linked |
|---|---|---|---|---|---|---|
| ISO/IEC 27001 | 93, 3 | 90 | 27 | 19 | 44 | 7 |
| PCI DSS | 63, 3 | 60 | 17 | 13 | 30 | 6 |
| SOC 2 | 61, 2 | 59 | 18 | 12 | 29 | 7 |
| Total | 217, 8 | 209 | 62 | 44 | 103 | 20 |

*Readiness* is a score out of 100 on each row, not a percentage implemented,
and the *Total* row's *Readiness* equals the *Readiness score* above. *Evidence
linked* in the *Total* row equals the **20** in *Evidence coverage*.

**Coverage atlas**, full width: **217** squares in three groups (ISO/IEC 27001
93, PCI DSS 63, SOC 2 61); the legend counts *Implemented* 62, *In progress*
44, *Not started* 103, *Not applicable* 8. In progress is half filled and not
applicable is hatched. Point at `CC6.1` in the SOC 2 group (each square's
tooltip gives its reference, title and status). **Expect:** 12 other controls
light up with an accent ring across all three groups, including `A.5.15` and
`7.1`, and the rest dim; no lines are drawn. Select it (click, or **Enter**).
**Expect:** the light stays, and a place card shows `CC6.1`, SOC 2, *Not
started*, a readiness score and band, and *Also answers* with six partners
listed and "and 6 more". **Esc** clears the card and the light. **Tab** into
the atlas: it is one Tab stop, the arrow keys move inside it, and **Shift+Tab**
returns to the same square.

**Needs attention**: Reviews overdue **1** (4 due in the next 30 days), Risk
posture *3 open · 1 overdue*, Evidence coverage *20/217* (22 links), Documents
**9** on file (9 approved). Calendar: the overdue *Incident Response Plan* is
red; filter chips narrow by type; clicking a day lists its items. "Reviews
coming up" lists the eight documents due within 120 days, most urgent first,
with **Mark reviewed**.

### 3 · Analytics
**Expect:** three framework bars; donut centres **217** and **9**; review load
for the next six months; ownership *Documents with an owner 9/9*;
most-overdue list shows *3d*, *Incident Response Plan*, *Owen Owner*.

### 4 · Close the overdue review
Dashboard → **Mark reviewed** on *Incident Response Plan*. **Expect:** it leaves
the list, Reviews overdue → **0**, Analytics' overdue list is empty, the audit
log gains an `update` on `documents`.

### 5 · Controls
**Expect:** segmented control *All frameworks 217 · SOC 2 61 · ISO 27001 93 ·
PCI DSS 63*; status chips with counts. Search `CC6.1`, expand → objective,
selects (as admin), linked evidence *Access Control Policy* with **Unlink**,
attach form. Set a control to *Implemented* → the Dashboard's lead schedule
follows, that control's square in the atlas fills solid, and the badge on the
*Controls* tab moves if the control was or became *In progress*. **Export CSV** → `controls.csv` opens in a spreadsheet.

### 6 · Documents
Expand *SOC 2 → CC6 → CC6.1* using only the keyboard (Tab to the tree, arrows,
Enter). Upload "Test Evidence" (Quarterly, owner Owen, any small file) →
badge; **Rename**; **Version** → v2; **Reviewed** → date +3 months; **Map** →
link `A.5.15`. **Manage access** → grant *Viewer* → view; grant user `val` →
edit; remove one. Create subfolder "Q3 scans"; delete it. Try to upload
`evil.html` → refused with a clear message.

### 7 · Least privilege
As `val`: tree shows only granted folders; no upload/actions unless granted
edit; Risks has no *New risk*/*Import*; Calendar events can't be created
(`POST /api/calendar/` → 403); `GET /api/folder-permissions/` returns only
manageable grants (none). As `aria`: the bar offers one tab, *Documents*, and
*Governance* lists only *Audit packages*, *User audit* and *Audit log*; the
Dashboard link lands on *Audit packages*; Audit log and User audit readable,
every write control absent.

### 8 · Risks
As `mia`: chips *3 live · 1 overdue · 2 high/critical · 1 closed*. Open the IR
risk → set **Closed** (closed_at appears) → **Open** (cleared). Add a note.
Import `docs/sample-risk-import.csv` → *4 created, 0 warnings*; again → *0
created, 4 skipped*. Export → a cell whose first character, after any leading
whitespace, is `=`, `+`, `-` or `@` gets an apostrophe in front, so a
spreadsheet shows it as text instead of evaluating it.

### 9 · User audit
As `admin`: **Start new review** → 5 rows. Set decisions (Revoke turns red),
notes, **Export CSV**. **Complete review** stays disabled, with a count, while
any row is pending. Completing it deactivates every account marked Revoke and
ends its sessions. Your own row, superusers and accounts that are already
inactive or deleted are left as they are and listed afterwards, for you to
handle by hand. The grid then becomes read-only. Mark as Revoke only accounts
you do not need in the later steps (or none). As `aria`: read-only view.

### 10 · Meetings · Groups · Jira
Meetings: *Security Steering Committee* on track, *Risk Review* behind; record a
minute → counts update; attach a >32 MB file → refused. Groups: add and remove
a champion (adding the same user twice → clear error). Jira: without
credentials a clear empty state; with them, *Test connection* reports the
account name and a tracked board lists issues.

### 11 · Users
Create `tess` (role Viewer, password ≥ 12 chars; `short` → inline error).
Change role, set password, deactivate/activate, delete. Lockout guards refuse
self-deactivation, self-deletion and stripping the last administrator.

### 12 · Two-factor authentication
As `mia`: Settings → Security → enable (you are asked to confirm your
password), confirm a code, save the 10 backup codes. Sign out/in → code
prompt; wrong code rejected; a backup code works once. Regenerating the backup
codes and disabling ask for the password, or a current code from the
authenticator app, or an unused backup code. As `admin`: **Reset 2FA**.

### 13 · Sign-out revokes the session
Cookie mode is the default, so the refresh token is an HttpOnly cookie that
page script cannot read. Sign in, then in DevTools → Application → Cookies
copy the value of `conformiti_refresh` (`__Secure-conformiti_refresh` when
`BEHIND_TLS` is true). Sign out, and confirm the cookie is gone and that
reloading does not sign you back in. To check the server side, wait for the
access cookie to expire (60 minutes unless `JWT_ACCESS_MINUTES` says
otherwise), sign out, then send the copied value as `{"refresh": "..."}` to
`POST /api/auth/token/refresh/`, with the CSRF cookie and a matching
`X-CSRFToken` header. **Expect:** 401 with *Token is blacklisted*, which is
what 0.9.5b fixed. Without the CSRF token the endpoint answers 403, and
without a refresh value 400. With `AUTH_TRANSPORT=header` the tokens are in
Local Storage and can be replayed directly.

### 14 · Audit log
As `admin`: entries for your sign-ins, the failed attempts from step 1 (with
reason), sign-outs, and every change above with `fields=…`. Filters, search,
Load more. No write controls; `DELETE /api/audit-log/1/` → 405.

### 15 · Reminders
`manage.py send_review_reminders --dry-run` → *would be notified: N*; real run
prints the emails (console provider); second run → 0.

### 16 · Docker path
`./install.sh --docker --demo` → healthy in < 4 minutes on a laptop;
`http://localhost:8080/api/health/` → `status ok`, `demo_accounts true`;
`docker compose exec backend python manage.py createsuperuser` (your own
administrator: `remove_demo_data` refuses until one exists), then
`docker compose exec backend python manage.py remove_demo_data` → the login
page stops showing the demo hint and `demo_accounts` is `false`. Without
`--demo` the dataset is never created and `demo_accounts` is `false` from the
start, which is what a real deployment gets.

### 17 · Themes and reduced motion
Repeat the Dashboard and Documents checks in **Obsidian** and **Audit Ledger**:
no unreadable text, no white flashes, and on the Dashboard the lit ring, the
dimmed squares, the half-filled and hatched statuses and the double rule under
the schedule's *Total* stay distinguishable. With the OS "reduce motion" setting on,
panels appear without animation.

## Reset to a clean slate

```bash
./install.sh --reset               # local path
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Reset   # local path, Windows
docker compose down -v && docker compose up -d --build   # Docker (destroys data)
```

On Docker, `down -v` removes every volume: the database and the uploads, and
also the `secrets` volume, which holds the Django secret key, the
field-encryption keys and the package-signing key. The next start generates
new ones, so the installation signs packages with a new key.

On the published images, give `up` the same `-f` files you started with, or it
builds from source ([INSTALL.md](INSTALL.md), *Without a build*).
