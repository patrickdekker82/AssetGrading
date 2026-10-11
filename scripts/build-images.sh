#!/usr/bin/env bash
# Build both images on the Mac for the Synology (linux/amd64) and save them as one file.
# Usage: scripts/build-images.sh            -> dist/graadmeter-images.tar.gz
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p dist
docker buildx build --platform linux/amd64 --load -t graadmeter-server:latest server
docker buildx build --platform linux/amd64 --load -t graadmeter-web:latest web
docker pull --platform linux/amd64 postgres:16-alpine
docker save graadmeter-server:latest graadmeter-web:latest postgres:16-alpine | gzip > dist/graadmeter-images.tar.gz
echo "Klaar: dist/graadmeter-images.tar.gz"
echo "Kopieer naar de NAS en laad met: docker load -i graadmeter-images.tar.gz"
