#!/usr/bin/env bash
# Restore a back-up into the database of this installation, also on a new (clean) machine.
#   scripts/restore.sh backups/graadmeter-20261015T020000Z.dump
# Steps: check the file, start only the database, replace its contents with the dump, start the rest and
# recompute every grade from its stored input to prove the restore is complete.
set -euo pipefail
cd "$(dirname "$0")/.."
dump=${1:?gebruik: scripts/restore.sh backups/graadmeter-<datum>.dump}
compose="docker compose ${COMPOSE_FILES:-}"
set -a; source .env; set +a
user=${POSTGRES_USER:-graadmeter}; db=${POSTGRES_DB:-graadmeter}

if [ -f "$dump.sha256" ]; then
  (cd "$(dirname "$dump")" && sha256sum -c "$(basename "$dump").sha256") || { echo "Controlegetal klopt niet"; exit 1; }
fi
echo "Database starten..."
$compose up -d db
# The first start of an empty database runs a temporary server (socket only); wait for the real one on TCP.
until $compose exec -T db pg_isready -h 127.0.0.1 -U "$user" -d "$db" >/dev/null 2>&1; do sleep 2; done
$compose stop server web >/dev/null 2>&1 || true
echo "Inhoud vervangen door $dump ..."
$compose exec -T db psql -v ON_ERROR_STOP=1 -U "$user" -d postgres \
  -c "DROP DATABASE IF EXISTS \"$db\" WITH (FORCE);" -c "CREATE DATABASE \"$db\";"
$compose exec -T db pg_restore --no-owner --no-privileges --exit-on-error -U "$user" -d "$db" < "$dump"
echo "Server en interface starten..."
$compose up -d
until $compose exec -T server python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" \
  >/dev/null 2>&1; do sleep 3; done
echo "Alle grades opnieuw berekenen en vergelijken..."
$compose exec -T server python -m app.cli verify
