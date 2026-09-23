#!/usr/bin/env bash
# ===========================================================================
# Container entrypoint for the API service.
#
#   1. wait for PostgreSQL (when POSTGRES_HOST is set)
#   2. apply the shipped migrations (never makemigrations: the migration
#      files are part of the release and are verified in CI)
#   3. seed the control libraries + roles (idempotent)
#   4. optionally seed the demo dataset (SEED_DEMO_DATA, default false; a
#      no-op once remove_demo_data has retired it) and/or create an initial
#      superuser from DJANGO_SUPERUSER_* (no-op if it exists; a refusal is
#      logged with its reason and the boot carries on)
#   5. collect static files for nginx, print the boot banner (which says when
#      no administrator exists and, while demo accounts are active, what to
#      run before real use), then exec the CMD (gunicorn)
#
# The Celery worker and beat use their own entrypoints (see
# docker-compose.yml) and depend on this container being healthy, so
# migrations run exactly once.
# ===========================================================================
set -euo pipefail

log() { printf '%s [entrypoint] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

if [ -n "${POSTGRES_HOST:-}" ]; then
  log "Waiting for PostgreSQL at ${POSTGRES_HOST}:${POSTGRES_PORT:-5432}…"
  python - <<'PY'
import os, socket, sys, time
host, port = os.environ["POSTGRES_HOST"], int(os.getenv("POSTGRES_PORT", "5432"))
for attempt in range(60):
    try:
        socket.create_connection((host, port), 2).close()
        sys.exit(0)
    except OSError:
        time.sleep(1)
print("PostgreSQL did not become reachable in 60s", file=sys.stderr)
sys.exit(1)
PY
fi

log "Applying migrations"
python manage.py migrate --noinput

log "Seeding control libraries, roles and folder tree in every workspace"
# --all-workspaces: a release that adds a role or a control used to reach
# only Default on boot; every other organisation on the installation kept
# the previous release's libraries until someone ran this by hand.
python manage.py seed_frameworks --with-folders --all-workspaces

case "${SEED_DEMO_DATA:-false}" in
  1|true|TRUE|yes|on)
    log "Seeding demo dataset (SEED_DEMO_DATA=true)"
    # bootstrap_demo prints the generated sign-in password on first boot.
    # Set DEMO_PASSWORD to choose it, or SEED_DEMO_DATA=false to skip. After
    # remove_demo_data it seeds nothing: the container keeps this variable
    # for life, and restart: unless-stopped reruns this on every reboot.
    # With both DJANGO_SUPERUSER_* values set, the step below creates that
    # account after this one, so --superuser-follows has the seed leave its
    # before-real-use advice to the banner at the end instead of telling the
    # operator to run createsuperuser first. The flag is added only when both
    # are non-empty, the test that step applies.
    python manage.py bootstrap_demo \
      ${DJANGO_SUPERUSER_USERNAME:+${DJANGO_SUPERUSER_PASSWORD:+--superuser-follows}}
    ;;
  *)
    # Defaulted for the same reason as CLAMAV_ENABLED below: `set -u` makes a
    # bare expansion fatal, and this branch is the one an image run without any
    # environment at all takes.
    log "Skipping demo dataset (SEED_DEMO_DATA=${SEED_DEMO_DATA:-unset})"
    ;;
esac

if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
  log "Ensuring superuser '${DJANGO_SUPERUSER_USERNAME}' exists"
  # createsuperuser fails both when the account is already there (every boot
  # after the first) and when it refuses to make it, most often because
  # DJANGO_SUPERUSER_PASSWORD fails the password policy. Its own message says
  # which, so it is kept: discarding it behind "already exists" left an
  # installation with no administrator and nothing in the log to say why.
  # Either way the boot carries on, and the banner below says when no
  # administrator exists at all. The email fallback is not an @example.com
  # address: an account named admin with one is the demo administrator to
  # /api/health/, the banner and remove_demo_data.
  if su_err=$(python manage.py createsuperuser --noinput \
      --username "${DJANGO_SUPERUSER_USERNAME}" \
      --email "${DJANGO_SUPERUSER_EMAIL:-admin@localhost}" 2>&1 >/dev/null); then
    log "Superuser '${DJANGO_SUPERUSER_USERNAME}' created"
  elif [[ "$su_err" == *"is already taken"* ]]; then
    # Django's own words for "an account with this username exists".
    log "Superuser '${DJANGO_SUPERUSER_USERNAME}' already exists, leaving it alone"
  else
    log "!! Superuser '${DJANGO_SUPERUSER_USERNAME}' was NOT created. createsuperuser said:"
    while IFS= read -r line; do
      if [ -n "$line" ]; then log "!!   ${line}"; fi
    done <<<"$su_err"
    # The policy advice only when the policy refused it (accounts/tenancy.py
    # words that refusal): a bad email or a database error is not the password.
    if [[ "$su_err" == *"password policy"* ]]; then
      log "!! DJANGO_SUPERUSER_PASSWORD must pass the password policy (at least"
      log "!! PASSWORD_MIN_LENGTH characters, 12 by default, not a common password, not"
      log "!! all digits, not close to the username or email)."
    fi
    log "!! Fix the cause above where you set DJANGO_SUPERUSER_* (.env or the shell)"
    log "!! and run docker compose up -d again, or create one by hand:"
    log "!!   docker compose exec backend python manage.py createsuperuser"
  fi
elif [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] || [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
  log "!! DJANGO_SUPERUSER_USERNAME and DJANGO_SUPERUSER_PASSWORD must both be set;"
  log "!! with only one of them no superuser is created."
fi

python manage.py generate_folder_tree >/dev/null 2>&1 || log "generate_folder_tree skipped (tree root not writable)"
python manage.py collectstatic --noinput >/dev/null

# Say at boot whether the scanner is reachable, rather than at the first upload.
# Defaulted: `set -euo pipefail` above would kill the container on a bare
# ${CLAMAV_ENABLED} for every default `docker compose up`.
if [ "${CLAMAV_ENABLED:-false}" = "true" ]; then
  if python -c "
import os, sys
sys.path.insert(0, '.')
from documents.clamav import ping
sys.exit(0 if ping(os.getenv('CLAMAV_HOST', 'clamav'), int(os.getenv('CLAMAV_PORT', '3310'))) else 1)
" 2>/dev/null; then
    log "Malware scanning ON - clamd answered at ${CLAMAV_HOST:-clamav}:${CLAMAV_PORT:-3310}"
  else
    log "!! Malware scanning is ON but clamd did not answer. Uploads will be REFUSED"
    log "!! until it does (scanning fails closed on purpose). Start it with:"
    log "!!   docker compose --profile scanning up -d clamav"
  fi
fi

python - <<'PY'
import os
from config.version import __version__
# DEBUG is read the way the image sets it, not the way the code defaults for
# a developer running it. Reading DEBUG as on when the image pins it off is a
# false alarm, and the line that matters is the one nobody believes.
debug = os.getenv("DJANGO_DEBUG", "false").lower() in ("1", "true", "yes", "on")
# The demo line reports the database, with the same test /api/health/ uses,
# not SEED_DEMO_DATA: the variable stays set on a container after
# remove_demo_data has retired the accounts, and accounts seeded on an earlier
# boot outlive a restart without it. Guarded, because `set -euo pipefail`
# above would kill the container over a banner; if the lookup fails,
# SEED_DEMO_DATA is the best guess left.
try:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django
    django.setup()
    from config.health import demo_accounts_present
    demo = demo_accounts_present()
except Exception:
    demo = os.getenv("SEED_DEMO_DATA", "false").lower() in ("1", "true", "yes", "on")
# Whether anyone can administer the installation. None when the lookup fails,
# so the banner claims nothing either way on a guess.
try:
    from config.health import administrator_present
    admin = administrator_present()
except Exception:
    admin = None
# Whether remove_demo_data would run: it refuses while the demo accounts are
# the only administrators of the workspace it cleans (Default, as the line
# below runs it), and asks this same question. None when the lookup fails,
# which gets the advice that is right either way.
try:
    from accounts import tenancy
    from accounts.management.commands.bootstrap_demo import own_administrator_present
    own_admin = own_administrator_present(tenancy.from_option({}))
except Exception:
    own_admin = None
# Read from the environment, not from django.conf, so the line stays right
# when the settings could not be loaded above.
key_src = ("from the environment" if os.getenv("DJANGO_FIELD_ENCRYPTION_KEY")
           else "from the key file" if os.getenv("DJANGO_FIELD_ENCRYPTION_KEY_FILE")
           else "derived from the signing key")
print(f"Conformiti {__version__}: DEBUG={'ON' if debug else 'off'}, demo accounts={'ON' if demo else 'off'}")
print(f"   field encryption: key ring {key_src}")
if debug:
    print("!! DJANGO_DEBUG is on. Never expose this container to a network you don't trust.")
if admin is False:
    print("!! No administrator exists yet: no active superuser, and no active account whose")
    print("!! role manages users, so nobody can sign in to run this installation. Create one:")
    print("!!   docker compose exec backend python manage.py createsuperuser")
    print("!! or set DJANGO_SUPERUSER_USERNAME and DJANGO_SUPERUSER_PASSWORD in .env and run")
    print("!! docker compose up -d again. When they are set, the log above says why no")
    print("!! account was made.")
if demo:
    print("!! Demo accounts are active. They share the password printed once when they")
    print("!! were created (or the DEMO_PASSWORD you chose).")
    if own_admin:
        print("!! Before real use run:")
    else:
        print("!! Before real use, create an administrator of your own (remove_demo_data")
        print("!! refuses until one exists), then retire the demo accounts:")
        print("!!   docker compose exec backend python manage.py createsuperuser")
    print("!!   docker compose exec backend python manage.py remove_demo_data")
PY

exec "$@"
