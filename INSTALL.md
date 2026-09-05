# Install

Three ways to run Conformiti, from "just show me" to production.

| Path | Best for | Needs | Command |
|---|---|---|---|
| **Docker** | evaluating, LAN pilots, production | Docker Engine 24+ / Docker Desktop with Compose v2 | `docker compose up -d --build` |
| **Local dev** | hacking on the code | Python 3.11+, Node 20.19+ | `./install.sh` / `.\install.ps1` |
| **Manual** | custom hosting, bare metal | as above + PostgreSQL, Redis, nginx | see §3 |

---

## 1. Docker (recommended)

```bash
git clone https://github.com/dboudreau00/Conformiti.git
cd Conformiti
docker compose up -d --build
```

Then open **http://localhost:8080** and sign in as `admin` / `DemoPass123!`.

What happens on first boot:

1. PostgreSQL 16 and Redis 7 start with healthchecks.
2. The API container waits for the database, applies the shipped migrations,
   seeds the three control libraries (217 controls, 1,117 folders) and the
   built-in roles, seeds the demo dataset (unless `SEED_DEMO_DATA=false`),
   collects static files and starts gunicorn as an unprivileged user.
3. A strong `DJANGO_SECRET_KEY` is generated and persisted in the `secrets`
   volume — no placeholder ever signs a token.
4. The Celery worker starts once the API is *healthy* and runs the daily
   review scan (06:00 by default), the readiness snapshot and blacklist pruning.
5. nginx serves the built SPA, proxies `/api/` and `/admin/`, and serves
   uploads and static files from shared volumes.

The API is bound to `127.0.0.1:8000` on the host for debugging; the LAN only
sees nginx on port 8080 (`CONFORMITI_PORT` to change it).

### The scripted variant

```bash
./install.sh --docker            # macOS / Linux / WSL
.\install.ps1 -Docker            # Windows PowerShell
```

The script checks Docker is running, writes a production-style `.env` if you
don't have one (DEBUG off, a unique key, your hostname in `ALLOWED_HOSTS`),
builds and starts the stack, **waits until `/api/health/` reports `ok`**, and
prints the URLs and demo credentials. Flags: `--no-demo` / `-NoDemo`,
`--open` / `-Open`, `--port N` / `-Port N`.

### Going to production

1. Set the real hostname in `.env`:
   ```ini
   DJANGO_ALLOWED_HOSTS=grc.example.com
   CSRF_TRUSTED_ORIGINS=https://grc.example.com
   CORS_ALLOWED_ORIGINS=https://grc.example.com
   BEHIND_TLS=true            # once TLS is terminated in front of nginx
   SECURE_HSTS_SECONDS=31536000
   EMAIL_PROVIDER=smtp        # + EMAIL_HOST / EMAIL_HOST_USER / EMAIL_HOST_PASSWORD
   POSTGRES_PASSWORD=<something long>
   ```
2. Terminate TLS (Caddy, Traefik, a load balancer) in front of port 8080.
3. Create your own administrator and retire the demo data:
   ```bash
   docker compose exec backend python manage.py createsuperuser
   docker compose exec backend python manage.py remove_demo_data
   ```
   or set `SEED_DEMO_DATA=false` and `DJANGO_SUPERUSER_USERNAME` /
   `DJANGO_SUPERUSER_PASSWORD` / `DJANGO_SUPERUSER_EMAIL` before the first boot.
4. Confirm: `curl -s https://grc.example.com/api/health/` →
   `{"status":"ok","version":"0.4.0","database":"ok","demo_accounts":false}`.
5. Back up the `pgdata` and `media` volumes nightly.

### Single sign-on (OpenID Connect)

Optional. Nothing changes until all three of the first keys are set.

1. Register Conformiti at your identity provider as a **confidential web
   application** using the authorization-code flow, with the redirect URI
   `https://grc.example.com/api/auth/oidc/callback/` and the scopes
   `openid email profile`. Okta, Entra ID, Google Workspace, Keycloak and
   Authentik all work; anything that publishes
   `/.well-known/openid-configuration` should.
2. Add to `.env` and restart:
   ```ini
   OIDC_ISSUER=https://login.example.com      # exactly the issuer the provider publishes
   OIDC_CLIENT_ID=...
   OIDC_CLIENT_SECRET=...
   OIDC_LABEL=Sign in with Okta               # the button text
   OIDC_ALLOWED_DOMAINS=example.com           # who may sign in through it
   ```
3. On a person's first SSO sign-in, a verified email that matches exactly one
   local account links it. Administrator accounts — superuser, staff, or any
   role that can manage users — are never linked this way, and a linked user
   who is later promoted loses SSO until an operator re-affirms it. Link
   them deliberately:
   ```bash
   docker compose exec backend python manage.py link_oidc_identity admin <subject> --allow-privileged
   ```
   Pre-link anyone else the same way (without the flag) to skip the email match.
4. To create accounts for people the provider vouches for but who have no
   local account yet, set `OIDC_AUTO_PROVISION=true` and `OIDC_DEFAULT_ROLE`
   (default `Viewer`; a role that can manage users is refused).

Entra ID often omits `email_verified`; set `OIDC_REQUIRE_VERIFIED_EMAIL=false`
only when the tenant is your own. SSO sign-ins skip local TOTP — enforce MFA
at the provider.

Everyday operations:

```bash
docker compose logs -f backend worker      # logs
docker compose pull && docker compose up -d --build   # update
docker compose exec backend python manage.py send_review_reminders --dry-run
docker compose down                        # stop (volumes are kept)
```

---

## 2. Local development (SQLite, console email)

```bash
./install.sh                 # macOS / Linux / WSL
.\install.ps1                # Windows PowerShell
```

The installer verifies Python 3.11+ and Node 20.19+, creates `.env` with a
generated secret key, builds `.venv`, installs backend and frontend
dependencies, applies migrations, seeds the libraries and demo data, and starts
the API on **:8000** and the Vite dev server on **:5173**. Every step is
exit-code checked; a failing step stops the installer.

Open **http://localhost:5173**. Demo accounts (all `DemoPass123!`):

| Username | Role |
|---|---|
| `admin` | Administrator (superuser) |
| `mia` | Compliance Manager |
| `owen` | Control Owner |
| `aria` | Auditor |
| `val` | Viewer |

Useful flags:

| Flag | Effect |
|---|---|
| `--setup-only` / `-SetupOnly` | install and seed, don't start servers |
| `--test` / `-Test` | run the validator, the backend test suite and a production frontend build |

### Optional: scan uploaded evidence for malware

```bash
docker compose --profile scanning up -d          # starts a ClamAV daemon
CONFORMITI_SCANNING=true docker compose up -d    # and tells the API to use it
```

The first start downloads the signature database, which takes a few minutes;
the container reports whether the scanner answered. **Scanning fails closed** —
while it is on and the daemon is unreachable, uploads are refused rather than
stored unscanned.
| `--reset` / `-Reset` | wipe `db.sqlite3` and uploads, reseed |
| `--no-demo` / `-NoDemo` | seed libraries only (then `createsuperuser`) |
| `--open` / `-Open` | open the browser when ready |

Re-running the installer is safe: it reuses `.venv`, leaves `.env` alone, and
every seeder is idempotent.

Review reminders on this path run on demand:

```bash
cd backend
../.venv/bin/python manage.py send_review_reminders --dry-run    # Windows: ..\.venv\Scripts\python.exe
```

---

## 3. Manual / bare metal

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env            # set DJANGO_DEBUG=false, DJANGO_SECRET_KEY, POSTGRES_*, origins
cd backend
python manage.py migrate
python manage.py seed_frameworks --with-folders
python manage.py createsuperuser
python manage.py collectstatic --noinput
gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3
```

Run `celery -A config worker -B -l info` under a supervisor for the daily
jobs, or schedule them with cron:

```
0 6 * * *  cd /srv/conformiti/backend && ../.venv/bin/python manage.py send_review_reminders
5 6 * * *  cd /srv/conformiti/backend && ../.venv/bin/python manage.py record_readiness
30 3 * * 0 cd /srv/conformiti/backend && ../.venv/bin/python manage.py flushexpiredtokens
```

Build the SPA once (`cd frontend && npm ci && npm run build`) and serve
`frontend/dist` with the shipped `frontend/nginx.conf` as a template (it
proxies `/api/` and `/admin/` to gunicorn and serves `/media/` and `/static/`
from disk).

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `docker compose up` prints `DJANGO_SECRET_KEY must be set…` | You set `DJANGO_DEBUG=false` in `.env` with the placeholder key and no `DJANGO_SECRET_KEY_FILE`. Delete the placeholder line (compose generates a key) or set a real one. |
| The app loads but every request is `400 Bad Request` | The hostname you browse with isn't in `DJANGO_ALLOWED_HOSTS`. |
| Admin login form reloads silently over plain HTTP | `BEHIND_TLS=true` (secure cookies) on an HTTP deployment. Set it to `false` until TLS is in front. |
| `/api/health/` says `"database": "unavailable"` | PostgreSQL is not up or credentials differ between the `db` and `backend` services. |
| Login always fails on the local path | Seed didn't run: `cd backend && ../.venv/bin/python manage.py bootstrap_demo`. |
| `Too many attempts` at sign-in | The per-client login throttle (8/min). Wait a minute. |
| Uploads rejected as too large | Raise `MAX_UPLOAD_MB` **and** `client_max_body_size` in `frontend/nginx.conf`. |
| Port in use | `CONFORMITI_PORT=8081` (Docker) or `manage.py runserver 127.0.0.1:8001` + the proxy target in `frontend/vite.config.js`. |
