#!/bin/bash
set -euo pipefail

CLUSTER_NAME="rtc"
NAMESPACE="rtc"
MEDIA_NODE_LABEL_KEY="rtc-role"
MEDIA_NODE_LABEL_VALUE="media"
PLATFORM_NODE_LABEL_VALUE="platform"
MIN_MEDIA_NODE_COUNT="${MIN_MEDIA_NODE_COUNT:-2}"
MEDIA_NODE_COUNT="${MEDIA_NODE_COUNT:-${MIN_MEDIA_NODE_COUNT}}"
RTC_DEPLOY_MODE="${RTC_DEPLOY_MODE:-dev}"
RELAY_PUBLIC_PORT_BASE="${RELAY_PUBLIC_PORT_BASE:-31080}"

configure_dev_loadbalancer() {
  local lb_container="k3d-${CLUSTER_NAME}-serverlb"
  local tmp_config
  tmp_config="$(mktemp)"

  {
    cat <<EOF
error_log stderr notice;

worker_processes auto;
events {
  multi_accept on;
  use epoll;
  worker_connections 1024;
}

stream {

  upstream 30080_tcp {
EOF

    while IFS= read -r NODE_NAME; do
      [[ -z "${NODE_NAME}" ]] && continue
      printf '    server %s:30080 max_fails=1 fail_timeout=10s;\n' "${NODE_NAME}"
    done <<< "${NODE_NAMES}"

    cat <<EOF
  }

  server {
    listen        30080;
    proxy_pass    30080_tcp;
    proxy_timeout 600;
    proxy_connect_timeout 2s;
  }

EOF

    for (( node_index=0; node_index<MEDIA_NODE_COUNT; node_index++ )); do
      local relay_port
      relay_port=$((RELAY_PUBLIC_PORT_BASE + node_index))
      cat <<EOF
  upstream ${relay_port}_tcp {
    server k3d-${CLUSTER_NAME}-agent-${node_index}:31080 max_fails=1 fail_timeout=10s;
  }

  server {
    listen        ${relay_port};
    proxy_pass    ${relay_port}_tcp;
    proxy_timeout 600;
    proxy_connect_timeout 2s;
  }

EOF
    done

    cat <<EOF
  upstream 6443_tcp {
    server k3d-${CLUSTER_NAME}-server-0:6443 max_fails=1 fail_timeout=10s;
  }

  server {
    listen        6443;
    proxy_pass    6443_tcp;
    proxy_timeout 600;
    proxy_connect_timeout 2s;
  }

}
EOF
  } > "${tmp_config}"

  docker cp "${tmp_config}" "${lb_container}:/etc/nginx/nginx.conf"
  docker exec "${lb_container}" nginx -s reload >/dev/null
  rm -f "${tmp_config}"
}

if (( MEDIA_NODE_COUNT < MIN_MEDIA_NODE_COUNT )); then
  echo "MEDIA_NODE_COUNT must be at least ${MIN_MEDIA_NODE_COUNT}." >&2
  exit 1
fi

if [[ "${RTC_DEPLOY_MODE}" != "dev" && "${RTC_DEPLOY_MODE}" != "cloud" ]]; then
  echo "RTC_DEPLOY_MODE must be either dev or cloud." >&2
  exit 1
fi

echo "Deleting existing cluster (if present)..."
k3d cluster delete "${CLUSTER_NAME}" || true

echo "Creating new cluster..."
PORT_ARGS=(-p "8080:30080@loadbalancer")

if [[ "${RTC_DEPLOY_MODE}" == "dev" ]]; then
  for (( node_index=0; node_index<MEDIA_NODE_COUNT; node_index++ )); do
    host_port=$((RELAY_PUBLIC_PORT_BASE + node_index))
    PORT_ARGS+=(-p "${host_port}:${host_port}@loadbalancer")
  done
fi

k3d cluster create "${CLUSTER_NAME}" --agents "${MEDIA_NODE_COUNT}" "${PORT_ARGS[@]}"

echo "Setting kubectl context..."
kubectl config use-context "k3d-${CLUSTER_NAME}"

echo "Waiting for Kubernetes API..."
until kubectl get nodes >/dev/null 2>&1; do
  sleep 1
done

echo "Waiting for all nodes to become Ready..."
kubectl wait --for=condition=Ready nodes --all --timeout=120s

echo "Labeling node roles..."
NODE_NAMES=$(kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')
LABELED_MEDIA_NODE_COUNT=0

while IFS= read -r NODE_NAME; do
  if [[ -z "${NODE_NAME}" ]]; then
    continue
  fi

  if [[ "${NODE_NAME}" == *"-agent-"* ]]; then
    kubectl label node "${NODE_NAME}" "${MEDIA_NODE_LABEL_KEY}=${MEDIA_NODE_LABEL_VALUE}" --overwrite >/dev/null
    LABELED_MEDIA_NODE_COUNT=$((LABELED_MEDIA_NODE_COUNT + 1))
  else
    kubectl label node "${NODE_NAME}" "${MEDIA_NODE_LABEL_KEY}=${PLATFORM_NODE_LABEL_VALUE}" --overwrite >/dev/null
  fi
done <<< "${NODE_NAMES}"

if (( LABELED_MEDIA_NODE_COUNT < MIN_MEDIA_NODE_COUNT )); then
  echo "Only ${LABELED_MEDIA_NODE_COUNT} media nodes were labeled. Expected at least ${MIN_MEDIA_NODE_COUNT}." >&2
  exit 1
fi

if [[ "${RTC_DEPLOY_MODE}" == "dev" ]]; then
  echo "Configuring dev load balancer..."
  configure_dev_loadbalancer
fi

echo "Creating namespace..."
kubectl create namespace "${NAMESPACE}" >/dev/null 2>&1 || true

echo "Cluster is ready"
kubectl get nodes
