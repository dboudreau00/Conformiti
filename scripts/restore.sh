#!/usr/bin/env sh
# Restore a backup made by scripts/backup.sh into a Docker Compose
# installation, replacing whatever is there. Run it from the checkout:
#
#   scripts/restore.sh [--yes] backups/<timestamp>
#
# Every archive is read end to end first, so a damaged one stops the run before
# anything is changed. On a terminal it then asks you to type yes; --yes (or no
# terminal, as in a script or CI) goes straight on.
#
# The application containers are stopped, the three volumes are unpacked to a
# scratch directory inside each (the old files stay where they are), the
# database is emptied and reloaded from db.sql.gz in ONE transaction, and only
# when that has committed are the volumes swapped for the unpacked copies and
# the stack started again. A failure before the swap changes nothing: the old
# database rolls back, the scratch directories are removed, and a stack that was
# running is started again. Each volume needs room for a second copy while this
# runs. A fresh machine works too: compose creates the network, the volumes and
# the containers first, so nothing is left behind as a foreign volume a later
# `up` would refuse.
#
# .env is not in the backup: it is your own configuration. On a fresh machine
# write it back before running this (see the note printed below when it is
# missing). This script is for the Docker stack only; for an installation run
# without Docker, see "Backups on bare metal" in INSTALL.md.
set -eu
export MSYS_NO_PATHCONV=1   # Git Bash on Windows: leave /dst and /in alone

assume_yes=0
if [ "${1:-}" = "--yes" ]; then
  assume_yes=1
  shift
fi
src="${1:?usage: scripts/restore.sh [--yes] <backup directory>}"
src="$(cd "$src" && pwd)"
for f in db.sql.gz media.tgz secrets.tgz tree.tgz; do
  if [ ! -f "$src/$f" ]; then
    echo "restore: $src/$f is missing" >&2
    exit 1
  fi
done

# The steps below replace the database and three volumes. A truncated or
# corrupt archive is better found before any of that starts, and a pipe into
# psql reports psql's status, not gunzip's. So read them all first.
echo "restore: checking the archives"
if ! gunzip -t "$src/db.sql.gz" 2>/dev/null; then
  echo "restore: $src/db.sql.gz is damaged: it does not decompress. Nothing was changed." >&2
  exit 1
fi
for v in media secrets tree; do
  if ! tar tzf "$src/$v.tgz" >/dev/null 2>&1; then
    echo "restore: $src/$v.tgz is damaged: it cannot be read. Nothing was changed." >&2
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

# Replacing a database and three volumes is not undoable, so on a terminal say
# what is about to happen and wait for a yes.
if [ "$assume_yes" -ne 1 ] && [ -t 0 ]; then
  echo "restore: this replaces the database and the media, secrets and tree volumes of the stack" >&2
  echo "restore: in $(pwd) with the contents of $src." >&2
  printf 'restore: type yes to go on: ' >&2
  read -r _answer
  if [ "$_answer" != "yes" ]; then
    echo "restore: stopped. Nothing was changed." >&2
    exit 1
  fi
fi

# Compose prints a status line per container for every up and stop. Where it
# can be told not to (--progress quiet; an older Compose refuses the flag or
# the value, so ask first: `config` checks both, `version` checks neither),
# only this script's own lines show. Errors print either way.
if docker compose --progress quiet config -q >/dev/null 2>&1; then
  compose() { docker compose --progress quiet "$@"; }
else
  compose() { docker compose "$@"; }
fi

compose up -d --no-recreate db
compose up --no-start

# What was serving before is started again if this run fails before anything
# is replaced. `up --no-start` above only creates containers, so this lists the
# ones that were really running.
running="$(docker compose ps -q --status running backend worker beat frontend)"
stopped=0
staged=0
swapping=0
project=""
work="$(mktemp -d)"
finish() {
  status=$?
  trap - EXIT
  set +e
  rm -rf "$work"
  if [ "$status" -ne 0 ]; then
    if [ "$staged" -eq 1 ] && [ "$swapping" -eq 0 ]; then
      for v in media secrets tree; do
        docker run --rm -v "${project}_${v}:/dst" alpine:3.20 rm -rf /dst/.restore-new >/dev/null 2>&1
      done
    fi
    if [ "$swapping" -eq 1 ]; then
      echo "restore: stopped while the volumes were being replaced. The database holds the backup's" >&2
      echo "restore: data and a volume may still hold the old files: run this again with the same" >&2
      echo "restore: backup. The application containers are left stopped." >&2
    elif [ "$stopped" -eq 1 ] && [ -n "$running" ]; then
      echo "restore: failed. Nothing was replaced. Starting the stack again on what it held before." >&2
      compose up -d >/dev/null 2>&1
    elif [ "$stopped" -eq 1 ]; then
      echo "restore: failed. Nothing was replaced." >&2
    fi
  fi
  exit "$status"
}
trap finish EXIT
trap 'exit 130' INT TERM HUP

compose stop backend worker beat frontend
stopped=1

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

# Unpacked first, beside the files they will replace, so a full disk or a bad
# archive is found while the old files are all still in place.
for v in media secrets tree; do
  echo "restore: unpacking the $v volume"
  staged=1
  docker run --rm -e V="$v" -v "${project}_${v}:/dst" -v "$src:/in:ro" alpine:3.20 \
    sh -c 'set -e; rm -rf /dst/.restore-new; mkdir /dst/.restore-new; tar xzf "/in/$V.tgz" -C /dst/.restore-new'
done

echo "restore: database"
# One psql session and one transaction: the drop, the new schema and the whole
# dump commit together or not at all, so a dump the server rejects part way (a
# full disk, a missing extension, a dropped connection, Ctrl-C) leaves the old
# database as it was. The transaction is opened and closed here, not with
# `psql -1`, so that COMMIT is sent only if gunzip finished: a pipeline reports
# psql's status, and a gunzip that failed after the check above would otherwise
# hand psql a short stream that ends on a statement boundary and commit it. The
# marker file records that COMMIT was sent.
# -q quiets psql, not the server: without the SET, the CASCADE drop prints a
# NOTICE and a DETAIL line for every table it takes with it. pg_dump's output
# sets that level itself, but -q does not hide query results, and the dump
# runs a SELECT for every sequence (setval) and one set_config: -o /dev/null
# drops those tables. Errors still go to stderr, and ON_ERROR_STOP still
# stops the load with a non-zero exit.
{
  echo "SET client_min_messages = warning;"
  echo "BEGIN;"
  echo "DROP SCHEMA public CASCADE;"
  echo "CREATE SCHEMA public;"
  gunzip -c "$src/db.sql.gz" && echo "COMMIT;" && : > "$work/committed"
} | docker compose exec -T db sh -c \
  'exec psql -v ON_ERROR_STOP=1 -q -o /dev/null -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
if [ ! -f "$work/committed" ]; then
  echo "restore: $src/db.sql.gz could not be read to the end, so the database was not replaced." >&2
  exit 1
fi

swapping=1
for v in media secrets tree; do
  echo "restore: $v volume"
  # The volume root is a mount point, so the unpacked copy is moved up into it
  # (a rename on the same volume) once the old entries are removed. The root
  # directory takes the owner and mode the archive recorded for it, as a plain
  # extraction into it would have.
  docker run --rm -v "${project}_${v}:/dst" alpine:3.20 sh -c '
    set -e
    new=/dst/.restore-new
    find /dst -mindepth 1 -maxdepth 1 ! -name .restore-new -exec rm -rf {} +
    find "$new" -mindepth 1 -maxdepth 1 -exec mv {} /dst/ \;
    chown "$(stat -c %u:%g "$new")" /dst
    chmod "$(stat -c %a "$new")" /dst
    rmdir "$new"'
done
swapping=0

echo "restore: starting the stack"
compose up -d
echo "restore: done. Check docker compose ps and /api/health/."
