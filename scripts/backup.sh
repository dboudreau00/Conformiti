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
#
# It is for the Docker stack only. An installation run without Docker (the
# bare-metal recipe in INSTALL.md) has no db container and no volumes to take:
# see "Backups on bare metal" in INSTALL.md for what to copy there.
set -eu
export MSYS_NO_PATHCONV=1   # Git Bash on Windows: leave /src and /out alone

not_docker() {
  echo "backup: this script backs up the Docker Compose stack. Run it from the checkout" >&2
  echo "backup: that ran docker compose up, with the stack up (docker compose up -d db)." >&2
  echo "backup: For an installation run without Docker, see \"Backups on bare metal\" in INSTALL.md." >&2
  exit 1
}

# Checked before anything is written, so a run that cannot back anything up
# leaves no empty backup directory behind.
if ! command -v docker >/dev/null 2>&1; then
  echo "backup: docker is not installed on this machine." >&2
  not_docker
fi
# docker's own error (no compose file here, daemon not running) stays on
# screen above the advice; `|| db=""` only stops `set -e` from ending the
# script before the advice is printed.
db="$(docker compose ps -q db)" || db=""
if [ -z "$db" ]; then
  echo "backup: no db container is running for the compose project in this directory." >&2
  not_docker
fi

out="${1:-backups/$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$out"
out="$(cd "$out" && pwd)"
# The volumes are named after the compose project. Ask the running container
# for it rather than guessing from the directory name, which compose
# normalises in ways that are easy to get wrong.
project="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project" }}' "$db")"

# Everything written from here is the installation's secrets, its evidence and
# its database. A backup that any local account can read is not a backup of a
# system that encrypts anything (0.9.5h, L-3). This umask covers what this
# shell creates, which is the database dump: the redirect below happens here.
umask 077

# The archives are written by a container running as root; these hand them
# back to whoever ran this script, so the backup is readable by its owner and
# by nobody else.
owner_uid="$(id -u)"
owner_gid="$(id -g)"

echo "backup: database"
docker compose exec -T db sh -c 'exec pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$out/db.sql"
gzip -f "$out/db.sql"

for v in media secrets tree; do
  echo "backup: $v volume"
  # Both the mode and the owner are set INSIDE the container, by the process
  # that creates the file. The tar has to run as root, because the volumes
  # belong to the unprivileged user the application runs as; that is what
  # made the archive root-owned and 644, and what made the chmod 0.9.5h added
  # afterwards fail silently behind `|| true` while the script printed
  # "mode 600" regardless (0.9.5i, L-2).
  #
  # The chown is the other half. Without it the archive is 600 root:root and
  # the operator who ran this cannot read their own backup without sudo,
  # which is a different way of being unusable.
  docker run --rm -v "${project}_${v}:/src:ro" -v "$out:/out" alpine:3.20 \
    sh -c "umask 077 && tar czf /out/$v.tgz -C /src . \
           && chown ${owner_uid}:${owner_gid} /out/$v.tgz \
           && chmod 600 /out/$v.tgz"
done

# The directory too, and not quietly: if this cannot be set, the archives are
# readable by anyone who can reach the path and the operator needs to know.
chmod 700 "$out"

echo "backup: written to $out (archives 600, owned by $(id -un), directory 700)"
ls -l "$out"
