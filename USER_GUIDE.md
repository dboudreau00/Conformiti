# Conformiti — user guide

How the platform is organised and how to use each screen day to day.
Installation lives in [INSTALL.md](INSTALL.md); a guided first hour in
[GETTING_STARTED.md](GETTING_STARTED.md).

---

## 1. Concepts

**Framework → category → control.** SOC 2, ISO/IEC 27001:2022 and PCI DSS
v4.0.1 ship pre-loaded (217 controls). Each control has a status (*not
started*, *in progress*, *implemented*, *not applicable*), an owner, and a
count of linked evidence. Readiness is *implemented ÷ applicable*.

**Folders and documents.** Evidence lives in a folder tree generated from the
control libraries (framework → category → control) plus any subfolders you
add. Access is granted per folder — by role or by user, at *view*, *edit* or
*manage* — and inherited down the tree. Documents carry a review cadence and a
next review date, which drive reminders.

**Evidence links.** A many-to-many mapping between controls and documents: one
Access Control Policy can satisfy `CC6.1`, `A.5.15` and `7.1`; one control can
cite many documents. Edit it from either side.

**Risks.** Register entries scored on a 5×5 likelihood × impact matrix (low /
moderate / high / critical), with status, treatment, owner, optional control
and Jira key, due date and a note trail.

**Access reviews.** Point-in-time snapshots of every account on which an
administrator records keep / modify / revoke — the periodic user-access review
SOC 2 and ISO expect. Export the grid as evidence.

**Audit trail.** Every change made through the API, plus every sign-in, failed
sign-in and sign-out, with actor, record, the fields touched and the IP.
Read-only by design.

**Readiness history.** A snapshot is recorded every day (and on the first
dashboard visit of a day). The dashboard's trend and month-over-month delta
come from those snapshots.

## 2. Roles

| Role | Can |
|---|---|
| **Administrator** | everything, including users, roles, access reviews, integrations |
| **Compliance Manager** | frameworks and control statuses, all folders and documents, risks, meetings, calendar; sees the whole tree |
| **Control Owner** | edit documents in folders granted to them; update risks they own; add minutes |
| **Auditor** | read-only: audit log, access reviews, and folders granted to them |
| **Viewer** | read-only in folders granted to them |

Capabilities are enforced by the API; the interface only shows write controls
where the API would accept them. Folder grants are managed on the Documents
page by anyone with *manage* on that folder.

## 3. The shell

- **Sidebar** — Workspace (Dashboard, Analytics, Controls, Documents) and
  Governance (Users, User audit, Audit log, Meetings, Groups, Risks, Jira);
  live badges show controls in progress, open risks and open access reviews.
- **Top bar** — page title, the **theme pack** picker (Audit Ledger, Nimbus,
  Ledger Dark, Obsidian), four **accent** dots, a version/demo label and the
  **notification bell**. Theme and accent are remembered per browser.
- **Notifications** are computed for *you*: documents and risks you own that
  are due or overdue, tasks assigned to you, meeting cadences you own that are
  behind; managers get org-wide digests; administrators and auditors see open
  access reviews. Opening the tray marks items read; × dismisses one.

## 4. Pages

### Dashboard
Overall readiness with the trend line and status bar; frameworks, documents
and overdue-review cards; evidence coverage; risk posture; the compliance
calendar (filter by Review / Audit / Task / Other, click a day for details,
arrows for other months); and "Reviews coming up" with **Mark reviewed**
(managers and owners with edit access).

### Analytics
Framework readiness bars, control and document status donuts, review load for
the next six months, ownership coverage (controls, documents, risks) and the
most overdue documents.

### Controls
Filter by framework and status, search by reference or title, **Export CSV**.
Expand a row for the objective, the status and owner selects (managers), the
linked evidence (with **Unlink** where you have edit rights on the document's
folder) and **Attach evidence** (multi-select, optional note). Bulk attach
reports anything it skipped and why.

### Documents
The folder tree on the left (keyboard: arrows to move and expand, Enter to
select). Select a folder to see its documents: status, review due, owner,
version and the controls each satisfies. With edit access: **Upload
document** (name, cadence, owner, file — up to 32 MB, no active-content
types), **Rename**, **Reviewed** (resets the review clock), **Version**
(archives the current file and bumps the version), **Map** (link/unlink
controls), **New subfolder**. With manage access: **Manage access** (grant a
role or a user view/edit/manage; remove grants) and **Delete folder** for
folders you created (framework folders are permanent).

### Risks
Chips filter live / closed / all; the toolbar offers a CSV template, **Import
CSV/XLSX** and **New risk** (managers) and **Export**. Select a row to edit
status, treatment, scores, owner, due date, Jira key and the mitigation plan
(managers, or the risk's owner) and to add notes (anyone). Import recognises
common column names (Title/Risk, Likelihood/Probability, Impact/Severity,
Owner, Control, Due date, Status, Notes…), word scales (High, Likely…), and
skips duplicates by title.

### Users *(administrators)*
Create accounts (temporary password of 12+ characters), assign roles, set
passwords, deactivate/activate, delete, reset a user's two-factor. The API
refuses self-lockout and will never leave the organisation without an active
administrator.

### User audit *(administrators; auditors read-only)*
**Start new review** snapshots every account (role, last login, folder grants,
capabilities). Record a decision and a note per row, **Export CSV**, then
**Complete review** — refused while any row is pending; completed reviews are
read-only evidence.

### Audit log *(administrators, auditors, view-all managers)*
Filter by action, record type, user and time window; search detail, record or
IP; **Load more** pages through history. Actions include `create`, `update`,
`delete`, `login`, `login_failed` (with the reason) and `logout`.

### Meetings
Series with a required cadence per year (steering committee quarterly, risk
review semi-annually…) and the minutes recorded against them. The status
badge compares minutes held this year with what the calendar demands so far.
Managers add series and record minutes (with an optional attachment).

### Groups
Champion groups with an accountable owner and members tagged by the
department they represent. Administrators manage membership.

### Jira *(optional)*
Administrators connect an Atlassian site (base URL, account email, API token —
stored server-side, never sent to the browser) and track boards by id;
everyone can read the tracked boards' issues. Only `https://` public hosts are
allowed.

### Vendors
The third-party register: tier, what they touch, the assurance on file with
its expiry, the shared responsibility matrix, and the security questionnaire.
**Send to the vendor** on the Questionnaire tab emails their contact a
personal link (valid 14 days by default); they answer in their browser, and
the result appears as *Returned by …* for you to mark satisfactory, exceptions
noted or unsatisfactory.

### Audit packages
Assemble the controls and evidence for an engagement, seal the package and
issue it to the auditor's account for a fixed period. The **Request list**
on each package is what the auditor has asked for: raise lines (or let the
auditor raise them), assign and date each one, attach the documents and mark
it *provided*; the auditor accepts or returns it. Lines assigned to you are
also listed on this page even if you cannot see the package itself.

### Settings
- **Profile** — name, email (where reminders go), job title.
- **Appearance** — theme packs, accent packs, a custom accent colour, live preview.
- **Security** — change password; enable two-factor (setup key or `otpauth://`
  URI for any authenticator app, one-time backup codes), regenerate codes or
  turn it off (password required); enrol **passkeys or security keys**, which
  then satisfy the second step instead of a code. A key flagged as possibly
  cloned is disabled — remove it with your password and enrol a fresh one.
- **Notifications** — how reminders reach you.
- **Role & access** — your capabilities.
- **About** — version, frameworks loaded, whether demo data is present.

## 5. Review reminders

Owners (and the compliance team address) are emailed at 30, 14, 7 and 1 days
before a document's review date and once when it goes overdue (which also
marks the document *expired*). Each window is sent once; **Mark reviewed** or
a new version resets the clock. In Docker the worker runs the scan daily at
`REVIEW_SCAN_HOUR`; elsewhere run `manage.py send_review_reminders` from cron.
Providers: console (default), SMTP, a standard IMAP/POP3 + SMTP mailbox
account, Amazon SES — see `.env.example`.

## 6. Administration cheat-sheet

```bash
manage.py createsuperuser              # first real administrator
manage.py remove_demo_data [--delete]  # retire the demo accounts and sample data
manage.py send_review_reminders [--dry-run]
manage.py record_readiness             # today's readiness snapshot (cron)
manage.py flushexpiredtokens           # prune the JWT blacklist (cron)
manage.py seed_frameworks --with-folders   # re-sync libraries after an upgrade (idempotent)
manage.py test_mailbox --to you@example.com
```

Prefix with `docker compose exec backend python` on the Docker path or
`../.venv/bin/python` from `backend/` on the local path.
