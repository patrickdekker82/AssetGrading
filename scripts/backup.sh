#!/usr/bin/env bash
# Dump the database to ./backups by hand. The server also does this every night (job "backup", 02:00 UTC).
# Same format as the nightly dump: PostgreSQL custom format plus a .sha256 file.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
mkdir -p backups
name="graadmeter-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker compose exec -T db pg_dump -Fc --no-owner --no-privileges -U "${POSTGRES_USER:-graadmeter}" \
  -d "${POSTGRES_DB:-graadmeter}" > "backups/$name.part"
mv "backups/$name.part" "backups/$name"
(cd backups && sha256sum "$name" > "$name.sha256")
echo "Back-up: backups/$name"
