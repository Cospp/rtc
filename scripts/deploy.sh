#!/bin/bash
set -euo pipefail

NAMESPACE="rtc"
MIN_MEDIA_NODE_COUNT="${MIN_MEDIA_NODE_COUNT:-2}"
RTC_DEPLOY_MODE="${RTC_DEPLOY_MODE:-dev}"
RELAY_PUBLIC_HOST_DEV="${RELAY_PUBLIC_HOST_DEV:-localhost}"
RELAY_PUBLIC_PORT_BASE="${RELAY_PUBLIC_PORT_BASE:-31080}"

MEDIA_NODE_COUNT=$(kubectl get nodes -l rtc-role=media --no-headers 2>/dev/null | wc -l | tr -d ' ')
if (( MEDIA_NODE_COUNT < MIN_MEDIA_NODE_COUNT )); then
  echo "Need at least ${MIN_MEDIA_NODE_COUNT} media nodes before deployment. Found ${MEDIA_NODE_COUNT}." >&2
  exit 1
fi

if [[ "${RTC_DEPLOY_MODE}" != "dev" && "${RTC_DEPLOY_MODE}" != "cloud" ]]; then
  echo "RTC_DEPLOY_MODE must be either dev or cloud." >&2
  exit 1
fi

echo "Applying Kubernetes manifests..."
kubectl apply -f k8s/

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

echo "Waiting for redis deployment..."
kubectl rollout status deployment/redis -n "${NAMESPACE}" --timeout=120s

echo "Waiting for session-control deployment..."
kubectl rollout status deployment/session-control -n "${NAMESPACE}" --timeout=120s

echo "Waiting for relay daemonset..."
kubectl rollout status daemonset/relay -n "${NAMESPACE}" --timeout=120s

echo "Waiting for worker deployment..."
kubectl rollout status deployment/worker -n "${NAMESPACE}" --timeout=120s

echo "Current pod status:"
kubectl get pods -n "${NAMESPACE}" -o wide

echo "Deploy complete"
