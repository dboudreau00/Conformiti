# Conformiti user guide

How the platform is organised and how to use each screen day to day.
Installation lives in [INSTALL.md](INSTALL.md); a guided first hour in
[GETTING_STARTED.md](GETTING_STARTED.md).

---

## 1. Concepts

**Framework → category → control.** SOC 2, ISO/IEC 27001:2022 and PCI DSS
v4.0.1 ship pre-loaded (217 controls). Each control has a status (*not
started*, *in progress*, *implemented*, *not applicable*), an owner, and a
count of linked evidence. Readiness is *implemented ÷ applicable* (Analytics'
*Overall readiness*); the Dashboard leads with the *readiness score*, the mean
of every applicable control's own score out of 100 (implementation, an owner,
evidence and its freshness, a test, less open risks).

**Folders and documents.** Evidence lives in a folder tree generated from the
control libraries (framework → category → control) plus any subfolders you
add. Access is granted per folder (by role or by user, at *view*, *edit* or
*manage*) and inherited down the tree. Documents carry a review cadence and a
next review date, which drive reminders.

**Evidence links.** A many-to-many mapping between controls and documents: one
Access Control Policy can satisfy `CC6.1`, `A.5.15` and `7.1`; one control can
cite many documents. Edit it from either side.

**Risks.** Register entries scored on a 5×5 likelihood × impact matrix (low /
moderate / high / critical), with status, treatment, owner, optional control
and Jira key, due date and a note trail.

**Access reviews.** Point-in-time snapshots of every account on which an
administrator records keep / modify / revoke: the periodic user-access review
SOC 2 and ISO expect. Export the grid as evidence.

**Audit trail.** Every successful change made through the API (apart from each
person's own notification tray), with the actor, the record, the names of the
fields sent (never their values) and the IP; every sign-in, failed sign-in and
sign-out through the application and single sign-on; every download or
preview of evidence; and the evidence-package events (seal, issue, withdraw,
export). Changes saved in the Django admin at `/admin/` and sign-ins to it
are recorded too. Read-only by design: nobody, a superuser included, edits or
deletes an entry, in the application or in the Django admin. Keep `/admin/`
reachable only by the people who need it.

**Readiness history.** A snapshot is recorded every day (and on the first
dashboard visit of a day). The dashboard's trend and month-over-month delta
come from those snapshots.

**Workspaces.** One installation can serve several organisations, each a
workspace with its own users, roles, folders, documents, risks and audit
trail. Everything in this guide happens inside your workspace, and an
Administrator manages that workspace only. A superuser is an installation
account: it creates and archives workspaces and can switch into any of them,
and what it does there is recorded in that workspace's audit log.

## 2. Roles

| Role | Can |
|---|---|
| **Administrator** | everything, including users, roles, access reviews, integrations |
| **Compliance Manager** | frameworks and control statuses, all folders and documents, risks, meetings, calendar; sees the whole tree |
| **Control Owner** | edit documents in folders granted to them, and documents they own; update risks they own; add, edit and delete meeting series and minutes, and, through the API, calendar events and form templates |
| **Auditor** | the outside party: packages issued to them while their grant is live, the folders granted to them (or to the Auditor role), their own request list, access reviews and the workspace's whole audit log, and nothing else of the programme |
| **Viewer** | read the documents in folders granted to them and the programme-wide records listed below; add notes to risks; edit a risk they are named owner of |

Folder grants limit documents only. Every signed-in account except the Auditor
reads the programme-wide records: the control library, the risk register and
its export, vendors, the responsibility matrix, meetings and their minutes,
champion groups, the calendar, analytics, the tracked Jira boards and the user
directory (names, email addresses, roles, last sign-in, and whether two-factor
is on). The capability flags decide who may change them. Give someone outside
the organisation the Auditor role, never Viewer.

An auditor's folder access is separate from the package grant. Folder grants
are read-only, do not expire and do not end when the package's grant does, and
a grant to the Auditor role reaches every auditor account in the workspace.
Grant folders to the named auditor, and remove them when the engagement
closes.

Capabilities are enforced by the API; the interface only shows write controls
where the API would accept them. Folder grants are managed on the Documents
page by anyone with *manage* on that folder.

## 3. The shell

One bar runs across the top of every page, and nothing runs down the side.
The page's own title and a line about it open the page, under the bar.

- **Workspace tabs**: Dashboard, Analytics, Controls and Documents. The page
  you are on has an accent underline. A live badge on Controls counts the
  controls in progress.
- **Governance**: a menu holding the ten governance pages (Users, User audit,
  Audit packages, Vendors, Responsibility matrix, Audit log, Meetings,
  Champion groups, Risks, Jira), two to a row, each with its icon, a line on
  what it is for and, where there is one, a live badge (open access reviews,
  open risks). When you are on one of those pages the button also names it,
  so the bar still says where you are with the menu closed.
- **Search**: press **Ctrl K** (**Cmd K** on a Mac) or select the search
  field. Type two or more characters and the palette lists the controls,
  documents and people that match, up to six of each, the best match first.
  **Up** and **Down** move, **Enter** goes to the page that holds the result,
  **Esc** closes. It asks only for what your role may list, so an auditor is
  offered documents and nothing else, and people appear only for accounts that
  can read the user directory.
- **Appearance**: the four **theme packs** (Audit Ledger, Nimbus, Ledger Dark,
  Obsidian), each with a swatch and a line describing it, and four **accent**
  colours. Choosing one recolours the page at once and the menu stays open so
  a pack and an accent can be tried together. Theme and accent are remembered
  per browser; a custom accent colour and **Reset** are on the Settings page.
- **Notification bell** and the **account menu**: your name and role, the
  workspace you are working in where it is not the installation's default (a
  superuser who has switched into another organisation's workspace is always
  told), **Settings** and **Sign out**. The bar also carries a demo and
  version label where there is room for it.
- **Keyboard and narrow screens**: **Skip to content** is the first Tab stop on
  every page. Every menu opens with **Enter** or **Space** on its button (the
  Appearance and account menus also with an arrow key), moves with the arrow
  keys, closes with **Esc** and hands focus back to its button. Under 768
  pixels the tabs fold into one **Menu** button that opens a sheet listing
  every section, and at 1180 pixels or narrower the search field is an icon.
- **A left side menu** appears only when the navigation holds sections the core
  does not define, which an add-on can contribute. It collapses to an icon
  rail, and without such sections there is none.
- **An auditor** sees one tab, Documents, a Governance menu of Audit packages,
  User audit and Audit log, and Settings in the account menu.
- **Notifications** are computed for *you*: documents and risks you own that
  are due or overdue, tasks assigned to you, meeting cadences you own that are
  behind; managers get org-wide digests; administrators and auditors see open
  access reviews. Opening the tray marks items read; × dismisses one.

## 4. Pages

### Dashboard
**Readiness score** (out of 100, the mean of the applicable controls' scores)
with the share of controls marked implemented, the monthly trend line and
the readiness bands (Ready, Nearly there, At risk, Not ready), beside the
**lead schedule**. Under them, the **coverage atlas**, then **Needs
attention**, the compliance calendar and "Reviews coming up". A panel that
cannot be loaded says so and offers a retry, and the rest of the page still
shows.

**Lead schedule.** One row per framework: its name and version, how many
controls it has and how many of those are marked not applicable, then
*Applicable*, *Implemented*, *In progress*, *Not started*, *Evidence linked*
and *Readiness*. A framework's *Readiness* is its own score out of 100, the
mean score of its applicable controls as the headline is for the whole
programme. It is not the share marked implemented. The **Total** row is
footed to the programme: it quotes the dashboard's own figures rather than
adding rounded rows, so *Evidence linked* matches the evidence coverage
figure and *Readiness* matches the readiness score. A framework's name opens
the Controls page. With more than six frameworks the schedule shows six and a
**Show all** button.

**Coverage atlas.** Every control is one small square, grouped into one
territory per framework in the schedule's order and, inside each, in the
register's order. The fill is the status: implemented solid, in progress half
filled, not started an empty outline, not applicable hatched, so the four read
apart without colour, and the legend counts each. Controls that answer the
same crosswalk theme are partners: point at a square, or move to it with the
arrow keys, and every partner in any framework lights up with an accent ring
while the rest dim a little. There are no lines between squares.

- **Select** a square (click, or **Enter**) to pin the light and open its place
  card: the reference, title, framework and status, the control's readiness
  score and band, **Also answers** (the partners, up to six listed and then
  "and N more") and **Open control**, which goes to the Controls page. Select a
  listed partner to move the pin to it. **Esc**, or **Clear**, lets go.
- **From the keyboard** the whole field is one Tab stop. The arrow keys move
  inside it, **Home** and **End** go to the start and end of a framework,
  **Page Up** and **Page Down** to the neighbouring framework, and **Ctrl
  Home** and **Ctrl End** to the first and last control. Each square is named
  with its reference, title and status.
- **A large programme** shrinks the squares to a floor of nine pixels. Above
  600 controls the atlas draws the four frameworks with the most applicable
  controls and offers a chip per framework to draw the others, or **Draw all**.
- **The place card's score** is the one the register shows you, which counts
  only evidence in folders you can see. The schedule and the headline count
  every folder, so for someone with narrow folder access the two can differ.

**Needs attention** has four cells. *Reviews overdue* gives the count, how many
fall due in the next 30 days and a link to the review queue. *Risk posture*
gives open, mitigating and accepted risks and how many are overdue. *Evidence
coverage* gives the share of controls with at least one document linked, as a
bar, and the number of links. *Documents* gives how many are on file and how
many are approved, in review and expired. A figure whose source could not be
loaded shows a dash, not a zero.

The compliance calendar (filter by Review / Audit / Task / Other, click a day
for details, arrows for other months) and "Reviews coming up" with **Mark
reviewed** (managers and owners with edit access) close the page.

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
document** (name, cadence, owner and a file of up to 32 MB by default, set by
`MAX_UPLOAD_MB`), **Rename**, **Reviewed** (resets the review clock),
**Version** (archives the current file and bumps the version), **Map**
(link/unlink controls), **New subfolder**. Files a browser would run (HTML,
SVG, scripts, executables), macro-enabled and legacy Office formats (`.docm`,
`.xlsm`, `.doc`, `.xls`, `.ppt`, `.rtf` and similar) and Office files carrying
macros or embedded objects are refused: save as PDF, or as `.docx`, `.xlsx` or
`.pptx` without macros, instead. With malware scanning on, uploaded files are
scanned first and refused while the scanner cannot be reached. With manage
access: **Manage access** (grant a role or a user view/edit/manage; remove
grants) and **Delete folder** on any folder that is not a framework folder
(framework folders are permanent). Deleting a folder deletes its subfolders,
their documents and every archived version, and cannot be undone.
Administrators and Compliance Managers hold manage on every folder.

### Risks
Chips filter live / closed / all; the toolbar offers a CSV template, **Import
CSV/XLSX** and **New risk** (managers) and **Export**. Select a row to edit
status, treatment, scores, owner, due date, Jira key and the mitigation plan
(managers, or the risk's owner) and to add notes (anyone). Import recognises
common column names (Title/Risk, Likelihood/Probability, Impact/Severity,
Owner, Control, Due date, Status, Notes…), word scales (High, Likely…), and
skips duplicates by title.

### Users *(administrators)*
Create accounts with an initial password that passes the password policy (at
least `PASSWORD_MIN_LENGTH` characters, 12 by default; the form requires one).
The person is not made to change it at first sign-in, so hand it over safely
and ask them to change it under Settings, Security. Through the API, an
account created with no password gets a random one nobody is shown, which
suits accounts that sign in through single sign-on. You can also assign roles,
set passwords, deactivate/activate, delete, reset a user's two-factor. The API
refuses self-lockout and will never leave the organisation without an active
administrator.

### User audit *(administrators; auditors read-only)*
**Start new review** snapshots every account (role, last login, folder grants,
capabilities). Record a decision and a note per row, **Export CSV**, then
**Complete review**, which is refused while any row is pending. Completing
deactivates every account marked Revoke and signs it out of its sessions. It
skips your own account, superusers, accounts already inactive and accounts
since deleted, and lists each skipped row on screen with the reason. Completed
reviews are read-only evidence.

### Audit log *(administrators, auditors, view-all managers)*
Filter by action, record type, user and time window; search detail, record or
IP; **Load more** pages through history. Actions include `create`, `update`,
`delete`, `login`, `login_failed` (with the reason) and `logout`.

### Meetings
Series with a required cadence per year (steering committee quarterly, risk
review semi-annually…) and the minutes recorded against them. The status
badge compares minutes held this year with what the calendar demands so far.
Anyone whose role manages documents (Administrator, Compliance Manager,
Control Owner) adds, edits and deletes series and records minutes (with an
optional attachment).

### Groups
Champion groups with an accountable owner and members tagged by the
department they represent. Administrators manage membership.

### Jira *(optional)*
Administrators connect an Atlassian site (base URL, account email, API token,
stored server-side and never sent to the browser) and track boards by id;
everyone can read the tracked boards' issues. Only `https://` public hosts are
allowed.

### Vendors
The third-party register: tier, what they touch, the assurance on file with
its expiry, the shared responsibility matrix, and the security questionnaire.
**Send to the vendor** on the Questionnaire tab emails their contact a link
(valid 14 days by default, up to 90); they answer in their browser without an
account, and the result appears as *Returned by …* for you to mark
satisfactory, exceptions noted or unsatisfactory. The link itself is the
credential: whoever holds it can answer until it is submitted, revoked or
expires, so revoke it if it goes to the wrong person. Unless the installation
runs with DEBUG on, sending needs `PUBLIC_URL` set, because the link is built
from it.

### Responsibility matrix
Who is Responsible, Accountable, Consulted and Informed for each control,
people and vendors alike. A control's owner shows as its Accountable until
someone is named, and a vendor that states it does or shares a control on its
shared responsibility matrix shows as Responsible. A control has one
Accountable party at most. Everyone except an auditor can read the grid;
framework managers (Administrator, Compliance Manager) edit it.

### Audit packages
Assemble the controls and evidence for an engagement, seal the package and
issue it to the auditor's account for a fixed period. The **Request list**
on each package is what the auditor has asked for: raise lines (or let the
auditor raise them), assign and date each one, attach the documents and mark
it *provided*; the auditor accepts or returns it. Lines assigned to you are
also listed on this page even if you cannot see the package itself.

### Settings
- **Profile**: name and job title. Your email is shown but not editable:
  it is where reminders go, and it is what single sign-on matches on, so
  changing it is an administrator's job rather than a preference. Ask one, at
  *Users*, and the change is recorded.
- **Appearance**: theme packs, accent packs, a custom accent colour, live preview.
- **Security**: change password; enable two-factor (setup key or `otpauth://`
  URI for any authenticator app, one-time backup codes), regenerate codes or
  turn it off; enrol **passkeys or security keys**, which then satisfy the
  second step instead of a code. A key flagged as possibly cloned is disabled;
  remove it and enrol a fresh one.

  Every one of those asks you to confirm the account is yours first: your
  password, or a code from a factor you already hold (an authenticator code
  or a backup code). Changing which factors can sign you in is itself a
  security change, and somebody who has taken over a session must not be able
  to make their authenticator the one you need. One case has nothing to
  confirm with: an account with no password here and no factor yet, which is
  how an account created through your organisation's identity provider
  starts. Its first factor is enrolled without this step, so enrol one
  promptly. From then on an authenticator code, or one of the backup codes
  issued with your first factor, answers instead of a password.
- **Notifications**: how reminders reach you.
- **Role & access**: your capabilities, and the workspace you are in (a
  superuser creates, switches and archives workspaces here, and sets each
  workspace's notification inbox and Slack and Teams webhooks).
- **About**: version, frameworks loaded, whether demo data is present.

## 5. Review reminders

Owners (and the compliance team address) are emailed at 30, 14, 7 and 1 days
before a document's review date and once when it goes overdue (which also
marks the document *expired*). Each window is sent once; **Mark reviewed** or
a new version resets the clock. In Docker the `beat` service schedules the
scan daily at `REVIEW_SCAN_HOUR` and the worker runs it; elsewhere run
`manage.py send_review_reminders` from cron.
Providers: console (what `.env.example` and the Docker stack set; it prints
mail and delivers nothing), SMTP, a standard IMAP/POP3 + SMTP mailbox account,
Amazon SES (see `.env.example`). With `DJANGO_DEBUG=false` and no
`EMAIL_PROVIDER` at all, the default is SES, so set it explicitly.

## 6. Administration cheat-sheet

```bash
manage.py createsuperuser              # first real administrator (the password policy applies)
manage.py remove_demo_data [--delete]  # retire the demo accounts, sample data and demo control statuses (after createsuperuser)
manage.py send_review_reminders [--dry-run]
manage.py record_readiness             # today's readiness snapshot (cron)
manage.py flushexpiredtokens           # prune the JWT blacklist (cron)
manage.py seed_frameworks --with-folders --all-workspaces   # re-sync libraries after an upgrade, in every workspace (idempotent; without the flag, Default only)
manage.py test_mailbox --to you@example.com   # sample reminder through EMAIL_PROVIDER (mailbox: sign-in checked first)
manage.py rotate_signing_key           # new package-signing key; sealed packages keep verifying
manage.py rotate_field_keys            # re-encrypt stored secrets under the newest field-encryption key
manage.py link_oidc_identity <username> <subject>   # link a single sign-on identity by hand (--unlink removes it)
```

Prefix with `docker compose exec backend python` on the Docker path or
`../.venv/bin/python` from `backend/` on the local path.
