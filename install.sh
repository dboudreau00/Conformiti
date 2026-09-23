#!/usr/bin/env bash
# ===========================================================================
# Conformiti installer (macOS / Linux / WSL)
#
#   ./install.sh                Local dev: venv + npm + migrate + seed, then
#                               start the API on :8000 and the web app on
#                               :5173 (CONFORMITI_DEV_API_PORT and
#                               CONFORMITI_DEV_PORT in the shell move them).
#   ./install.sh --setup-only   Install and seed, but don't start the servers.
#   ./install.sh --docker       Build and start the full Docker stack
#                               (Postgres · Redis · API · worker · nginx) on
#                               http://localhost:8080 and wait until healthy.
#   ./install.sh --test         Run the backend test suite, the static
#                               validator and a production frontend build.
#   ./install.sh --reset        Local only: wipe db.sqlite3 + uploads, reseed.
#
# Flags that combine with the above: --demo (load the sample organisation;
# off by default, and an installation carrying it says so on its sign-in
# page), --open (open the browser when ready), --port N (Docker: host port).
# With --docker and an existing .env, --demo / --no-demo and --port update
# SEED_DEMO_DATA and CONFORMITI_PORT in it, and the script says so.
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

# DEMO_SET / PORT_SET record that the flag was given, so an existing .env is
# only changed when the user asked for it (a plain re-run leaves it alone).
MODE="run"; DEMO="false"; DEMO_SET=""; OPEN="no"; PORT="8080"; PORT_SET=""
while [ $# -gt 0 ]; do
  case "$1" in
    --setup-only) MODE="setup" ;;
    --docker)     MODE="docker" ;;
    --test)       MODE="test" ;;
    --reset)      MODE="reset" ;;
    --demo)       DEMO="true"; DEMO_SET="yes" ;;
    --no-demo)    DEMO="false"; DEMO_SET="yes" ;;   # kept: it is what older notes say
    --open)       OPEN="yes" ;;
    --port)       [ $# -ge 2 ] || die "--port needs a port number"; shift; PORT="$1"; PORT_SET="yes" ;;
    -h|--help)    sed -n '2,/^# ====/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
  shift
done
check_port() {  # $1 = what the value is called, $2 = the value
  case "$2" in ''|*[!0-9]*) die "$1 needs a port number (got '$2')" ;; esac
  [ "${#2}" -le 5 ] && [ "$2" -ge 1 ] && [ "$2" -le 65535 ] || die "$1 must be between 1 and 65535 (got '$2')"
}
check_port --port "$PORT"

open_url() {
  [ "$OPEN" = "yes" ] || return 0
  if command -v xdg-open >/dev/null 2>&1; then xdg-open "$1" >/dev/null 2>&1 || true
  elif command -v open >/dev/null 2>&1; then open "$1" || true
  elif command -v powershell.exe >/dev/null 2>&1; then powershell.exe -NoProfile -Command "Start-Process '$1'" || true
  fi
}

gen_secret() { "$1" -c 'import secrets; print(secrets.token_urlsafe(50))'; }

# .env helpers (plain awk, so they behave the same on macOS and Linux).
# env_get KEY prints the value Compose reads for KEY: the last KEY= line wins,
# and Compose takes one pair of surrounding quotes, or else a " # comment" at
# the end, off the value before a container sees it, so this does too.
env_get() {
  awk -v k="$1" -v sq="'" '
    index($0, k "=") == 1 { v = substr($0, length(k) + 2) }
    END {
      sub(/\r$/, "", v); t = v; sub(/^[ \t]+/, "", t); q = substr(t, 1, 1)
      if ((q == "\"" || q == sq) && (e = index(substr(t, 2), q)) > 0) v = substr(t, 2, e - 1)
      else { sub(/[ \t]+#.*$/, "", v); sub(/^[ \t]+/, "", v); sub(/[ \t]+$/, "", v) }
      print v
    }' .env
}
# env_edit AWK-ARGS... rewrites .env through awk. It writes back into the same
# file rather than moving a new one over it, so mode 600 and the owner survive.
env_edit() {
  local tmp
  tmp=$(mktemp "${TMPDIR:-/tmp}/conformiti-env.XXXXXX") || die "could not create a temporary file to update .env"
  if awk "$@" .env > "$tmp" && cat "$tmp" > .env; then rm -f "$tmp"; else rm -f "$tmp"; die "could not update .env"; fi
}
# env_set KEY VALUE replaces every KEY= line with one KEY=VALUE, or appends it.
env_set() {
  env_edit -v k="$1" -v v="$2" '
    index($0, k "=") == 1 { if (!done) print k "=" v; done = 1; next }
    { print }
    END { if (!done) print k "=" v }'
}
# env_move_origins OLD NEW moves the localhost origins this script writes into
# CSRF_TRUSTED_ORIGINS / CORS_ALLOWED_ORIGINS from port OLD to port NEW. Any
# other origin (a real hostname, a proxy) is left exactly as it is. A CRLF
# line's CR is set aside while the last origin is compared, then put back.
env_move_origins() {
  env_edit -v o="$1" -v n="$2" '
    /^(CSRF_TRUSTED_ORIGINS|CORS_ALLOWED_ORIGINS)=/ {
      cr = sub(/\r$/, "")
      eq = index($0, "="); line = substr($0, 1, eq); cnt = split(substr($0, eq + 1), a, ",")
      for (i = 1; i <= cnt; i++) {
        if (a[i] == "http://localhost:" o || a[i] == "http://127.0.0.1:" o) sub(":" o "$", ":" n, a[i])
        line = line (i > 1 ? "," : "") a[i]
      }
      print line (cr ? "\r" : ""); next
    }
    { print }'
}
CR=$(printf '\r')  # for a grep pattern that has to allow a CRLF .env

# port_busy PORT is true when something already accepts connections on
# 127.0.0.1:PORT. It uses bash's /dev/tcp; where that is missing it says free.
port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
# stack_holds SERVICE CONTAINER-PORT HOST-PORT is true when this project's own
# running SERVICE already publishes HOST-PORT, which is what a re-run finds.
stack_holds() { grep -q ":$3\$" <<< "$(docker compose port "$1" "$2" 2>/dev/null | tr -d '\r')"; }
# own_admin_state prints "yes" when the running stack's Default workspace has
# an administrator that is not a demo account, "no" when it has none, and
# nothing when the stack cannot say (it is not up, or its image is older than
# the test). It is the question remove_demo_data asks before it will run.
own_admin_state() {
  docker compose exec -T backend python manage.py shell -v 0 -c "from accounts import tenancy; from accounts.management.commands.bootstrap_demo import own_administrator_present as f; print('own_admin=' + ('yes' if f(tenancy.from_option({})) else 'no'))" 2>/dev/null \
    | tr -d '\r' | sed -n 's/^own_admin=//p' | tail -n 1
}
# retire_demo_advice PRINTER says, one PRINTER call per line, what to run
# before real use. remove_demo_data refuses until an administrator of the
# operator's own exists, so createsuperuser comes first unless the stack says
# there already is one; when it cannot say, the advice covers both cases.
retire_demo_advice() {
  local p="$1" state
  state=$(own_admin_state || true)
  if [ "$state" = "yes" ]; then
    "$p" "${YEL}Before real use:${RESET} docker compose exec backend python manage.py remove_demo_data"
    return 0
  fi
  if [ "$state" = "no" ]; then
    "$p" "${YEL}Before real use,${RESET} create an administrator of your own (remove_demo_data refuses"
    "$p" "until one exists), then retire the demo accounts:"
  else
    "$p" "${YEL}Before real use,${RESET} create an administrator of your own if you have none yet"
    "$p" "(remove_demo_data refuses until one exists), then retire the demo accounts:"
  fi
  "$p" "  docker compose exec backend python manage.py createsuperuser"
  "$p" "  docker compose exec backend python manage.py remove_demo_data"
}
banner_line() { printf "%s\n" "  $*"; }

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
  # docker-compose.yml's optional .env entry (`required: false`) and the ghcr
  # file's `!reset` need Compose 2.24.0; an older one rejects the file. The
  # short form is "2.40.3", "v2.20.2" or a distribution's "2.40.3+ds1-...".
  COMPOSE_VER=$(docker compose version --short 2>/dev/null | tr -d '\r' | sed -n 's/^[^0-9]*\([0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\).*/\1/p' | head -n 1 || true)
  if [ -n "$COMPOSE_VER" ]; then
    IFS=. read -r C_MAJOR C_MINOR _ <<< "$COMPOSE_VER"
    if [ "$C_MAJOR" -lt 2 ] || { [ "$C_MAJOR" -eq 2 ] && [ "$C_MINOR" -lt 24 ]; }; then
      die "Docker Compose 2.24.0 or newer is required (found ${COMPOSE_VER}): older releases reject the compose file's optional .env entry. Update Docker Desktop or the Compose plugin."
    fi
  else
    warn "could not read the Docker Compose version; the compose file needs 2.24.0 or newer."
  fi
  docker info >/dev/null 2>&1 || die "The Docker daemon is not running or not reachable."
  command -v curl >/dev/null 2>&1 || die "curl is required to wait for the stack to become healthy."

  if [ ! -f .env ]; then
    HOSTS="localhost,127.0.0.1,backend,$(hostname 2>/dev/null || echo conformiti)"
    cat > .env <<ENV
# Written by install.sh --docker on $(date -u +%Y-%m-%dT%H:%MZ). Safe production-style
# defaults for a LAN deployment over plain HTTP. See .env.example for every key.
#
# The Docker stack reads CONFORMITI_DEBUG / CONFORMITI_SECRET_KEY, not
# DJANGO_DEBUG / DJANGO_SECRET_KEY: those two belong to the local dev path and
# must never leak into a container. CONFORMITI_SECRET_KEY is left unset on
# purpose: the container generates its own key and keeps it in the 'secrets'
# volume, which scripts/backup.sh saves with the database.
CONFORMITI_DEBUG=false
DJANGO_ALLOWED_HOSTS=${HOSTS}
CSRF_TRUSTED_ORIGINS=http://localhost:${PORT},http://127.0.0.1:${PORT}
CORS_ALLOWED_ORIGINS=http://localhost:${PORT}
# Flip to true once a TLS-terminating proxy sits in front of nginx.
BEHIND_TLS=false
EMAIL_PROVIDER=console
SEED_DEMO_DATA=${DEMO}
CONFORMITI_PORT=${PORT}
ENV
    # No secret in it yet, but mail and database passwords usually end up in
    # this file later: not world-readable.
    chmod 600 .env 2>/dev/null || true
    ok ".env written (DEBUG off, demo data ${DEMO}, mode 600)"
    ok "no secret key in .env: the container generates one and keeps it in the 'secrets' volume"
  else
    ok ".env already present: using it"
    if grep -Eq '^CONFORMITI_DEBUG=(1|true|yes|on)' .env; then
      warn "your .env sets CONFORMITI_DEBUG=true, so the Docker stack will run in DEBUG mode."
      warn "For a real deployment set CONFORMITI_DEBUG=false."
    fi
    if grep -Eq '^DJANGO_DEBUG=(1|true|yes|on)' .env && ! grep -q '^CONFORMITI_DEBUG=' .env; then
      warn "your .env has DJANGO_DEBUG=true (from the local dev path). It does NOT"
      warn "affect the Docker stack, which stays in production mode. Set"
      warn "CONFORMITI_DEBUG=true if you deliberately want a DEBUG container."
    fi
    # --demo / --no-demo: the stack seeds from SEED_DEMO_DATA in .env, so a flag
    # that disagrees with it is written there instead of being ignored. The
    # values below are the ones backend/entrypoint.sh treats as "seed".
    if [ -n "$DEMO_SET" ]; then
      ENV_DEMO=$(env_get SEED_DEMO_DATA)
      case "$ENV_DEMO" in 1|true|TRUE|yes|on) ENV_DEMO_ON="true" ;; *) ENV_DEMO_ON="false" ;; esac
      if [ "$DEMO" != "$ENV_DEMO_ON" ]; then
        env_set SEED_DEMO_DATA "$DEMO"
        if [ "$DEMO" = "true" ]; then
          ok "--demo: set SEED_DEMO_DATA=true in .env (it was ${ENV_DEMO:-unset})"
        else
          ok "--no-demo: set SEED_DEMO_DATA=false in .env (it was ${ENV_DEMO})"
          warn "demo accounts that already exist stay until remove_demo_data retires them."
          retire_demo_advice warn
        fi
      fi
    fi
    # --port wins over CONFORMITI_PORT in .env, and is saved there so a later
    # plain `docker compose up` keeps using it. Without --port, .env decides.
    ENV_PORT=$(env_get CONFORMITI_PORT | tr -cd '0-9')
    if [ -n "$PORT_SET" ]; then
      OLD_PORT="${ENV_PORT:-8080}"
      if [ "$PORT" != "$OLD_PORT" ]; then
        env_set CONFORMITI_PORT "$PORT"
        ok "--port: set CONFORMITI_PORT=${PORT} in .env (it was ${ENV_PORT:-unset, so 8080})"
        if grep -Eq "^(CSRF_TRUSTED_ORIGINS|CORS_ALLOWED_ORIGINS)=(.*,)?http://(localhost|127\.0\.0\.1):${OLD_PORT}(,|${CR}?\$)" .env; then
          env_move_origins "$OLD_PORT" "$PORT"
          ok "--port: moved the localhost origins in CSRF_TRUSTED_ORIGINS / CORS_ALLOWED_ORIGINS from ${OLD_PORT} to ${PORT}"
        fi
      fi
    else
      PORT="${ENV_PORT:-8080}"
    fi
  fi

  # A host port something else holds would stop Compose part way, with the
  # database up and the API left without a network. Ports this project's own
  # containers publish are fine: that is a re-run, and Compose recreates them.
  # The API port is read the way Compose reads it: the shell first, then .env.
  API_PORT="${CONFORMITI_API_PORT:-$(env_get CONFORMITI_API_PORT | tr -cd '0-9')}"; API_PORT="${API_PORT:-8000}"
  if port_busy "$PORT" && ! stack_holds frontend 80 "$PORT"; then
    die "port ${PORT} is already in use on this machine. Choose another with --port N (it is saved as CONFORMITI_PORT in .env)."
  fi
  if port_busy "$API_PORT" && ! stack_holds backend 8000 "$API_PORT"; then
    die "port ${API_PORT} on 127.0.0.1, where the stack publishes its API, is already in use (a local 'manage.py runserver' is the usual holder). Set CONFORMITI_API_PORT to a free port in .env and run this again."
  fi

  say "Building images and starting the stack (first build takes a few minutes)…"
  # Passed explicitly so a CONFORMITI_PORT exported in this shell (which would
  # beat .env) cannot publish the app on a port other than the one waited on.
  CONFORMITI_PORT="$PORT" docker compose up -d --build
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
  # What the running stack holds decides the banner, not the flags: a .env or
  # an earlier run can seed demo accounts this run never asked for.
  case "$HEALTH" in *'"demo_accounts":true'*|*'"demo_accounts": true'*) DEMO_LIVE="true" ;; *) DEMO_LIVE="false" ;; esac
  if [ "$DEMO_LIVE" = "true" ]; then
    # The stack runs detached, so bootstrap_demo's one-time "Sign in as" line
    # is only in the backend log, and only when this container created the
    # accounts; a container that found them already there never prints it.
    DEMO_PW=$(docker compose logs --no-color --no-log-prefix backend 2>/dev/null | tr -d '\r' | sed -n 's/.*Sign in as *admin *\/ *//p' | tail -n 1 || true)
    printf "%s\n" "  ${BOLD}Sign in${RESET}  admin   ${DIM}(also mia, owen, aria, val; same password)${RESET}"
    if [ -n "$DEMO_PW" ]; then
      printf "%s\n" "  ${BOLD}Password${RESET} ${DEMO_PW}   ${DIM}(note it now)${RESET}"
      printf "%s\n" "  ${DIM}The backend log keeps it only until that container is recreated, which --port,${RESET}"
      printf "%s\n" "  ${DIM}an update or any .env change does.${RESET}"
    else
      printf "%s\n" "  ${DIM}Password: not in the current backend log. It is printed once, by the container that${RESET}"
      printf "%s\n" "  ${DIM}created the demo accounts. Set a new one for admin with:${RESET}"
      printf "%s\n" "  ${DIM}  docker compose exec backend python manage.py changepassword admin${RESET}"
    fi
    retire_demo_advice banner_line
  else
    if [ "$DEMO" = "true" ]; then
      warn "--demo was given but the stack reports no demo accounts. Check: docker compose logs backend"
    fi
    # first_admin_needed is true only while no active account exists, so a
    # re-run or an update on a used installation is not told to make one.
    # An image older than the field says neither, hence the third wording.
    case "$HEALTH" in
      *'"first_admin_needed":true'*|*'"first_admin_needed": true'*)
        printf "%s\n" "  Create your first account: docker compose exec backend python manage.py createsuperuser" ;;
      *'"first_admin_needed":false'*|*'"first_admin_needed": false'*)
        printf "%s\n" "  ${BOLD}Sign in${RESET}  with an existing account (this installation already has one)" ;;
      *)
        printf "%s\n" "  No account yet? docker compose exec backend python manage.py createsuperuser" ;;
    esac
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
[ -n "$PY" ] || die "Python 3.11 or newer is required but was not found on PATH (tested: 3.11 to 3.14)."
# Newer than the tested range is allowed, not refused: it usually works, but
# a dependency without wheels for it yet is the usual way it does not.
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info < (3, 15) else 1)' 2>/dev/null; then
  warn "$("$PY" --version 2>&1) is newer than the tested range (3.11 to 3.14): carrying on, but it is untested."
fi
command -v node >/dev/null 2>&1 || die "Node.js 20.19+ or 22.12+ (with npm) is required but was not found on PATH."
command -v npm >/dev/null 2>&1 || die "npm is required but was not found on PATH."
# Mirrors frontend/package.json engines, "^20.19.0 || >=22.12.0" (Vite 8):
# 21.x and 22.0 to 22.11 are refused there, so they are refused here too.
NODE_OK=$(node -e 'const [a,b]=process.versions.node.split(".").map(Number); process.stdout.write(((a===20&&b>=19)||(a===22&&b>=12)||a>22)?"y":"n")')
[ "$NODE_OK" = "y" ] || die "Node.js 20.19+ or 22.12+ is required (found $(node --version))."
ok "using $($PY --version 2>&1), node $(node --version), npm $(npm --version)"

# The local path's own ports, never the Docker ones: a CONFORMITI_API_PORT
# exported for the stack must not put runserver on the stack's API port.
# Vite reads the same two names from the environment (frontend/vite.config.js).
DEV_API_PORT="${CONFORMITI_DEV_API_PORT:-8000}"; DEV_PORT="${CONFORMITI_DEV_PORT:-5173}"
if [ "$MODE" != "test" ]; then
  check_port CONFORMITI_DEV_API_PORT "$DEV_API_PORT"
  check_port CONFORMITI_DEV_PORT "$DEV_PORT"
fi

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
  chmod 600 .env 2>/dev/null || true
  ok ".env created (SQLite + console email; a secret key was generated, mode 600)"
else
  ok ".env already present: leaving it untouched"
fi
# Sign-in is refused from any origin CSRF_TRUSTED_ORIGINS does not list, and
# .env.example lists http://localhost:5173 only, so a moved web app says so.
if [ "$MODE" != "test" ] && [ "$DEV_PORT" != "5173" ]; then
  ORIGINS=$(env_get CSRF_TRUSTED_ORIGINS | tr -d ' ')
  case ",${CSRF_TRUSTED_ORIGINS:-${ORIGINS:-http://localhost:5173}}," in
    *",http://localhost:${DEV_PORT},"*) ;;
    *) warn "CONFORMITI_DEV_PORT is ${DEV_PORT}: add http://localhost:${DEV_PORT} to CSRF_TRUSTED_ORIGINS and"
       warn "CORS_ALLOWED_ORIGINS in .env, or every sign-in from the web app is refused." ;;
  esac
fi

# --- Python virtualenv + backend deps --------------------------------------
# An existing .venv is reused only when its pip runs. Without Debian's venv
# package, `python3 -m venv` stops at ensurepip and leaves a .venv/bin/python
# with no pip behind, and every later run would die at the pip step.
VPY=".venv/bin/python"
PY_VER=$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
if [ -x "$VPY" ] && ! "$VPY" -m pip --version >/dev/null 2>&1; then
  warn "the existing .venv has no working pip (an earlier creation probably stopped part way): recreating it"
  rm -rf .venv
fi
if [ ! -x "$VPY" ]; then
  "$PY" -c 'import ensurepip, venv' >/dev/null 2>&1 \
    || die "Python ${PY_VER} has no ensurepip, so it cannot give a new .venv its pip. On Debian or Ubuntu run: sudo apt install python${PY_VER}-venv   and then run this again."
  say "Creating Python virtual environment (.venv)…"
  rm -rf .venv
  if ! "$PY" -m venv .venv || ! "$VPY" -m pip --version >/dev/null 2>&1; then
    rm -rf .venv
    die "creating .venv with ${PY} failed (see above). On Debian or Ubuntu, sudo apt install python${PY_VER}-venv is the usual fix; then run this again."
  fi
fi
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
# `npm ci` installs exactly what the lock file pins and never rewrites it;
# `npm install` from npm 10 drops the lock's libc fields and leaves the
# checkout dirty. npm install stays for a tree without a lock file.
if [ -f frontend/package-lock.json ]; then
  ( cd frontend && npm ci --no-fund --no-audit --silent )
else
  ( cd frontend && npm install --no-fund --no-audit --silent )
fi
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
DEMO_PW=""; DEMO_STATE=""
if [ "$DEMO" = "true" ]; then
  # Captured so the banner below can repeat the one-time password. It is only
  # printed when this run created the accounts; a re-run keeps the old one.
  if ! DEMO_OUT=$(cd backend && ../"$VPY" manage.py bootstrap_demo); then
    printf "%s\n" "$DEMO_OUT"
    die "loading the demo data failed (see above)."
  fi
  printf "%s\n" "$DEMO_OUT"
  DEMO_PW=$(printf "%s\n" "$DEMO_OUT" | tr -d '\r' | sed -n 's/.*Sign in as *admin *\/ *//p' | tail -n 1)
  # bootstrap_demo exits 0 in all three cases, so its words tell them apart.
  # "retired": remove_demo_data retired the demo here, and the accounts are
  # switched off or gone, so there is nothing to sign in with.
  case "$DEMO_OUT" in
    *"Demo data not seeded"*) DEMO_STATE="retired" ;;
    *"existing accounts kept their password"*) DEMO_STATE="kept" ;;
    *) DEMO_STATE="loaded" ;;
  esac
  if [ "$DEMO_STATE" = "retired" ]; then
    ok "database ready (SOC 2 · ISO 27001 · PCI DSS seeded; demo data retired, not loaded)"
    warn "remove_demo_data retired the demo in this database, so --demo loaded nothing and"
    warn "there are no demo accounts to sign in with. To seed them again anyway:"
    warn "  cd backend && ../.venv/bin/python manage.py bootstrap_demo --force"
  else
    ok "database ready (SOC 2 · ISO 27001 · PCI DSS seeded, demo data loaded)"
  fi
else
  ok "database ready (SOC 2 · ISO 27001 · PCI DSS seeded, no demo data)"
  warn "create your first account with: cd backend && ../.venv/bin/python manage.py createsuperuser"
fi

# --- Done ------------------------------------------------------------------
cat <<BANNER

${GREEN}${BOLD}Setup complete.${RESET}
BANNER
if [ "$DEMO" = "true" ] && [ "$DEMO_STATE" != "retired" ]; then
  printf "%s\n" "  ${BOLD}Sign in${RESET}   admin   ${DIM}(also mia, owen, aria, val; same password)${RESET}"
  if [ -n "$DEMO_PW" ]; then
    printf "%s\n" "  ${BOLD}Password${RESET}  ${DEMO_PW}   ${DIM}(not shown again: note it now)${RESET}"
  elif [ "$DEMO_STATE" = "kept" ]; then
    printf "%s\n" "  ${DIM}Password: unchanged. The demo accounts already existed and kept the one set when${RESET}"
    printf "%s\n" "  ${DIM}they were created. Set a new one for admin with:${RESET}"
    printf "%s\n" "  ${DIM}  cd backend && ../.venv/bin/python manage.py changepassword admin${RESET}"
  else
    printf "%s\n" "  ${DIM}Password: not in the seeding output above. Set one for admin with:${RESET}"
    printf "%s\n" "  ${DIM}  cd backend && ../.venv/bin/python manage.py changepassword admin${RESET}"
  fi
fi
cat <<BANNER
  ${BOLD}Tests${RESET}     ./install.sh --test
  ${BOLD}Mailer${RESET}    cd backend && ../.venv/bin/python manage.py send_review_reminders --dry-run

BANNER

if [ "$MODE" = "setup" ]; then
  # A moved port has to reach Vite too, so the command carries it.
  DEV_ENV=""
  [ "$DEV_API_PORT" = "8000" ] || DEV_ENV="CONFORMITI_DEV_API_PORT=${DEV_API_PORT} "
  [ "$DEV_PORT" = "5173" ] || DEV_ENV="${DEV_ENV}CONFORMITI_DEV_PORT=${DEV_PORT} "
  cat <<NEXT
To start the app later, run:
  (backend)   cd backend && ../.venv/bin/python manage.py runserver 127.0.0.1:${DEV_API_PORT}
  (frontend)  cd frontend && ${DEV_ENV}npm run dev
Then open ${BOLD}http://localhost:${DEV_PORT}${RESET}
${DIM}Ports: CONFORMITI_DEV_API_PORT=${DEV_API_PORT} (API), CONFORMITI_DEV_PORT=${DEV_PORT} (web app); set them in the shell to move either.${RESET}
NEXT
  exit 0
fi

say "Starting servers: API on :${DEV_API_PORT} (CONFORMITI_DEV_API_PORT), web app on :${DEV_PORT} (CONFORMITI_DEV_PORT)."
say "Open ${BOLD}http://localhost:${DEV_PORT}${RESET} in your browser. Press Ctrl-C to stop."
# `kill 0` signals this script's whole process group, the script included, so
# the handler disarms itself first. Otherwise the TERM it sends would run it
# again, and again, until bash crashed. Ctrl-C and TERM are how a user stops
# the servers, so they end the script with 0; a plain exit keeps its status.
stop_servers() {  # $1 = INT, TERM or EXIT
  local rc=$?
  trap - EXIT
  trap '' INT TERM
  echo; say "Shutting down…"
  kill 0 2>/dev/null || true
  wait 2>/dev/null || true
  [ "$1" = "EXIT" ] || rc=0
  exit "$rc"
}
trap 'stop_servers EXIT' EXIT
trap 'stop_servers INT' INT
trap 'stop_servers TERM' TERM
( cd backend && exec ../.venv/bin/python manage.py runserver "127.0.0.1:${DEV_API_PORT}" ) &
( cd frontend && exec npm run dev ) &
( sleep 6 && open_url "http://localhost:${DEV_PORT}" ) &
wait
