<div align="center">

# Conformiti

**Self-hosted GRC for SOC 2, ISO/IEC 27001:2022 and PCI DSS v4.0.1 — controls, evidence, documents, risks and access reviews in one audit-ready workspace.**

[![CI](https://github.com/dboudreau00/Conformiti/actions/workflows/ci.yml/badge.svg)](https://github.com/dboudreau00/Conformiti/actions/workflows/ci.yml)
[![Release](https://img.shields.io/badge/release-v0.4.1-2563d8.svg)](CHANGELOG.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.11%E2%80%933.13-3776AB?logo=python&logoColor=white)
![Django](https://img.shields.io/badge/Django-5.2%20LTS-092E20?logo=django&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![Docker](https://img.shields.io/badge/Docker-one%20command-2496ED?logo=docker&logoColor=white)

<img src="assets/screenshots/dashboard.png" alt="Conformiti dashboard — readiness, evidence coverage, risk posture, compliance calendar" width="900">

</div>

---

## Sixty-second install

```bash
git clone https://github.com/dboudreau00/Conformiti.git && cd Conformiti
docker compose up -d --build
```

Open **http://localhost:8080** and sign in as `admin` / `DemoPass123!`.
That is the whole install: PostgreSQL, Redis, the API, the reminder worker and
nginx come up with production-safe defaults (DEBUG off, a unique secret key
generated on first boot, rate limits in Redis, the API reachable only through
nginx). No `.env` is required.

Prefer a script that also waits for the stack to report healthy and prints the
URLs?

```bash
./install.sh --docker          # macOS / Linux / WSL
.\install.ps1 -Docker          # Windows PowerShell
```

Before real use, retire the demo accounts:

```bash
docker compose exec backend python manage.py createsuperuser
docker compose exec backend python manage.py remove_demo_data
```

Local development without Docker (SQLite, console email) is one command too:
`./install.sh` or `.\install.ps1` — see [INSTALL.md](INSTALL.md).

---

## What you get

<table>
  <tr>
    <td><img src="assets/screenshots/controls.png" alt="Control register" width="440"></td>
    <td><img src="assets/screenshots/analytics.png" alt="Analytics" width="440"></td>
  </tr>
  <tr>
    <td align="center"><sub>217 controls with inline status, owners and linked evidence</sub></td>
    <td align="center"><sub>Framework readiness, status mix, review load and ownership coverage</sub></td>
  </tr>
  <tr>
    <td><img src="assets/screenshots/documents.png" alt="Documents" width="440"></td>
    <td><img src="assets/screenshots/risks.png" alt="Risk register" width="440"></td>
  </tr>
  <tr>
    <td align="center"><sub>Evidence tree segregated by control, review cadences, versions, grants</sub></td>
    <td align="center"><sub>5×5 risk register with treatment, owners, notes and CSV/XLSX import</sub></td>
  </tr>
  <tr>
    <td><img src="assets/screenshots/access-reviews.png" alt="Access reviews" width="440"></td>
    <td><img src="assets/screenshots/audit-log.png" alt="Audit log" width="440"></td>
  </tr>
  <tr>
    <td align="center"><sub>Periodic user access reviews exported as audit evidence</sub></td>
    <td align="center"><sub>Immutable trail of every change and sign-in</sub></td>
  </tr>
  <tr>
    <td><img src="assets/screenshots/vendors.png" alt="Vendor register and shared responsibility matrix" width="440"></td>
    <td><img src="assets/screenshots/responsibility-matrix.png" alt="RACI responsibility matrix" width="440"></td>
  </tr>
  <tr>
    <td align="center"><sub>Vendors: assurance on file and a shared responsibility matrix, typed, prompted or imported</sub></td>
    <td align="center"><sub>RACI per control, for people and vendors, with the gaps counted</sub></td>
  </tr>
  <tr>
    <td><img src="assets/screenshots/viewer.png" alt="Evidence opened in the browser" width="440"></td>
    <td><img src="assets/screenshots/audit-packages.png" alt="Audit packages" width="440"></td>
  </tr>
  <tr>
    <td align="center"><sub>PDF, image, Word and Excel evidence opened in the browser, with its digest</sub></td>
    <td align="center"><sub>Sealed evidence packages issued to a named auditor</sub></td>
  </tr>
</table>

### Frameworks and controls
- **Three complete control libraries** — SOC 2 (61), ISO/IEC 27001:2022 (93),
  PCI DSS v4.0.1 (63) — with a cross-framework crosswalk, per-control status
  and owner, and a CSV export of the register.
- **Evidence ↔ control mapping** in both directions: one policy can satisfy
  `CC6.1`, `A.5.15` and `7.1` at once; bulk-attach during audit prep.
- **Readiness that is measured, not drawn.** Daily snapshots feed the
  dashboard trend and month-over-month delta.

### Documents and evidence
- **Folder tree segregated by control**, generated on disk and mirrored in the
  app; per-folder grants (by role or user) inherited down the tree.
- **Document lifecycle** — versions, rename, move, mark-reviewed; review
  cadences from monthly to biennial.
- **Review reminders** emailed to owners and the compliance team at
  configurable lead times and once when overdue, deduplicated per window.
- **Open in browser.** PDFs and images stream inline after a magic-byte
  check; Word and Excel are parsed on the server and rendered as structure,
  never as HTML from the file. The wrapper shows the version, the controls it
  satisfies and a SHA-256 computed in the browser — the same digest a sealed
  audit package records.

### Third parties and shared responsibility
- **Vendor register** with tier, data handled, owner and a review clock;
  **assurance on file** — SOC 2 reports, ISO certificates, PCI AOCs, pen
  tests, DPAs, a copy of their own responsibility matrix — with expiry
  tracking, plus a built-in security questionnaire. Posture and risk rating
  are computed from what is on file, not typed.
- **Shared responsibility matrix per vendor** — provider / customer / shared
  with a statement each side, over every control in scope. Type it, be walked
  through the unstated controls, or **import the vendor's own CSV/XLSX**: the
  columns and values are recognised in the layouts vendors actually send, and
  nothing is written until you confirm what it read.
- **RACI matrix** per control for people *and* vendors, with the control
  owner as implied Accountable and a vendor's matrix as implied Responsible;
  exactly one Accountable, and the gaps counted.
- **Onboarding prompts** in the notification tray when a vendor has no
  matrix, a report is about to lapse, or a review falls due — and a
  **bridge-letter reminder**, in the tray and by email, when a SOC report has
  lapsed with nothing newer on file.
- **Export in their layout**: the stated matrix goes back to the vendor under
  the column headers of the file they sent.

### Governance
- **Risk register** — likelihood × impact, treatment, due dates, Jira keys, a
  note trail, CSV/XLSX import and CSV export.
- **User access reviews** — snapshot every account into a decision grid, record
  keep/modify/revoke, export the evidence.
- **Meeting cadences** with required-per-year tracking, **champion groups**,
  optional **Jira** board visibility.
- **Immutable audit trail** — every change, sign-in, failed sign-in and
  sign-out, with actor, record, changed fields and IP.

### Security and access
- **TOTP two-factor auth** with backup codes and admin reset; **rotating,
  revocable refresh tokens**; per-client login throttles shared across workers.
- **Single sign-on over OpenID Connect** (Okta, Entra ID, Google Workspace,
  Keycloak…), configured from the environment only, with verified-email
  linking that never touches an administrator account, optional
  auto-provisioning and a domain allow-list.
- **Five built-in roles** plus custom roles, folder-level grants, and an API
  that enforces every rule the UI shows.
- Security headers and CSP on by default; uploads size-capped, typed and
  served as sandboxed attachments; SSRF-hardened Jira client.

### Interface
- Four theme packs (Audit Ledger, Nimbus, Ledger Dark, Obsidian), four accent
  packs and a custom accent colour; keyboard-accessible throughout; a per-user
  notification tray.

---

## Tech stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.11–3.13 · Django 5.2 LTS · Django REST Framework · SimpleJWT |
| **Async** | Celery 5 + Redis (daily reminder scan, readiness snapshot, token pruning) |
| **Frontend** | React 18 · React Router 7 · Vite 7 · Tailwind CSS · framer-motion · lucide |
| **Database** | SQLite (local) · PostgreSQL 16 (Docker / production) |
| **Storage** | Local filesystem · Amazon S3 optional |
| **Email** | Console · SMTP · IMAP/POP3 mailbox account · Amazon SES |

```mermaid
flowchart LR
    U[Browser · React SPA] -->|/api, /admin, /media| N[nginx]
    N --> A[Django REST API]
    A --> P[(PostgreSQL)]
    A --> R[(Redis · cache + broker)]
    W[Celery worker + beat] --> R
    W -->|review reminders| M[Email]
    A -->|optional| S[(S3)]
    A -->|optional| J[Jira Cloud]
```

---

## Configuration

Everything is environment-driven. The compose file carries production-safe
defaults; `.env` overrides them. Every key is documented in
[`.env.example`](.env.example). The ones that matter most:

| Setting | Purpose |
|---|---|
| `DJANGO_DEBUG` | `false` in Docker by default; `true` for the local dev path |
| `DJANGO_SECRET_KEY` / `DJANGO_SECRET_KEY_FILE` | A strong key, or a path where one is generated and persisted (compose does this) |
| `DJANGO_ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `CORS_ALLOWED_ORIGINS` | Your real hostname(s) once you leave localhost |
| `BEHIND_TLS` | `true` once a TLS-terminating proxy sits in front of nginx (secure cookies, HTTPS redirect) |
| `EMAIL_PROVIDER` | `console` · `smtp` · `mailbox` · `ses` |
| `SEED_DEMO_DATA` | `false` to boot without the demo dataset |
| `DJANGO_SUPERUSER_USERNAME` / `_PASSWORD` | Create your first account on first boot |
| `MAX_UPLOAD_MB`, `PASSWORD_MIN_LENGTH`, `THROTTLE_LOGIN`, `REVIEW_SCAN_HOUR` | Tuning knobs |

Full reference: [PREREQUISITES.md](PREREQUISITES.md), [INSTALL.md](INSTALL.md), [USER_GUIDE.md](USER_GUIDE.md).

---

## Roles

| Role | Manage users | Manage frameworks | Manage documents | Manage folders | View all | Auditor |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| Administrator | ✓ | ✓ | ✓ | ✓ | ✓ | – |
| Compliance Manager | – | ✓ | ✓ | ✓ | ✓ | – |
| Control Owner | – | – | ✓ (granted folders) | – | – | – |
| Auditor | – | – | – | – | – (granted folders, read-only) | ✓ |
| Viewer | – | – | – | – | – | – |

Folder grants (`view` / `edit` / `manage`, by role or user) are inherited by
every subfolder. Effective access is resolved in `Folder.effective_access()`.
Demo accounts: `admin`, `mia`, `owen`, `aria`, `val` — all `DemoPass123!`.

---

## Quality gates

Everything in the badge row runs on every push:

```bash
./install.sh --test        # or: .\install.ps1 -Test
```

| Gate | What it proves |
|---|---|
| `tools/validate.py` — 17 static checks | app/route wiring, API contract between SPA and backend, shipped migrations, theme packs, tests + CI present |
| `manage.py test` — **293 tests** | auth, MFA, token rotation, RBAC and tree integrity, evidence RBAC, access reviews, risk import/export safety, audit trail, reminders, health, demo retirement, boot guard |
| Backend matrix | Python 3.11 / 3.12 / 3.13 on SQLite, plus PostgreSQL 16 |
| Frontend | production build + `npm audit --audit-level=high` |
| Docker | both images build; the API image boots and answers `/api/health/` |
| [End-to-end](e2e/README.md) | Playwright drives the **built** SPA in a real browser through every screen — and fails on any console error |

The review that produced this release — findings, severities, fixes and what
was deliberately left alone — is in [REVIEW.md](REVIEW.md). Operator-facing
posture and residual risks: [SECURITY.md](SECURITY.md).

> **Control text and copyright:** control IDs and short titles are functional
> identifiers; the `objective` fields are brief original paraphrases, not the
> normative text of the standards. Only paste official control text into the
> app if your organisation holds a licence for the source documents.

---

## Handing evidence to an auditor

Audit time usually means granting the external auditor read access to a folder
tree and hoping somebody remembers to take it away afterwards. **Audit
packages** replace that ritual.

A compliance manager assembles the controls in scope, pins the evidence for
each one, writes the management assertion and **seals** the package. Sealing
snapshots every row — control text, status, owner, document name, version,
size and SHA-256 — and produces a canonical manifest with a digest. The package
is then **issued** to one named auditor for a fixed period.

That auditor signs in and sees exactly that package: the controls, the pinned
files, nothing else. They record a **design** and an **operating** conclusion
per control, which nobody at the assessed organisation can edit, and the
organisation can answer with a management response beside it. An exception can
be raised into the risk register in one click.

They leave with one self-verifying ZIP — the manifest, `SHA256SUMS`, the
workpaper and evidence CSVs, an audit-trail extract, the files themselves, and
a stdlib-only `verify.py` — which checks out with `sha256sum -c SHA256SUMS` and
no vendor involvement. Access expires or is withdrawn in one click; the record
of what was disclosed, to whom, and every file they opened, is permanent.

Operating effectiveness is tested on **sampled items**, and the package holds
them. The organisation states each control's population (size, source,
sampling method) and may list the items while the package is a draft; they are
sealed into the manifest with the artefact that supports each one. After
sealing, the auditor adds their own selections and records **pass, exception
or not tested** per item, with an exception note that is required, not
optional. The bundle carries the whole workpaper as `samples.csv`.

> The bundle proves **integrity, not origin**: it carries no signature, so the
> digest in the audit trail and the copy you publish out of band are what bind
> it to a moment.

![Audit packages](assets/screenshots/audit-packages.png)

## Project structure

```
conformiti/
├── backend/            Django project (config/) + apps: accounts, compliance,
│                       documents, governance, vendors, attestations, notifications,
│                       audit, analytics, calendar_app, integrations · testutils.py · Dockerfile
├── frontend/           React SPA (src/pages, src/components, src/styles) · Dockerfile · nginx.conf
├── compliance-data/    generated evidence folder tree (segregated by control)
├── docs/               architecture notes, sample risk import
├── tools/validate.py   dependency-free static validator
├── .github/workflows   CI
├── docker-compose.yml  db · redis · backend · worker · frontend
└── install.sh / install.ps1
```

---

## Roadmap

Highlights from [ROADMAP.md](ROADMAP.md): sample rows on package items for a
Type II operating-effectiveness workpaper, questionnaires sent to the vendor to
answer, WebAuthn passkeys, a PBC request list, SAML for the providers that still
insist on it, automated evidence collection from cloud/SaaS integrations, and
Slack/Teams notifications.

## License

[MIT](LICENSE) © 2026 elemosecurity
