#!/usr/bin/env bash
# Dump the database to ./backups (outside the containers). Scheduled nightly from phase 10;
# run by hand until then. Keeps the last 14 dumps.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
mkdir -p backups
file="backups/graadmeter-$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
docker compose exec -T db pg_dump -U "${POSTGRES_USER:-graadmeter}" -d "${POSTGRES_DB:-graadmeter}" | gzip > "$file"
ls -1t backups/graadmeter-*.sql.gz | tail -n +15 | xargs -r rm --
echo "Back-up: $file"
