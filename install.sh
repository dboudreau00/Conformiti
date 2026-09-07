#!/usr/bin/env bash
# ===========================================================================
# Conformiti installer (macOS / Linux / WSL)
#
#   ./install.sh                Local dev: venv + npm + migrate + seed, then
#                               start the API (:8000) and the web app (:5173).
#   ./install.sh --setup-only   Install and seed, but don't start the servers.
#   ./install.sh --docker       Build and start the full Docker stack
#                               (Postgres · Redis · API · worker · nginx) on
#                               http://localhost:8080 and wait until healthy.
#   ./install.sh --test         Run the backend test suite, the static
#                               validator and a production frontend build.
#   ./install.sh --reset        Local only: wipe db.sqlite3 + uploads, reseed.
#
# Flags that combine with the above: --no-demo (skip the demo dataset),
# --open (open the browser when ready), --port N (Docker: host port).
#
# The local path needs no external services: SQLite + console email. Review
# reminders run on demand (`manage.py send_review_reminders`); the Docker
# stack runs them daily on its own.
# ===========================================================================
set -euo pipefail
cd "$(dirname "$0")"

BOLD=$(printf '\033[1m'); DIM=$(printf '\033[2m'); GREEN=$(printf '\033[32m'); RED=$(printf '\033[31m'); YEL=$(printf '\033[33m'); RESET=$(printf '\033[0m')
say()  { printf "%s\n" "${BOLD}==>${RESET} $*"; }
ok()   { printf "%s\n" "${GREEN}  ✓${RESET} $*"; }
warn() { printf "%s\n" "${YEL}  !${RESET} $*"; }
die()  { printf "%s\n" "${RED}Error:${RESET} $*" >&2; exit 1; }

MODE="run"; DEMO="true"; OPEN="no"; PORT="8080"
while [ $# -gt 0 ]; do
  case "$1" in
    --setup-only) MODE="setup" ;;
    --docker)     MODE="docker" ;;
    --test)       MODE="test" ;;
    --reset)      MODE="reset" ;;
    --no-demo)    DEMO="false" ;;
    --open)       OPEN="yes" ;;
    --port)       shift; PORT="${1:-8080}" ;;
    -h|--help)    sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
  shift
done

open_url() {
  [ "$OPEN" = "yes" ] || return 0
  if command -v xdg-open >/dev/null 2>&1; then xdg-open "$1" >/dev/null 2>&1 || true
  elif command -v open >/dev/null 2>&1; then open "$1" || true
  elif command -v powershell.exe >/dev/null 2>&1; then powershell.exe -NoProfile -Command "Start-Process '$1'" || true
  fi
}

gen_secret() { "$1" -c 'import secrets; print(secrets.token_urlsafe(50))'; }

wait_for_health() {  # $1 = url, $2 = seconds
  local url="$1" limit="${2:-180}" i=0
  while [ $i -lt "$limit" ]; do
    if curl -fsS "$url" >/dev/null 2>&1; then return 0; fi
    sleep 2; i=$((i + 2))
    [ $((i % 20)) -eq 0 ] && printf "%s\n" "${DIM}  … still starting (${i}s)${RESET}"
  done
  return 1
}

# --- Docker path -----------------------------------------------------------
if [ "$MODE" = "docker" ]; then
  command -v docker >/dev/null 2>&1 || die "Docker is not installed (https://docs.docker.com/get-docker/)."
  docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required ('docker compose')."
  docker info >/dev/null 2>&1 || die "The Docker daemon is not running or not reachable."
  command -v curl >/dev/null 2>&1 || die "curl is required to wait for the stack to become healthy."

  if [ ! -f .env ]; then
    PY=""; for cand in python3 python; do command -v "$cand" >/dev/null 2>&1 && { PY="$cand"; break; }; done
    if [ -n "$PY" ]; then SECRET=$(gen_secret "$PY"); else SECRET=$(head -c 48 /dev/urandom | base64 | tr -d '=+/\n'); fi
    HOSTS="localhost,127.0.0.1,backend,$(hostname 2>/dev/null || echo conformiti)"
    cat > .env <<ENV
# Written by install.sh --docker on $(date -u +%Y-%m-%dT%H:%MZ). Safe production-style
# defaults for a LAN deployment over plain HTTP. See .env.example for every key.
#
# The Docker stack reads CONFORMITI_DEBUG / CONFORMITI_SECRET_KEY, not
# DJANGO_DEBUG / DJANGO_SECRET_KEY: those two belong to the local dev path and
# must never leak into a container. Leave CONFORMITI_SECRET_KEY unset to have
# the container generate and persist its own key in the 'secrets' volume.
CONFORMITI_DEBUG=false
CONFORMITI_SECRET_KEY=${SECRET}
DJANGO_ALLOWED_HOSTS=${HOSTS}
CSRF_TRUSTED_ORIGINS=http://localhost:${PORT},http://127.0.0.1:${PORT}
CORS_ALLOWED_ORIGINS=http://localhost:${PORT}
# Flip to true once a TLS-terminating proxy sits in front of nginx.
BEHIND_TLS=false
EMAIL_PROVIDER=console
SEED_DEMO_DATA=${DEMO}
CONFORMITI_PORT=${PORT}
ENV
    ok ".env written (DEBUG off, unique secret key, demo data ${DEMO})"
  else
    ok ".env already present — leaving it untouched"
    if grep -Eq '^CONFORMITI_DEBUG=(1|true|yes|on)' .env; then
      warn "your .env sets CONFORMITI_DEBUG=true — the Docker stack will run in DEBUG mode."
      warn "For a real deployment set CONFORMITI_DEBUG=false."
    fi
    if grep -Eq '^DJANGO_DEBUG=(1|true|yes|on)' .env && ! grep -q '^CONFORMITI_DEBUG=' .env; then
      warn "your .env has DJANGO_DEBUG=true (from the local dev path). It does NOT"
      warn "affect the Docker stack, which stays in production mode. Set"
      warn "CONFORMITI_DEBUG=true if you deliberately want a DEBUG container."
    fi
    grep -q '^CONFORMITI_PORT=' .env && PORT=$(grep '^CONFORMITI_PORT=' .env | tail -1 | cut -d= -f2)
  fi

  say "Building images and starting the stack (first build takes a few minutes)…"
  docker compose up -d --build
  say "Waiting for the API to report healthy…"
  if wait_for_health "http://localhost:${PORT}/api/health/" 240; then
    HEALTH=$(curl -fsS "http://localhost:${PORT}/api/health/")
    ok "healthy: ${HEALTH}"
  else
    docker compose ps
    die "The stack did not become healthy in time. Inspect with: docker compose logs backend"
  fi
  cat <<BANNER

${GREEN}${BOLD}Conformiti is running.${RESET}

  ${BOLD}App${RESET}      http://localhost:${PORT}
  ${BOLD}Admin${RESET}    http://localhost:${PORT}/admin/
  ${BOLD}Health${RESET}   http://localhost:${PORT}/api/health/
BANNER
  if [ "$DEMO" = "true" ]; then
    printf "%s\n" "  ${BOLD}Sign in${RESET}  admin   ${DIM}(also mia, owen, aria, val — same password)${RESET}"
    printf "%s\n" "  ${DIM}The password was printed above when the demo data was seeded.${RESET}"
    printf "%s\n" "  ${YEL}Before real use:${RESET} docker compose exec backend python manage.py remove_demo_data"
  else
    printf "%s\n" "  Create your first account: docker compose exec backend python manage.py createsuperuser"
  fi
  printf "%s\n" "  ${DIM}Logs: docker compose logs -f    Stop: docker compose down    Update: ./install.sh --docker${RESET}"
  open_url "http://localhost:${PORT}"
  exit 0
fi

# --- Prerequisites (local paths) -------------------------------------------
PY=""
for cand in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(0 if sys.version_info>=(3,11) else 1)' 2>/dev/null; then
    PY="$cand"; break
  fi
done
[ -n "$PY" ] || die "Python 3.11+ is required but was not found on PATH."
command -v node >/dev/null 2>&1 || die "Node.js 20.19+ (with npm) is required but was not found on PATH."
command -v npm >/dev/null 2>&1 || die "npm is required but was not found on PATH."
NODE_OK=$(node -e 'const [a,b]=process.versions.node.split(".").map(Number); process.stdout.write((a>20||(a===20&&b>=19))?"y":"n")')
[ "$NODE_OK" = "y" ] || die "Node.js 20.19+ is required (found $(node --version))."
ok "using $($PY --version 2>&1), node $(node --version), npm $(npm --version)"

# --- .env (generate a secret key on first run) -----------------------------
if [ ! -f .env ]; then
  cp .env.example .env
  SECRET=$(gen_secret "$PY")
  "$PY" - "$SECRET" <<'PY'
import sys, re, pathlib
p = pathlib.Path(".env"); t = p.read_text(encoding="utf-8")
t = re.sub(r'^DJANGO_SECRET_KEY=.*$', 'DJANGO_SECRET_KEY=' + sys.argv[1], t, flags=re.M)
p.write_text(t, encoding="utf-8")
PY
  ok ".env created (SQLite + console email; a secret key was generated)"
else
  ok ".env already present — leaving it untouched"
fi

# --- Python virtualenv + backend deps --------------------------------------
if [ ! -x .venv/bin/python ]; then
  say "Creating Python virtual environment (.venv)…"
  rm -rf .venv
  "$PY" -m venv .venv
fi
VPY=".venv/bin/python"
say "Installing backend dependencies…"
"$VPY" -m pip install --quiet --upgrade pip
"$VPY" -m pip install --quiet -r backend/requirements.txt
ok "backend dependencies installed"

if [ "$MODE" = "reset" ]; then
  say "Resetting the local database and uploads…"
  rm -f backend/db.sqlite3
  rm -rf backend/media
  ok "clean slate"
  MODE="setup"
fi

# --- Frontend deps ---------------------------------------------------------
say "Installing frontend dependencies (this can take a minute)…"
( cd frontend && npm install --no-fund --no-audit --silent )
ok "frontend dependencies installed"

# --- Test mode -------------------------------------------------------------
if [ "$MODE" = "test" ]; then
  say "Static validator"
  "$VPY" tools/validate.py
  say "Backend test suite"
  ( cd backend && ../"$VPY" manage.py check && ../"$VPY" manage.py makemigrations --check --dry-run && ../"$VPY" manage.py test --noinput )
  say "Frontend production build"
  ( cd frontend && npm run build )
  ok "all checks passed"
  exit 0
fi

# --- Database, control libraries, demo data --------------------------------
say "Applying migrations and seeding control libraries…"
( cd backend \
  && ../"$VPY" manage.py migrate --noinput \
  && ../"$VPY" manage.py seed_frameworks --with-folders \
  && ../"$VPY" manage.py generate_folder_tree >/dev/null )
if [ "$DEMO" = "true" ]; then
  ( cd backend && ../"$VPY" manage.py bootstrap_demo )
  ok "database ready (SOC 2 · ISO 27001 · PCI DSS seeded, demo data loaded)"
else
  ok "database ready (SOC 2 · ISO 27001 · PCI DSS seeded, no demo data)"
  warn "create your first account with: cd backend && ../.venv/bin/python manage.py createsuperuser"
fi

# --- Done ------------------------------------------------------------------
cat <<BANNER

${GREEN}${BOLD}Setup complete.${RESET}
BANNER
if [ "$DEMO" = "true" ]; then
  printf "%s\n" "  ${BOLD}Sign in${RESET}   admin   ${DIM}(also mia, owen, aria, val — same password)${RESET}"
  printf "%s\n" "  ${DIM}Password: docker compose logs backend | grep \"Sign in as\"${RESET}"
fi
cat <<BANNER
  ${BOLD}Tests${RESET}     ./install.sh --test
  ${BOLD}Mailer${RESET}    cd backend && ../.venv/bin/python manage.py send_review_reminders --dry-run

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
( cd backend && exec ../.venv/bin/python manage.py runserver 127.0.0.1:8000 ) &
( cd frontend && exec npm run dev ) &
( sleep 6 && open_url "http://localhost:5173" ) &
wait
