#!/bin/bash
set -euo pipefail

CLUSTER_NAME="rtc"

echo "Importing images into k3d cluster..."
k3d image import rtc-session-control:dev -c "${CLUSTER_NAME}"
k3d image import rtc-worker:dev -c "${CLUSTER_NAME}"

echo "Images imported"