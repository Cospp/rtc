# Kubernetes Operator Playbook

## Überblick

Dieses Dokument beschreibt den Betrieb, das Debugging und die Ausführung des RTC-Systems auf Kubernetes mittels **k3d**.

Abgedeckt werden:

* Cluster-Setup
* Image-Management
* Deployments
* Debugging
* Typische Fehlerbilder

Dies ist **kein** konzeptioneller Einstieg, sondern ein **Operator-Runbook**.

---

## Voraussetzungen

Benötigt werden:

* Docker Desktop (laufend)
* kubectl installiert
* k3d installiert

Verifikation:

```
docker --version
kubectl version --client
k3d version
```

---

## Cluster Setup

### Cluster erstellen

```
k3d cluster create rtc --agents 2 -p "8080:30080@loadbalancer"
```

### Erklärung

* Erstellt einen Cluster mit Namen `rtc`
* 1 Control-Plane Node
* 2 Worker Nodes
* Port-Mapping:

```
localhost:8080 → NodePort 30080
```

---

### Cluster verifizieren

```
kubectl get nodes
```

Erwartet:

```
k3d-rtc-server-0   Ready
k3d-rtc-agent-0    Ready
k3d-rtc-agent-1    Ready
```

---

## Namespace Setup

```
kubectl create namespace rtc
```

Verifikation:

```
kubectl get namespaces
```

---

## Image Management

### Problem

Kubernetes kann lokale Docker-Images nicht automatisch verwenden.

### Lösung

Images in den k3d-Cluster importieren:

```
k3d image import rtc-session-control:dev -c rtc
k3d image import rtc-worker:dev -c rtc
```

---

### Wann neu importieren?

Bei jeder Änderung an:

* Code
* Dockerfile
* Build-Flags

---

## Deployments

### Alle Manifeste anwenden

```
kubectl apply -f k8s/
```

---

### Einzelne Komponenten deployen

```
kubectl apply -f k8s/redis.yaml
kubectl apply -f k8s/session-control.yaml
kubectl apply -f k8s/worker.yaml
```

---

## Systemkomponenten

### Redis

* Zentrale State-Komponente
* Erreichbar innerhalb des Clusters unter:

```
redis:6379
```

---

### Session-Control

* HTTP API
* Über NodePort exponiert

Zugriff:

```
http://localhost:8080/docs
```

---

### Worker

* Zustandslose Pods
* Skalierung über `replicas`
* Worker-ID entspricht dem Pod-Namen

---

## Verifikation

### Pods prüfen

```
kubectl get pods -n rtc
```

---

### Services prüfen

```
kubectl get svc -n rtc
```

---

### Erwarteter Zustand

* redis → Running
* session-control → Running
* worker → mehrere Pods Running

---

## Logs

### Deployment-Logs

```
kubectl logs -n rtc deployment/worker
```

Hinweis: Zeigt standardmäßig nur **einen** Pod.

---

### Logs eines spezifischen Pods

```
kubectl logs -n rtc <pod-name>
```

---

## Debugging

### In einen Container wechseln

```
kubectl exec -n rtc -it deployment/redis -- redis-cli
```

Beispiel:

```
SMEMBERS workers:warm
```

---

### Pod-Details anzeigen

```
kubectl describe pod -n rtc <pod-name>
```

---

### Logs bei Fehlern

```
kubectl logs -n rtc <pod-name>
```

---

## Rollout / Updates

### Image neu bauen

```
docker build -t rtc-worker:dev -f worker/Dockerfile .
```

---

### Image neu importieren

```
k3d image import rtc-worker:dev -c rtc
```

---

### Deployment neu starten

```
kubectl rollout restart deployment/worker -n rtc
```

---

## Zugriff von außen

* NodePort: `30080`
* Host-Port: `8080`

Zugriff:

```
http://localhost:8080
```

---

## Typische Fehler

### ImagePullBackOff

Ursache:

* Image nicht importiert

Lösung:

```
k3d image import <image> -c rtc
```

---

### Falscher Namespace

Symptom:

```
kubectl get pods
```

zeigt nichts

Lösung:

```
kubectl get pods -n rtc
```

---

### Service nicht erreichbar

Prüfen:

```
kubectl get svc -n rtc
```

---

### Redis nicht erreichbar

Stellen sicher, dass verwendet wird:

```
redis://redis:6379/0
```

---

## Cluster Cleanup

### Cluster löschen

```
k3d cluster delete rtc
```

---

## Mentales Modell

Vergleich:

```
docker compose → Container + Ports

kubernetes →
  Pod (Container)
  Deployment (Skalierung)
  Service (Netzwerk)
```

---

## Kurzreferenz (Cheat Sheet)

```
# Cluster
k3d cluster create rtc --agents 2 -p "8080:30080@loadbalancer"

# Namespace
kubectl create namespace rtc

# Images
k3d image import rtc-session-control:dev -c rtc
k3d image import rtc-worker:dev -c rtc

# Deploy
kubectl apply -f k8s/

# Status
kubectl get pods -n rtc
kubectl get svc -n rtc

# Logs
kubectl logs -n rtc deployment/worker

# Redis Debug
kubectl exec -n rtc -it deployment/redis -- redis-cli

# Restart
kubectl rollout restart deployment/worker -n rtc

# Cleanup
k3d cluster delete rtc
```

---

## Fazit

Dieses Runbook deckt den vollständigen lokalen Kubernetes-Betrieb für das RTC-System ab.

Ziel ist ein reproduzierbarer, klar strukturierter Workflow für Entwicklung, Debugging und Validierung.
