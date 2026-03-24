#!/bin/bash
set -euo pipefail

CLUSTER_NAME="rtc"
NAMESPACE="rtc"

echo "Deleting existing cluster (if present)..."
k3d cluster delete "${CLUSTER_NAME}" || true

echo "Creating new cluster..."
k3d cluster create "${CLUSTER_NAME}" --agents 2 -p "8080:30080@loadbalancer"

echo "Setting kubectl context..."
kubectl config use-context "k3d-${CLUSTER_NAME}"

echo "Waiting for Kubernetes API..."
until kubectl get nodes >/dev/null 2>&1; do
  sleep 1
done

echo "Waiting for all nodes to become Ready..."
kubectl wait --for=condition=Ready nodes --all --timeout=120s

echo "Creating namespace..."
kubectl create namespace "${NAMESPACE}" >/dev/null 2>&1 || true

echo "Cluster is ready"
kubectl get nodes