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
#
# .env is not in the backup: it is your own configuration. On a fresh machine
# write it back before running this (see the note printed below when it is
# missing). This script is for the Docker stack only; for an installation run
# without Docker, see "Backups on bare metal" in INSTALL.md.
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

if ! command -v docker >/dev/null 2>&1; then
  echo "restore: docker is not installed on this machine. This script restores the Docker" >&2
  echo "restore: Compose stack; for an installation run without Docker, see \"Backups on bare" >&2
  echo "restore: metal\" in INSTALL.md." >&2
  exit 1
fi

# The database volume created below keeps the POSTGRES_PASSWORD it is created
# with, and the volumes are named after COMPOSE_PROJECT_NAME. A .env written
# after the restore therefore no longer matches what was restored, so say so
# while there is still time to stop. A terminal gets a pause to stop in; a run
# with no terminal (a script, CI) carries on after the note.
if [ ! -f .env ]; then
  echo "restore: there is no .env in this directory, so the stack comes up on the defaults in" >&2
  echo "restore: docker-compose.yml. .env is not part of a backup: if the installation you backed" >&2
  echo "restore: up had one, stop here, write it back from your own records (POSTGRES_PASSWORD," >&2
  echo "restore: REDIS_PASSWORD, PUBLIC_URL, DJANGO_ALLOWED_HOSTS and the origin lists, mail, and" >&2
  echo "restore: COMPOSE_PROJECT_NAME or ports if you set them) and run this again." >&2
  if [ -t 0 ]; then
    printf 'restore: press Enter to restore on the defaults, or Ctrl-C to stop. ' >&2
    read -r _answer
  fi
fi

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
# -q quiets psql, not the server: without the SET, the CASCADE drop prints a
# NOTICE and a DETAIL line for every table it takes with it. pg_dump's output
# sets that level itself, but -q does not hide query results, and the dump
# runs a SELECT for every sequence (setval) and one set_config: -o /dev/null
# drops those tables. Errors still go to stderr, and ON_ERROR_STOP still
# stops the load with a non-zero exit.
docker compose exec -T db sh -c \
  'exec psql -v ON_ERROR_STOP=1 -q -o /dev/null -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SET client_min_messages = warning; DROP SCHEMA public CASCADE; CREATE SCHEMA public;"'
gunzip -c "$src/db.sql.gz" | docker compose exec -T db sh -c \
  'exec psql -v ON_ERROR_STOP=1 -q -o /dev/null -U "$POSTGRES_USER" -d "$POSTGRES_DB"'

for v in media secrets tree; do
  echo "restore: $v volume"
  docker run --rm -v "${project}_${v}:/dst" -v "$src:/in:ro" alpine:3.20 \
    sh -c "find /dst -mindepth 1 -delete && tar xzf /in/$v.tgz -C /dst"
done

echo "restore: starting the stack"
docker compose up -d
echo "restore: done. Check docker compose ps and /api/health/."
