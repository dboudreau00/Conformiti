#!/usr/bin/env sh
# Back up a Docker Compose installation of Conformiti: the database and the
# three volumes the database only points at. Run it from the checkout that
# `docker compose up` was run from, while the stack is up.
#
#   scripts/backup.sh [directory]        default: backups/<UTC timestamp>
#
# Writes db.sql.gz (pg_dump), media.tgz (uploaded evidence), secrets.tgz
# (the package signing key, the field-encryption ring and the Django secret
# key) and tree.tgz (the compliance folder tree on disk). The `static`
# volume is rebuilt at boot and is not taken. scripts/restore.sh takes the
# directory back, on this machine or another one.
set -eu
export MSYS_NO_PATHCONV=1   # Git Bash on Windows: leave /src and /out alone

out="${1:-backups/$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$out"
out="$(cd "$out" && pwd)"

db="$(docker compose ps -q db)"
if [ -z "$db" ]; then
  echo "backup: the db service is not running (docker compose up -d db)" >&2
  exit 1
fi
# The volumes are named after the compose project. Ask the running container
# for it rather than guessing from the directory name, which compose
# normalises in ways that are easy to get wrong.
project="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project" }}' "$db")"

# Everything written from here is the installation's secrets, its evidence and
# its database. A backup that any local account can read is not a backup of a
# system that encrypts anything (0.9.5h, L-3). This umask covers what this
# shell creates, which is the database dump: the redirect below happens here.
umask 077

echo "backup: database"
docker compose exec -T db sh -c 'exec pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$out/db.sql"
gzip -f "$out/db.sql"

for v in media secrets tree; do
  echo "backup: $v volume"
  # The mode is set INSIDE the container, by the process that creates the
  # file. The tar runs as root there, so on Linux the archive lands root:root
  # 644 and a chmod afterwards from the user who invoked this script fails:
  # 0.9.5h wrote that chmod, hid the failure with `|| true`, and printed a
  # reassurance it had not earned (0.9.5i, L-2).
  docker run --rm -v "${project}_${v}:/src:ro" -v "$out:/out" alpine:3.20 \
    sh -c "umask 077 && tar czf /out/$v.tgz -C /src . && chmod 600 /out/$v.tgz"
done

# The directory too, and not quietly: if this cannot be set, the archives are
# readable by anyone who can reach the path and the operator needs to know.
chmod 700 "$out"

echo "backup: written to $out (archives 600, directory 700)"
ls -l "$out"
