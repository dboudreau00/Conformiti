#!/usr/bin/env bash
# ===========================================================================
# Conformiti — simple installer (macOS / Linux / WSL)
#
#   ./install.sh              Set up everything and start both dev servers.
#   ./install.sh --setup-only Install and seed, but don't start the servers.
#   ./install.sh --docker     Skip the local path and use Docker Compose instead.
#
# The local path needs no external services: it uses SQLite and prints emails
# to the console, so there's nothing to install beyond Python 3 and Node.js.
# Review reminders are triggered on demand with `manage.py send_review_reminders`
# (the Celery/Redis scheduler is only needed for the Docker/production path).
# ===========================================================================
set -euo pipefail
cd "$(dirname "$0")"

BOLD=$(printf '\033[1m'); DIM=$(printf '\033[2m'); GREEN=$(printf '\033[32m'); RESET=$(printf '\033[0m')
say()  { printf "%s\n" "${BOLD}==>${RESET} $*"; }
ok()   { printf "%s\n" "${GREEN}  ✓${RESET} $*"; }
die()  { printf "%s\n" "Error: $*" >&2; exit 1; }

MODE="run"
for arg in "$@"; do
  case "$arg" in
    --setup-only) MODE="setup" ;;
    --docker)     MODE="docker" ;;
    -h|--help)    grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option: $arg" ;;
  esac
done

# --- Docker path -----------------------------------------------------------
if [ "$MODE" = "docker" ]; then
  command -v docker >/dev/null 2>&1 || die "Docker is not installed."
  [ -f .env ] || { cp .env.example .env; ok "created .env"; }
  say "Starting with Docker Compose (app on http://localhost:8080)…"
  exec docker compose up --build
fi

# --- Prerequisites ---------------------------------------------------------
PY=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done
[ -n "$PY" ] || die "Python 3 is required but was not found on PATH."
"$PY" -c 'import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)' \
  || die "Python 3.10+ is required (found $($PY --version 2>&1))."
command -v npm >/dev/null 2>&1 || die "Node.js / npm is required but was not found on PATH."
ok "using $($PY --version 2>&1) and npm $(npm --version)"

# --- .env (generate a secret key on first run) -----------------------------
if [ ! -f .env ]; then
  cp .env.example .env
  SECRET=$("$PY" -c 'import secrets; print(secrets.token_urlsafe(50))')
  "$PY" - "$SECRET" <<'PY'
import sys, re, pathlib
p = pathlib.Path(".env"); t = p.read_text()
t = re.sub(r'^DJANGO_SECRET_KEY=.*$', 'DJANGO_SECRET_KEY=' + sys.argv[1], t, flags=re.M)
p.write_text(t)
PY
  ok ".env created (SQLite + console email; a secret key was generated)"
else
  ok ".env already present — leaving it untouched"
fi

# --- Python virtualenv + backend deps --------------------------------------
if [ ! -d .venv ]; then
  say "Creating Python virtual environment (.venv)…"
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
say "Installing backend dependencies…"
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r backend/requirements.txt
ok "backend dependencies installed"

# --- Database, control libraries, demo data --------------------------------
say "Applying migrations and seeding control libraries + demo data…"
pushd backend >/dev/null
python manage.py makemigrations accounts compliance documents calendar_app notifications audit governance integrations
python manage.py migrate --noinput
python manage.py seed_frameworks --with-folders
python manage.py bootstrap_demo || true
python manage.py generate_folder_tree || true
popd >/dev/null
ok "database ready (SOC 2 · ISO 27001 · PCI DSS seeded)"

# --- Frontend deps ---------------------------------------------------------
say "Installing frontend dependencies (this can take a minute)…"
pushd frontend >/dev/null
npm install --silent
popd >/dev/null
ok "frontend dependencies installed"

# --- Done ------------------------------------------------------------------
cat <<BANNER

${GREEN}${BOLD}Setup complete.${RESET}

  ${BOLD}Sign in${RESET}   admin / DemoPass123!
  ${DIM}(four role-based demo users also exist — mia, owen, aria, val — all with password DemoPass123!)${RESET}

  ${BOLD}Try the mailer${RESET}      cd backend && ../.venv/bin/python manage.py send_review_reminders --dry-run
  ${BOLD}Mailbox test${RESET}       set EMAIL_PROVIDER=mailbox + MAILBOX_* in .env, then
                     cd backend && ../.venv/bin/python manage.py test_mailbox --to you@example.com

BANNER

if [ "$MODE" = "setup" ]; then
  cat <<NEXT
To start the app later, run:
  (backend)   cd backend && ../.venv/bin/python manage.py runserver 127.0.0.1:8000
  (frontend)  cd frontend && npm run dev
Then open ${BOLD}http://localhost:5173${RESET}
NEXT
  exit 0
fi

say "Starting servers — backend on :8000, frontend on :5173."
say "Open ${BOLD}http://localhost:5173${RESET} in your browser. Press Ctrl-C to stop."
trap 'echo; say "Shutting down…"; kill 0 2>/dev/null || true' EXIT INT TERM
( cd backend && exec python manage.py runserver 127.0.0.1:8000 ) &
( cd frontend && exec npm run dev ) &
wait
