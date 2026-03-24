#!/bin/bash
set -euo pipefail

CLUSTER_NAME="rtc"

echo "HARD RESET START"

echo "Deleting k3d cluster..."
k3d cluster delete "${CLUSTER_NAME}" || true

echo "Removing RTC containers..."
docker ps -a --format "{{.Names}}" | grep "^rtc-" | xargs -r docker rm -f || true

echo "Removing leftover k3d containers..."
docker ps -a --format "{{.Names}}" | grep "^k3d-${CLUSTER_NAME}" | xargs -r docker rm -f || true

echo "Removing RTC images..."
docker images --format "{{.Repository}}:{{.Tag}}" | grep "^rtc-" | xargs -r docker rmi -f || true

echo "Removing k3d image volumes..."
docker volume ls --format "{{.Name}}" | grep "^k3d-${CLUSTER_NAME}" | xargs -r docker volume rm || true

echo "HARD RESET COMPLETE"