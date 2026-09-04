# Prerequisites

## Docker path (evaluation, pilots, production)

- **Docker Engine 24+ with Compose v2** (`docker compose version`), or Docker
  Desktop. On Windows, Docker Desktop or Docker inside WSL 2 both work.
- 2 vCPU / 4 GB RAM is comfortable for tens of users; ~3 GB disk for images
  and data.
- Free host port **8080** (`CONFORMITI_PORT` to change).
- Outbound internet once, to pull base images and build.
- Nothing else. No `.env` is required.

For production add: a DNS name, a TLS-terminating proxy in front of port 8080
(then `BEHIND_TLS=true`), a real `EMAIL_PROVIDER` (SMTP, a mailbox account, or
SES) so review reminders reach owners, and a backup of the `pgdata` and
`media` volumes.

## Local development path

- **Python 3.11, 3.12 or 3.13** with `venv` and `pip`
  (Ubuntu: `sudo apt install python3-venv python3-pip`).
- **Node.js 20.19+ or 22+** with npm 10+ (Vite 7 requires it).
- Free local ports **8000** (Django) and **5173** (Vite).
- macOS 13+, any recent Linux, or Windows 10/11 (PowerShell 5.1 or 7).

No external accounts are required: SQLite, console email and local file
storage are the defaults. Optional, to exercise integrations: SMTP/SES
credentials or an IMAP/POP3 mailbox, and an Atlassian Cloud site with an API
token for the Jira page.

## Browser

Any current Chrome, Edge, Firefox or Safari. The interface is keyboard
operable and respects `prefers-reduced-motion`.
