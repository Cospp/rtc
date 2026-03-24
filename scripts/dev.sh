#!/bin/bash
set -euo pipefail

# wichtig: immer ins Projekt-Root wechseln
cd "$(dirname "$0")/.."

echo "=============================="
echo " RTC DEV ENV START"
echo "=============================="

echo "Running hard cleanup..."
./scripts/clean.sh

echo "Building images..."
docker build -t rtc-session-control:dev -f session_control/Dockerfile .
docker build -t rtc-worker:dev -f worker/Dockerfile .

echo "☸ Resetting cluster..."
./scripts/reset.sh

echo "Loading images into cluster..."
./scripts/load-images.sh

echo "Deploying manifests..."
./scripts/deploy.sh

echo
echo "RTC DEV ENV READY"
echo "Swagger: http://localhost:8080/docs"