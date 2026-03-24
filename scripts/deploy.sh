#!/bin/bash
set -euo pipefail

NAMESPACE="rtc"

echo "Applying Kubernetes manifests..."
kubectl apply -f k8s/

echo "Waiting for redis deployment..."
kubectl rollout status deployment/redis -n "${NAMESPACE}" --timeout=120s

echo "Waiting for session-control deployment..."
kubectl rollout status deployment/session-control -n "${NAMESPACE}" --timeout=120s

echo "Waiting for worker deployment..."
kubectl rollout status deployment/worker -n "${NAMESPACE}" --timeout=120s

echo "Current pod status:"
kubectl get pods -n "${NAMESPACE}" -o wide

echo "Deploy complete"