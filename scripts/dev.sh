#!/bin/bash
set -euo pipefail

# wichtig: immer ins Projekt-Root wechseln
cd "$(dirname "$0")/.."


# MIN_MEDIA_NODE_COUNT existiert noch nicht als env var deshalb 2 als default
MIN_MEDIA_NODE_COUNT="${MIN_MEDIA_NODE_COUNT:-2}"
MEDIA_NODE_COUNT="${MEDIA_NODE_COUNT:-${MIN_MEDIA_NODE_COUNT}}"
RTC_DEPLOY_MODE="${RTC_DEPLOY_MODE:-dev}"

if (( MEDIA_NODE_COUNT < MIN_MEDIA_NODE_COUNT )); then
  echo "MEDIA_NODE_COUNT must be at least ${MIN_MEDIA_NODE_COUNT}."
  exit 1
fi

echo "=============================="
echo " RTC DEV ENV START"
echo "=============================="
echo "Media nodes: ${MEDIA_NODE_COUNT} (minimum ${MIN_MEDIA_NODE_COUNT})"
echo "Deploy mode: ${RTC_DEPLOY_MODE}"

echo "Running hard cleanup..."
./scripts/clean.sh

echo "Building images..."
docker build -t rtc-session-control:dev -f session_control/Dockerfile .
docker build -t rtc-worker:dev -f worker/Dockerfile .
docker build -t rtc-relay:dev -f relay/Dockerfile .

echo "☸ Resetting cluster..."
MEDIA_NODE_COUNT="${MEDIA_NODE_COUNT}" \
MIN_MEDIA_NODE_COUNT="${MIN_MEDIA_NODE_COUNT}" \
RTC_DEPLOY_MODE="${RTC_DEPLOY_MODE}" \
./scripts/reset.sh

echo "Loading images into cluster..."
./scripts/load-images.sh

echo "Deploying manifests..."
RTC_DEPLOY_MODE="${RTC_DEPLOY_MODE}" ./scripts/deploy.sh

echo
echo "RTC DEV ENV READY"
echo "Swagger: http://localhost:8080/docs"

