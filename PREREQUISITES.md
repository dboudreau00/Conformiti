# Prerequisites

## Docker path (evaluation, pilots, production)

- **Docker Engine 24+ with Docker Compose 2.24.0 or newer**
  (`docker compose version`), or a Docker Desktop that ships that Compose.
  Older Compose releases reject the compose file's optional `.env` entry
  (`env_file` with `required: false`). On Windows, Docker Desktop or Docker
  inside WSL 2 both work.
- 2 vCPU / 4 GB RAM / 20 GB disk is comfortable for tens of users.
- Free host ports: **8080** for nginx on every interface (`CONFORMITI_PORT` to
  change) and **8000** on 127.0.0.1 for the API (`CONFORMITI_API_PORT` to
  change). The local development path below uses 8000 as well, so stop one
  before starting the other, or move one of them (the local API moves with
  `CONFORMITI_DEV_API_PORT`, which is separate from `CONFORMITI_API_PORT`).
- Outbound internet once, to pull base images and build.
- **git**, to clone the repository and check out the newest release tag
  (`main` is the development line), and **curl** if you use
  `./install.sh --docker` (it waits for the stack with it; `install.ps1`
  needs nothing extra).
- Nothing else. No `.env` is required.

For production add: a DNS name, a TLS-terminating proxy in front of port 8080
(then `BEHIND_TLS=true`), a real `EMAIL_PROVIDER` (SMTP, a mailbox account, or
SES) so review reminders reach owners, and a backup of the database and of the
`media`, `secrets` and `tree` volumes. `scripts/backup.sh` takes all four. The
`secrets` volume holds the Django secret key, the field-encryption ring and the
package signing key, and a restore without it loses all three.

## Local development path

- **Python 3.11 to 3.14** with `venv` and `pip`
  (Debian or Ubuntu: `sudo apt install python3-venv python3-pip`). The
  installer refuses anything older than 3.11 and warns about anything newer
  than 3.14, which is untested.
- **Node.js 20.19+ or 22.12+** with npm 10+ (Vite 8 requires it). A Linux
  distribution's own `nodejs` package is usually older (Debian 12 and Ubuntu
  24.04 ship 18, Ubuntu 22.04 ships 12), so install Node 22 LTS from
  nodejs.org, NodeSource's repository or nvm, and check `node --version`.
  [INSTALL.md](INSTALL.md) §3 shows the NodeSource commands, which need
  **curl**.
- **git**, to clone the repository and check out the newest release tag.
- Free local ports **8000** (Django) and **5173** (Vite), or others named in
  `CONFORMITI_DEV_API_PORT` and `CONFORMITI_DEV_PORT`.
- macOS 13+, any recent Linux, or Windows 10/11 (PowerShell 5.1 or 7).

On Windows, start the installer with
`powershell -ExecutionPolicy Bypass -File .\install.ps1` (add `-Docker` for the
Docker path). Windows PowerShell refuses to run any script by default, and a
script extracted from a downloaded ZIP is refused under `RemoteSigned` too.
`-ExecutionPolicy Bypass` lifts that for the one run and changes nothing on
the machine.

## Bare metal (Linux, without Docker)

Everything the local development path needs, plus PostgreSQL 16, Redis 7 and
nginx on the host, a DNS name and a TLS certificate for production, and a
backup of the database, the evidence files and the key files.
[INSTALL.md](INSTALL.md) §3 walks through it, backups included.

PostgreSQL 16 is the version the Docker stack runs and CI tests. Django 5.2
refuses anything older than 14, and 14 and 15 are untested here. Ubuntu 24.04
ships 16; Debian 12 (15) and Ubuntu 22.04 (14) need the PostgreSQL project's
own repository first, which §3 shows how to add.

## Accounts and integrations

No external accounts are required: SQLite, console email and local file
storage are the defaults. Optional, to exercise integrations: SMTP/SES
credentials or an IMAP/POP3 mailbox, and an Atlassian Cloud site with an API
token for the Jira page.

## Browser

Any current Chrome, Edge, Firefox or Safari. The interface is keyboard
operable and respects `prefers-reduced-motion`.
