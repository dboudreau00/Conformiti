# Prerequisites

What you need before running the platform — split into what's required for a
local **alpha test** and what's additionally required for a hosted **beta**.

## Alpha (local install, one machine)

**Hardware / OS**
- Any modern machine: 2 CPU cores, 4 GB RAM, ~2 GB free disk.
- macOS 13+, Ubuntu 22.04/24.04 (or any recent Linux), or Windows 10/11
  (native via `install.ps1`, or WSL2 via `install.sh`).

**Software**
- **Python 3.11 or 3.12** with `venv` and `pip`
  (Ubuntu: `sudo apt install python3-venv python3-pip`).
- **Node.js 20+ and npm 10+** (for the React frontend dev server / build).
- `git` (to clone) and a POSIX shell on macOS/Linux; PowerShell 5+ on Windows.

**Network / ports**
- Outbound internet once, to install pip and npm packages.
- Free local ports: **8000** (Django API) and **5173** (Vite dev server).

**Accounts / credentials — all optional for alpha**
- None required. SQLite is the default database, email defaults to the
  console backend (reminder emails print to the terminal), and file storage
  is local disk.
- Optional: SMTP or AWS SES credentials to see real reminder emails; an IMAP
  or POP3 mailbox if testing the mailbox provider; an Atlassian Cloud site +
  scoped API token to exercise the Jira page.

**Then:** run `./install.sh` (macOS/Linux/WSL) or `.\install.ps1` (Windows).
The installer creates the venv, installs dependencies, runs migrations, seeds
the demo data (5 users, password `DemoPass123!`), and starts both servers.
Follow `TESTING.md` end-to-end — it's the alpha test script.

## Beta (hosted, multiple testers)

Everything above, plus:

**Infrastructure**
- A Linux host or VM (2 vCPU / 4 GB is comfortable for tens of users) with
  **Docker Engine 24+ and Docker Compose v2**, *or* the bare-metal stack:
  Python 3.12, Node 20 (build once), nginx, and systemd or supervisor.
- **PostgreSQL 16** (the compose file provides it) — don't run beta on SQLite.
- **Redis 7** for Celery (compose provides it) so review reminders actually send.

**Domain & transport**
- A DNS name for the app and **TLS termination** (nginx + Let's Encrypt, or a
  load balancer). The backend auto-enables secure cookies and SSL redirect
  when `DJANGO_DEBUG=false`; enable HSTS via `SECURE_HSTS_SECONDS` once HTTPS
  is stable.

**Required configuration (`.env`)**
- `DJANGO_DEBUG=false`
- `DJANGO_SECRET_KEY` — a strong unique value
  (`python -c "import secrets; print(secrets.token_urlsafe(50))"`).
  The app **refuses to boot** in production with the placeholder key.
- `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`
  set to your real origin(s).
- Database URL/credentials for Postgres; `EMAIL_PROVIDER` (ses/smtp/mailbox)
  with working credentials so testers get review reminders.

**Operations**
- Nightly Postgres backup (`pg_dump`) and a copy of the media/upload
  directory; a restore you've actually tested once.
- A superuser created for yourself (`python manage.py createsuperuser`), then
  onboard beta testers from the **Users** screen (assign roles; hand each a
  temporary password).
- Read `SECURITY.md` — it lists the residual risks to accept or mitigate
  (JWTs in localStorage, no refresh-token rotation, Jira token at rest) and
  the production checklist.

**Before inviting testers**
1. `python3 tools/validate.py` passes on your checkout.
2. `docker compose up` (or the installers) boots clean; log in as each demo
   role once.
3. Run TESTING.md §17 security spot-checks against the deployed URL.
4. Delete or change the demo accounts — `DemoPass123!` must not reach beta.
