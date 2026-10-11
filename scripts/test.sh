#!/usr/bin/env bash
# Run every test in containers; no Python or Node needed on the Mac.
# Usage: scripts/test.sh
# Extra docker flags (e.g. behind a proxy) via DOCKER_BUILD_FLAGS and DOCKER_RUN_FLAGS.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
user=${POSTGRES_USER:-graadmeter}

echo "== Rekenserver =="
docker build ${DOCKER_BUILD_FLAGS:-} --target test -t graadmeter-server:test server
docker compose up -d --wait db
docker compose exec -T db psql -U "$user" -d postgres -c "DROP DATABASE IF EXISTS graadmeter_test" >/dev/null
docker compose exec -T db psql -U "$user" -d postgres -c "CREATE DATABASE graadmeter_test" >/dev/null
test_url="postgresql+psycopg://$user:$POSTGRES_PASSWORD@db:5432/graadmeter_test"
network="$(docker compose ps -q db | xargs docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}')"
docker run --rm --network "$network" -v "$PWD/config:/config:ro" \
  -e DATABASE_URL="$test_url" -e TEST_DATABASE_URL="$test_url" \
  graadmeter-server:test sh -c "alembic upgrade head && python -m pytest"

echo "== Webinterface =="
docker run --rm ${DOCKER_RUN_FLAGS:-} -v "$PWD:/repo" -w /repo/web node:22-alpine \
  sh -c "npm ci --no-audit --no-fund && npm run typecheck && npm test"
