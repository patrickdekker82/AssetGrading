#!/bin/sh
set -e
# Started as root: make the mounted back-up folder writable for the server user, then drop privileges.
if [ "$(id -u)" = "0" ]; then
    mkdir -p "${BACKUP_DIR:-/backups}"
    chown graadmeter "${BACKUP_DIR:-/backups}" 2>/dev/null || echo "Let op: kan ${BACKUP_DIR:-/backups} niet overnemen"
    exec setpriv --reuid=graadmeter --regid=graadmeter --init-groups "$0" "$@"
fi
# Bring the database schema up to date before the server starts.
alembic upgrade head
exec "$@"
