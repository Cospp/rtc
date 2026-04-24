#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/.."

NAMESPACE="rtc"
CLUSTER_NAME="rtc"
RTC_DEPLOY_MODE="${RTC_DEPLOY_MODE:-dev}"
RELAY_PUBLIC_HOST_DEV="${RELAY_PUBLIC_HOST_DEV:-localhost}"
RELAY_PUBLIC_PORT_BASE="${RELAY_PUBLIC_PORT_BASE:-31080}"

usage() {
  echo "Usage: bash scripts/redeploy.sh [session-control|relay|worker|all]"
}

TARGET="${1:-all}"

build_and_import() {
  local service="$1"

  case "${service}" in
    session-control)
      echo "Building session-control image..."
      docker build -t rtc-session-control:dev -f session_control/Dockerfile .
      echo "Importing session-control image into k3d..."
      k3d image import rtc-session-control:dev -c "${CLUSTER_NAME}"
      echo "Restarting session-control deployment..."
      kubectl rollout restart deployment/session-control -n "${NAMESPACE}"
      kubectl rollout status deployment/session-control -n "${NAMESPACE}" --timeout=120s
      ;;
    relay)
      echo "Building relay image..."
      docker build -t rtc-relay:dev -f relay/Dockerfile .
      echo "Importing relay image into k3d..."
      k3d image import rtc-relay:dev -c "${CLUSTER_NAME}"
      echo "Applying relay manifest..."
      kubectl apply -f k8s/relay.yaml
      echo "Cleaning up legacy relay resources..."
      kubectl delete deployment/relay -n "${NAMESPACE}" --ignore-not-found
      kubectl delete service/relay -n "${NAMESPACE}" --ignore-not-found
      if [[ "${RTC_DEPLOY_MODE}" == "dev" ]]; then
        echo "Configuring relay advertised endpoints for local development..."
        kubectl set env daemonset/relay -n "${NAMESPACE}" \
          RELAY_PUBLIC_HOST_DEV="${RELAY_PUBLIC_HOST_DEV}" \
          RELAY_PUBLIC_PORT_BASE="${RELAY_PUBLIC_PORT_BASE}" >/dev/null
      else
        echo "Configuring relay advertised endpoints for cloud-style node exposure..."
        kubectl set env daemonset/relay -n "${NAMESPACE}" RELAY_PUBLIC_HOST_DEV- >/dev/null
      fi
      echo "Restarting relay daemonset..."
      kubectl rollout restart daemonset/relay -n "${NAMESPACE}"
      kubectl rollout status daemonset/relay -n "${NAMESPACE}" --timeout=120s
      ;;
    worker)
      echo "Building worker image..."
      docker build -t rtc-worker:dev -f worker/Dockerfile .
      echo "Importing worker image into k3d..."
      k3d image import rtc-worker:dev -c "${CLUSTER_NAME}"
      echo "Restarting worker deployment..."
      kubectl rollout restart deployment/worker -n "${NAMESPACE}"
      kubectl rollout status deployment/worker -n "${NAMESPACE}" --timeout=120s
      ;;
    *)
      usage
      exit 1
      ;;
  esac
}

case "${TARGET}" in
  all)
    build_and_import session-control
    build_and_import relay
    build_and_import worker
    ;;
  session-control|relay|worker)
    build_and_import "${TARGET}"
    ;;
  *)
    usage
    exit 1
    ;;
esac

echo "Current pod status:"
kubectl get pods -n "${NAMESPACE}" -o wide

echo "Redeploy complete"
