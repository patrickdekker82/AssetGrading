#!/usr/bin/env bash
# Install or update Graadmeter on the Synology from the images GitHub built (.github/workflows/images.yml).
# Fetches the server, web and bundle images, puts the compose file, configuration and scripts next to them and
# restarts the app. Run as root in the Graadmeter folder:   scripts/nas-update.sh   (or with a commit as tag).
#
# What you change on the NAS is kept:
# - config/model: kept when its model version is newer than the one in the update (a calibration you applied
#   with scripts/apply-proposal.sh); the update's copy is put next to it as config/model.nieuw.
# - config/etfs.csv, config/bond_etfs.csv, config/etcs.csv (the files you maintain): kept; a different copy in the
#   update is put next to it as <file>.nieuw.
set -euo pipefail
# Everything runs inside main(), which bash reads completely before it starts: the script replaces itself in
# scripts/ halfway through, and bash would otherwise go on reading the new file at the old position.
main() {
  cd "$(dirname "$0")/.." 2>/dev/null || true
  REGISTRY="${GRAADMETER_REGISTRY:-ghcr.io/patrickdekker82}"
  TAG="${1:-latest}"
  KEEP_FILES="config/etfs.csv config/bond_etfs.csv config/etcs.csv"

  echo "Images ophalen ($REGISTRY, $TAG)..."
  for name in server web bundle; do
    docker pull -q "$REGISTRY/graadmeter-$name:$TAG"
  done
  docker tag "$REGISTRY/graadmeter-server:$TAG" graadmeter-server:latest
  docker tag "$REGISTRY/graadmeter-web:$TAG" graadmeter-web:latest

  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  cid=$(docker create "$REGISTRY/graadmeter-bundle:$TAG" true)
  docker cp "$cid:/bundle/." "$tmp/"
  docker rm "$cid" >/dev/null

  version_of() {  # the model version in a model.yaml, or empty
    if [ -f "$1" ]; then sed -n 's/^version: *"\{0,1\}\([0-9.]*\)"\{0,1\}.*/\1/p' "$1" | head -1; fi
  }
  newer() {  # is version $1 newer than $2? (major.minor.patch)
    awk -v a="$1" -v b="$2" 'BEGIN { split(a, x, "."); split(b, y, ".");
      for (i = 1; i <= 3; i++) { if (x[i] + 0 > y[i] + 0) exit 0; if (x[i] + 0 < y[i] + 0) exit 1 } exit 1 }'
  }

  mkdir -p config scripts backups data/postgres   # Synology does not create missing bind-mount folders
  here=$(version_of config/model/model.yaml)
  incoming=$(version_of "$tmp/config/model/model.yaml")
  if [ -n "$here" ] && newer "$here" "$incoming"; then
    echo "LET OP: config/model op de NAS ($here) is nieuwer dan de update ($incoming) en blijft staan."
    echo "        De versie uit de update staat in config/model.nieuw. Vraag Claude je model in GitHub te zetten."
    rm -rf config/model.nieuw && mv "$tmp/config/model" config/model.nieuw
  else
    rm -rf config/model && mv "$tmp/config/model" config/model
    rm -rf config/model.nieuw
  fi
  for f in $KEEP_FILES; do
    if [ -f "$f" ] && [ -f "$tmp/$f" ]; then
      if cmp -s "$f" "$tmp/$f"; then rm -f "$f.nieuw"; else
        mv "$tmp/$f" "$f.nieuw"; echo "Bewaard: $f (de versie uit de update staat in $f.nieuw)"
      fi
    fi
  done
  cp -R "$tmp/config/." config/
  cp -R "$tmp/scripts/." scripts/
  chmod +x scripts/*.sh
  cp "$tmp/docker-compose.yml" docker-compose.yml
  cp "$tmp/.env.example" .env.example

  if [ ! -f .env ]; then
    echo "Bestanden staan klaar, maar .env ontbreekt nog: zet die eerst in deze map en draai dit script opnieuw."
    exit 0
  fi
  echo "App (her)starten..."
  docker compose up -d
  docker image prune -f >/dev/null
  echo "Klaar. Versie: $(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' \
    "$REGISTRY/graadmeter-server:$TAG" 2>/dev/null | cut -c1-7), model $(version_of config/model/model.yaml)."
}

main "$@"
exit
