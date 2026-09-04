#!/usr/bin/env bash
# ===========================================================================
# Container entrypoint for the API service.
#
#   1. wait for PostgreSQL (when POSTGRES_HOST is set)
#   2. apply the shipped migrations (never makemigrations: the migration
#      files are part of the release and are verified in CI)
#   3. seed the control libraries + roles (idempotent)
#   4. optionally seed the demo dataset (SEED_DEMO_DATA, default true) and/or
#      create an initial superuser from DJANGO_SUPERUSER_* (no-op if it exists)
#   5. collect static files for nginx, then exec the CMD (gunicorn)
#
# The Celery worker uses its own entrypoint (see docker-compose.yml) and
# depends on this container being healthy, so migrations run exactly once.
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

log "Seeding control libraries, roles and folder tree"
python manage.py seed_frameworks --with-folders

case "${SEED_DEMO_DATA:-true}" in
  1|true|TRUE|yes|on)
    log "Seeding demo dataset (SEED_DEMO_DATA=true)"
    python manage.py bootstrap_demo
    ;;
  *)
    log "Skipping demo dataset (SEED_DEMO_DATA=${SEED_DEMO_DATA})"
    ;;
esac

if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
  log "Ensuring superuser '${DJANGO_SUPERUSER_USERNAME}' exists"
  python manage.py createsuperuser --noinput \
    --username "${DJANGO_SUPERUSER_USERNAME}" \
    --email "${DJANGO_SUPERUSER_EMAIL:-admin@example.com}" 2>/dev/null \
    || log "Superuser already exists — leaving it alone"
fi

python manage.py generate_folder_tree >/dev/null 2>&1 || log "generate_folder_tree skipped (tree root not writable)"
python manage.py collectstatic --noinput >/dev/null

python - <<'PY'
import os
from config.version import __version__
debug = os.getenv("DJANGO_DEBUG", "true").lower() in ("1", "true", "yes", "on")
demo = os.getenv("SEED_DEMO_DATA", "true").lower() in ("1", "true", "yes", "on")
print(f"Conformiti {__version__} — DEBUG={'ON' if debug else 'off'}, demo data={'ON' if demo else 'off'}")
if debug:
    print("!! DJANGO_DEBUG is on. Never expose this container to a network you don't trust.")
if demo:
    print("!! Demo accounts are seeded with the published password. Before real use run:")
    print("!!   docker compose exec backend python manage.py remove_demo_data")
PY

exec "$@"
