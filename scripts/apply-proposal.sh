#!/usr/bin/env bash
# Write an approved calibration proposal (page Model) into a new model version and restart the server.
# The config folder is read-only inside the running containers, so this starts a one-off container with the
# folder writable, as the owner of that folder (so the files stay yours).
#   scripts/apply-proposal.sh <proposal number>
set -euo pipefail
cd "$(dirname "$0")/.."
[ $# -eq 1 ] || { echo "Gebruik: scripts/apply-proposal.sh <nummer van het voorstel>"; exit 2; }
set -a; source .env; set +a
project="${COMPOSE_PROJECT_NAME:-graadmeter}"
docker run --rm --network "${project}_default" --env-file .env \
  -e DATABASE_URL="postgresql+psycopg://${POSTGRES_USER:-graadmeter}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB:-graadmeter}" \
  -e CONFIG_DIR=/config -v "$PWD/config:/config" --user "$(stat -c %u:%g config 2>/dev/null || stat -f %u:%g config)" \
  --entrypoint python graadmeter-server:latest -m app.cli apply-proposal "$1"
docker compose restart server
echo "Klaar. Nieuwe modelversie: $(grep -m1 '^version:' config/model/model.yaml)"
