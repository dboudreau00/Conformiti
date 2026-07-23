#!/usr/bin/env bash
set -e

echo "Waiting for database…"
python - <<'PY'
import os, time
import socket
host = os.getenv("POSTGRES_HOST")
if host:
    for _ in range(30):
        try:
            socket.create_connection((host, int(os.getenv("POSTGRES_PORT", "5432"))), 2).close()
            break
        except OSError:
            time.sleep(1)
PY

python manage.py makemigrations accounts compliance documents calendar_app notifications audit governance integrations
python manage.py migrate --noinput

# Seed control libraries + folders + demo data on first run (idempotent).
python manage.py seed_frameworks --with-folders
python manage.py bootstrap_demo || true
python manage.py generate_folder_tree || true
python manage.py collectstatic --noinput || true

exec "$@"
