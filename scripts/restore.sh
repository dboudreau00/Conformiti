#!/usr/bin/env sh
# Restore a backup made by scripts/backup.sh into a Docker Compose
# installation, replacing whatever is there. Run it from the checkout:
#
#   scripts/restore.sh backups/<timestamp>
#
# The application containers are stopped, the database is emptied and
# reloaded from db.sql.gz, the media, secrets and tree volumes are replaced
# from their archives, and the stack is started again. A fresh machine works
# too: compose creates the network, the volumes and the containers first, so
# nothing is left behind as a foreign volume a later `up` would refuse.
set -eu
export MSYS_NO_PATHCONV=1   # Git Bash on Windows: leave /dst and /in alone

src="${1:?usage: scripts/restore.sh <backup directory>}"
src="$(cd "$src" && pwd)"
for f in db.sql.gz media.tgz secrets.tgz tree.tgz; do
  if [ ! -f "$src/$f" ]; then
    echo "restore: $src/$f is missing" >&2
    exit 1
  fi
done

docker compose up -d --no-recreate db
docker compose up --no-start
docker compose stop backend worker beat frontend

db="$(docker compose ps -q db)"
project="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project" }}' "$db")"

echo "restore: waiting for PostgreSQL"
i=0
until docker compose exec -T db sh -c 'pg_isready -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"'; do
  i=$((i + 1))
  if [ "$i" -gt 60 ]; then
    echo "restore: PostgreSQL did not come up" >&2
    exit 1
  fi
  sleep 1
done

echo "restore: database"
docker compose exec -T db sh -c \
  'exec psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"'
gunzip -c "$src/db.sql.gz" | docker compose exec -T db sh -c \
  'exec psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"'

for v in media secrets tree; do
  echo "restore: $v volume"
  docker run --rm -v "${project}_${v}:/dst" -v "$src:/in:ro" alpine:3.20 \
    sh -c "find /dst -mindepth 1 -delete && tar xzf /in/$v.tgz -C /dst"
done

echo "restore: starting the stack"
docker compose up -d
echo "restore: done. Check docker compose ps and /api/health/."
