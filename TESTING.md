# Testing

Two layers: the automated gates (run them first) and a manual browser
walkthrough with exact expected values from the seeded demo data.

## Automated

```bash
./install.sh --test            # Windows: .\install.ps1 -Test
```

Runs, in order: `tools/validate.py` (15 static checks), `manage.py check`,
`makemigrations --check`, the backend suite (**80 tests**, ~90 s on SQLite),
and a production frontend build. CI runs the same plus the PostgreSQL job,
`npm audit` and the Docker boot check. Details: [VALIDATION.md](VALIDATION.md).

To run one module or test:

```bash
cd backend
../.venv/bin/python manage.py test documents                       # one app
../.venv/bin/python manage.py test accounts.tests.MfaTests         # one class
```

## Manual walkthrough (~30 min)

All demo accounts use `DemoPass123!`. Seeded documents (owner Owen Owner):

| Document | Review due |
|---|---|
| Incident Response Plan | **3 days overdue** |
| PCI Information Security Policy | in 1 day |
| User Access Provisioning Procedure | in 6 days |
| Backup and Restore Procedure | in 12 days |
| Information Security Policy | in 20 days |
| Access Control Policy | in 45 days |
| Network Segmentation Standard | in 90 days |

Seeded risks: 4 (3 live · 1 overdue · 2 high/critical · 1 closed). Evidence
links: 17 across 15 controls. Meetings: Security Steering Committee 3/4,
Risk Review 1/2.

### 1 · Sign-in and shell
- Sign in as `admin`. **Expect:** Dashboard; sidebar badges *Controls* (in
  progress count), *Risks* 3, *User audit* (open reviews, 0 until you start one).
- Enter a wrong password 9 times quickly. **Expect:** the 9th attempt says
  *Too many attempts* (HTTP 429). Wait a minute.
- Top bar: switch theme packs and accents. **Expect:** instant recolour,
  persisted on reload, applied to the login page too.

### 2 · Dashboard
**Expect:** readiness percentage matching *Analytics*; Frameworks **3**;
Documents **7**; Reviews overdue **1**; Risk posture *3 open · 1 overdue*;
Evidence coverage *15/217*. Calendar: the overdue *Incident Response Plan* is
red; filter chips narrow by type; clicking a day lists its items. "Reviews
coming up" lists the seven documents most urgent first with **Mark reviewed**.

### 3 · Analytics
**Expect:** three framework bars; donut centres **217** and **7**; review load
for six months (current month ≥ 3); ownership *Documents with an owner 7/7*;
most-overdue list shows *Incident Response Plan — 3d — Owen Owner*.

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
created, 4 skipped*. Export → cells starting with `=` are quoted.

### 9 · User audit
As `admin`: **Start new review** → 5 rows. Set decisions (Revoke turns red),
notes, **Export CSV**, **Complete review** (refused with a count while any row
is pending; grid becomes read-only after). As `aria`: read-only view.

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
As `mia`: Settings → Security → enable, confirm a code, save the 10 backup
codes. Sign out/in → code prompt; wrong code rejected; a backup code works
once. Regenerate/disable require the password. As `admin`: **Reset 2FA**.

### 13 · Sign-out revokes the session
Sign in, copy the `refresh` token from DevTools → Application → Local Storage,
sign out, then `POST /api/auth/token/refresh/` with it → **401**.

### 14 · Audit log
As `admin`: entries for your sign-ins, the failed attempts from step 1 (with
reason), sign-outs, and every change above with `fields=…`. Filters, search,
Load more. No write controls; `DELETE /api/audit-log/1/` → 405.

### 15 · Reminders
`manage.py send_review_reminders --dry-run` → *would be notified: N*; real run
prints the emails (console provider); second run → 0.

### 16 · Docker path
`./install.sh --docker` → healthy in < 4 minutes on a laptop;
`http://localhost:8080/api/health/` → `status ok`, `demo_accounts true`;
`docker compose exec backend python manage.py remove_demo_data` → the login
page stops showing the demo hint and `demo_accounts` is `false`.

### 17 · Themes and reduced motion
Repeat the Dashboard and Documents checks in **Obsidian** and **Audit Ledger**:
no unreadable text, no white flashes. With the OS "reduce motion" setting on,
panels appear without animation.

## Reset to a clean slate

```bash
./install.sh --reset               # local path
docker compose down -v && docker compose up -d --build   # Docker (destroys data)
```
