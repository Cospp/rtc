# Kubernetes Guide

## Zweck

Dieses Dokument beschreibt den aktuellen Kubernetes- und k3d-Betrieb des Repositories.

Es behandelt:

- den lokalen Clusteraufbau
- die Rollen von Platform- und Media-Nodes
- Deployment und Redeploy der Services
- aktuelle Port- und Exposure-Regeln

## Aktuelles Deployment-Modell

Der lokale Cluster trennt bewusst zwischen:

- einem Platform-Node
- mehreren Media-Nodes

### Node-Rollen

`scripts/reset.sh` erzeugt einen k3d-Cluster und labelt:

- den Server-Node mit `rtc-role=platform`
- alle Agent-Nodes mit `rtc-role=media`

### Komponenten im Cluster

| Komponente | Deployment-Modell | Aufgabe |
| --- | --- | --- |
| `redis` | Deployment | zentraler Zustandsstore |
| `session-control` | Deployment | Control Plane und REST-Einstieg |
| `relay` | DaemonSet auf Media-Nodes | sessiongebundene Medienkante |
| `worker` | Deployment | interne Session-Verarbeitung |

Wichtig:

- Relay läuft nur auf Nodes mit `rtc-role=media`
- Worker haben aktuell keinen Node-Selector und können im Cluster normal geschedult werden

## Betriebsmodi

Der Workflow kennt zwei Modi:

- `RTC_DEPLOY_MODE=dev`
- `RTC_DEPLOY_MODE=cloud`

### `dev`

Im Dev-Modus:

- veröffentlicht jeder Relay lokal erreichbare Host-Ports
- `reset.sh` konfiguriert den k3d-Load-Balancer mit einem Port pro Media-Node
- `deploy.sh` setzt die Relay-Environment-Variablen für lokale Endpunkt-Ankündigung

Das Ziel ist:

- die Media-Node-Idee lokal testbar zu machen
- ohne echtes Cloud-Networking nachzubauen

### `cloud`

Im Cloud-Modus:

- wird die lokale `localhost`-Ankündigung nicht gesetzt
- der Cluster verhält sich näher an einem echten Node-basierten Exposure-Modell

## Vollständiger lokaler Aufbau

Der empfohlene Einstieg ist:

```bash
./scripts/dev.sh
```

`dev.sh` macht in dieser Reihenfolge:

1. Cleanup des lokalen Zustands
2. Build von `session-control`, `worker` und `relay`
3. Neuerstellung des k3d-Clusters
4. Labeling der Nodes
5. Import der Images in k3d
6. Anwendung der Kubernetes-Manifeste
7. Warten auf Deployments und DaemonSet

### Wichtige Parameter

```bash
MEDIA_NODE_COUNT=4 RTC_DEPLOY_MODE=dev ./scripts/dev.sh
RTC_DEPLOY_MODE=cloud ./scripts/dev.sh
```

Regeln:

- `MEDIA_NODE_COUNT` muss mindestens `2` sein
- `RTC_DEPLOY_MODE` muss `dev` oder `cloud` sein

## Was `reset.sh` konkret macht

`scripts/reset.sh`:

- löscht den bestehenden k3d-Cluster
- erstellt einen neuen Cluster mit genau `MEDIA_NODE_COUNT` Agent-Nodes
- mapped `localhost:8080` auf den `session-control`-NodePort
- mapped im Dev-Modus zusätzliche Host-Ports auf die einzelnen Relay-Ports
- labelt die Nodes als `platform` oder `media`
- konfiguriert den k3d-Load-Balancer für den lokalen Relay-Zugriff

## Was `deploy.sh` konkret macht

`scripts/deploy.sh`:

- wendet alle Manifeste in `k8s/` an
- entfernt alte Legacy-Relay-Ressourcen
- konfiguriert Relay-Environment-Variablen abhängig vom Deploy-Modus
- wartet auf `redis`, `session-control`, `relay` und `worker`

## Redeploy einzelner Komponenten

Für schnelle Iteration:

```bash
./scripts/redeploy.sh session-control
./scripts/redeploy.sh relay
./scripts/redeploy.sh worker
./scripts/redeploy.sh all
```

`redeploy.sh`:

- baut nur die gewählte Komponente neu
- importiert ihr Image in den k3d-Cluster
- stößt den Rollout für genau diese Komponente an

## Aktuelle Port- und Exposure-Regeln

### `session-control`

- Service-Typ: `NodePort`
- Cluster-Port: `8000`
- NodePort: `30080`
- lokal erreichbar über: `http://localhost:8080`

### `relay`

Im Cluster:

- Relay lauscht intern auf `8080`
- Relay läuft als DaemonSet auf Media-Nodes
- jeder Relay nutzt auf seinem Node `hostPort: 31080`

Im Dev-Modus:

- der Load-Balancer mappt `localhost:31080`, `localhost:31081`, ... auf die einzelnen Media-Nodes
- `deploy.sh` setzt dazu `RELAY_PUBLIC_HOST_DEV=localhost`
- zusätzlich wird `RELAY_PUBLIC_PORT_BASE` verwendet

Das Ergebnis ist:

- jeder Media-Node-Relay besitzt lokal einen eigenen Host-Port
- `session-control` kann einen konkreten öffentlichen Relay-Endpunkt zurückgeben

## Verifikation nach dem Deploy

### Cluster und Node-Rollen

```bash
kubectl get nodes --show-labels
```

Erwartung:

- ein Platform-Node
- mindestens zwei Media-Nodes

### Pods

```bash
kubectl get pods -n rtc -o wide
```

Erwartung:

- `redis` läuft
- `session-control` läuft
- `worker`-Pods laufen
- pro Media-Node ein Relay-Pod läuft

### Rollout-Status

```bash
kubectl rollout status deployment/session-control -n rtc
kubectl rollout status deployment/worker -n rtc
kubectl rollout status daemonset/relay -n rtc
```

### Erreichbarkeit

```bash
curl http://localhost:8080/health
curl http://localhost:8080/docs
curl http://localhost:31080/healthz
```

## Nützliche Betriebsbefehle

Logs:

```bash
kubectl logs -n rtc deployment/session-control
kubectl logs -n rtc deployment/worker
kubectl logs -n rtc daemonset/relay
```

Redis:

```bash
kubectl exec -n rtc -it deployment/redis -- redis-cli
```

Pod-Details:

```bash
kubectl describe pod -n rtc <pod-name>
```

## Typische Fehlerbilder

### Zu wenige Media-Nodes

Symptom:

- `dev.sh` oder `deploy.sh` bricht früh ab

Ursache:

- `MEDIA_NODE_COUNT` liegt unter dem Mindestwert
- oder Media-Nodes wurden nicht korrekt gelabelt

### Relay nicht erreichbar

Symptom:

- `localhost:31080` oder weitere Relay-Ports antworten nicht

Prüfen:

- läuft das Relay-DaemonSet?
- ist der Cluster im `dev`-Modus aufgebaut?
- wurde der Load-Balancer durch `reset.sh` korrekt konfiguriert?

### Session-Control erreichbar, Relay aber nicht

Symptom:

- `http://localhost:8080/docs` geht
- Relay-Healthz geht nicht

Prüfen:

- `kubectl get pods -n rtc -o wide`
- `kubectl rollout status daemonset/relay -n rtc`
- `kubectl logs -n rtc daemonset/relay`

## Verhältnis zu Docker Compose

Docker Compose bleibt für einen schnellen lokalen Software-Start nützlich, bildet aber das Media-Node-Modell nur eingeschränkt ab.

Für das echte Relay-/Media-Node-Denken ist der k3d-/Kubernetes-Weg die maßgebliche Referenz.

## Verwandte Dokumente

- [architecture.md](architecture.md)
- [runtime-lifecycle.md](runtime-lifecycle.md)
- [../README.md](../README.md)
