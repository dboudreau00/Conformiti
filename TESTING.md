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
- Sign in as `admin`. **Expect:** Dashboard; sidebar badges *Controls* (in
  progress count), *Risks* 3, *User audit* 1 (the seeded quarterly access
  review, still open with `val` pending).
- Enter a wrong password repeatedly. **Expect:** *Too many attempts* (HTTP 429)
  on the ninth sign-in request from your address inside one minute, counting
  the successful one above. The limit is `THROTTLE_LOGIN`, 8 a minute per
  client address, not per account. Wait a minute.
- Top bar: switch theme packs and accents. **Expect:** instant recolour,
  persisted on reload, applied to the login page too.

### 2 · Dashboard
**Expect:** *Readiness score* out of 100, and beneath it the share of
controls marked implemented, matching *Overall readiness* on *Analytics*;
Frameworks **3**; Documents **9**; Reviews overdue **1**; Risk posture *3 open
· 1 overdue*; Evidence coverage *20/217*. Calendar: the overdue *Incident
Response Plan* is red; filter chips narrow by type; clicking a day lists its
items. "Reviews coming up" lists the eight documents due within 120 days, most
urgent first, with **Mark reviewed**.

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
attach form. Set a control to *Implemented* → Dashboard's implemented count and
the sidebar badge update. **Export CSV** → `controls.csv` opens in a spreadsheet.

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
manageable grants (none). As `aria`: Audit log and User audit readable, every
write control absent.

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
no unreadable text, no white flashes. With the OS "reduce motion" setting on,
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
