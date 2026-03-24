# RTC Streaming Plattform

## Inhaltsverzeichnis

* [Überblick](#überblick)
* [Architektur](#architektur)
* [Rollen](#rollen)
* [Systemeigenschaften](#systemeigenschaften)
* [Aktueller Stand](#aktueller-stand)
* [Implementierte Funktionen](#implementierte-funktionen)
* [Zentrale Konzepte](#zentrale-konzepte)
* [Redis-Struktur](#redis-struktur)
* [Projektstruktur](#projektstruktur)
* [Quickstart (empfohlen)](#quickstart-empfohlen)
* [Quickstart (Docker Compose)](#quickstart-docker-compose)
* [API testen (Swagger UI)](#api-testen-swagger-ui)
* [Redis Debugging](#redis-debugging)
* [Lokaler Start (ohne Docker)](#lokaler-start-ohne-docker)
* [Kubernetes (k3d)](#kubernetes-k3d)
* [Wichtige Hinweise](#wichtige-hinweise)
* [Aktuelle Einschränkungen](#aktuelle-einschränkungen)
* [Nächste Schritte](#nächste-schritte)

---

## Überblick

Dieses Projekt implementiert eine experimentelle Plattform zur Annahme und Verarbeitung von Echtzeit-Streams.

Der Fokus liegt aktuell auf dem Aufbau einer zustandsbasierten Control Plane, die:

* Client-Sessions erstellt und verwaltet
* verfügbare Worker verwaltet
* Worker atomar reserviert
* inkonsistente Zustände selbständig bereinigt

Die eigentliche Medienverarbeitung (UDP / WebRTC) ist aktuell **nicht Bestandteil** des Systems.

---

## Architektur

Das System besteht aktuell aus drei zentralen Komponenten:

* `session_control`
* `worker`
* `redis`

Datenfluss:

```
Client -> session_control -> Redis <- worker
```

---

## Rollen

### session_control

Die Control Plane.

Verantwortung:

* Entgegennahme von Session-Anfragen
* Auswahl freier Worker
* atomare Worker-Reservation (Redis Lua)
* Speicherung von Session-Zuständen

---

### worker

Die Worker-Komponente.

Verantwortung:

* Registrierung in Redis
* periodischer Heartbeat
* Verwaltung des eigenen Zustands
* automatische Freigabe bei abgelaufenen Sessions

---

### redis

Koordinations- und Zustandslayer.

Verwendung:

* Session-State (`session:<id>`)
* Worker-State (`worker:<id>`)
* Worker-Discovery (`workers:warm`)
* TTL-basierte Liveness

---

## Systemeigenschaften

* Stateless Control Plane (`session_control`)
* Ephemere Worker mit Self-Healing
* Redis als zentraler Zustandsspeicher
* deterministische Zustandsübergänge
* TTL-basierte Konsistenz

---

## Aktueller Stand

Das System ist funktional lauffähig und implementiert den vollständigen Worker-Lifecycle:

```
warm -> reserved -> warm
```

---

## Implementierte Funktionen

* FastAPI-basierter `session_control`
* Redis-Anbindung (async)
* Startup-Validierung (fail-fast bei Redis-Ausfall)
* Health Endpoint (`/health`)
* Metrics Endpoint (`/metrics`)
* Session-Erstellung (`POST /sessions`)
* TTL-basierte Session-Verwaltung
* Worker-Registrierung und Heartbeat
* Worker-Discovery über Redis Set (`workers:warm`)
* atomare Worker-Reservation via Lua Script
* Worker Self-Healing bei Session-Verlust

---

## Zentrale Konzepte

### Worker Lifecycle

```
warm -> reserved -> warm
```

---

### Atomare Worker-Reservation

Die Zuweisung erfolgt über ein Redis Lua Script:

1. Worker wird aus `workers:warm` entfernt (`SPOP`)
2. Worker-State wird geprüft (`status == warm`)
3. Worker wird auf `reserved` gesetzt
4. `assigned_session_id` wird gesetzt

---

### Session-Modell

```
session:<id> -> {
  status: assigned,
  worker_id: <worker_id>
}
```

---

### Worker Self-Healing

Worker prüfen im Heartbeat:

```
wenn status == reserved und session nicht existiert:
    -> status = warm
```

---

### TTL Ownership

* Worker besitzt die TTL
* `session_control` verändert State ohne TTL
* Lua Script nutzt `KEEPTTL`

---

## Redis-Struktur

```
session:<session_id>
worker:<worker_id>
workers:warm
```

---

## Projektstruktur

```
rtc/
  session_control/
  worker/
  shared/
  scripts/
  k8s/
  docs/
```

---

## Quickstart (empfohlen)

### Kubernetes (ein Command)

```bash
./scripts/dev.sh
```

Dieser Workflow:

* bereinigt alte Zustände
* baut Images
* erstellt Cluster
* deployt System

---

## Quickstart (Docker Compose)

```bash
docker compose up --build
```

Stop:

```bash
docker compose down
```

---

## API testen (Swagger UI)

Docker Compose:

```
http://localhost:8000/docs
```

Kubernetes:

```
http://localhost:8080/docs
```

---

## Redis Debugging

```bash
docker compose exec redis redis-cli
```

```bash
kubectl exec -n rtc -it deployment/redis -- redis-cli
```
---

## Lokaler Start (ohne Docker)

Redis:

```bash
docker run -p 6379:6379 redis:7
```

---

## Kubernetes (k3d)

### Voraussetzungen

* Docker
* kubectl
* k3d
* Git Bash

---

### Schnellstart

```bash
./scripts/dev.sh
```

---

### Zugriff

```
http://localhost:8080/docs
```

---

### Komponenten

* redis
* session-control
* worker

---

### Manifeste

```
k8s/
```

---

### Dokumentation

```
docs/kubernetes.md
```

---

## Wichtige Hinweise

### Netzwerk

| Kontext    | Host      |
| ---------- | --------- |
| Lokal      | localhost |
| Docker     | redis     |
| Kubernetes | redis     |

---

## Aktuelle Einschränkungen

1. Keine Medienverarbeitung
2. Redis Single Instance
3. Kein Autoscaling
4. Keine Service Discovery

---

## Nächste Schritte

* Autoscaling
* Relay Layer
* UDP Streaming
* WebRTC Integration

---
