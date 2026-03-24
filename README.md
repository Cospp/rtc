# RTC Streaming Plattform

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

* `warm`: Worker ist verfügbar
* `reserved`: Worker ist einer Session zugewiesen
* Rückkehr zu `warm`: erfolgt automatisch durch Worker (Heartbeat + Session-TTL)

---

### Atomare Worker-Reservation

Die Zuweisung erfolgt über ein Redis Lua Script:

1. Worker wird aus `workers:warm` entfernt (`SPOP`)
2. Worker-State wird geprüft (`status == warm`)
3. Worker wird auf `reserved` gesetzt
4. `assigned_session_id` wird gesetzt

Die Operation ist atomar innerhalb von Redis.

---

### Session-Modell

```
session:<id> -> {
  status: assigned,
  worker_id: <worker_id>
}
```

Eigenschaften:

* Sessions besitzen eine TTL
* Ablauf löscht den Session-Key automatisch
* Worker erkennen fehlende Sessions und geben sich frei

---

### Worker Self-Healing

Worker prüfen im Heartbeat:

```
wenn status == reserved und session nicht existiert:
    -> status = warm
```

---

### TTL Ownership

* **Worker ist alleiniger Owner des Worker-TTL**
* `session_control` verändert Worker-State **ohne TTL zu setzen**
* Redis Lua Script verwendet `KEEPTTL`

→ verhindert konkurrierende TTL-Updates

---

## Redis-Struktur

### Session

```
session:<session_id>
```

### Worker

```
worker:<worker_id>
```

### Worker-Pool

```
workers:warm
```

Set mit aktuell verfügbaren Workern.

---

## Projektstruktur

```
rtc/
  session_control/
  worker/
  shared/
    models/
      worker.py
  docs/
  docker-compose.yml
```

---

## Quickstart (Docker Compose – empfohlen)

### Start

```
docker compose up --build
```

---

### Stop

```
docker compose down
```

---

### Clean Restart

```
docker compose down -v --remove-orphans
docker compose up --build
```

---

## Test


## API testen (Swagger UI)

Die einfachste Möglichkeit, das System zu testen, ist über die automatisch generierte API-Dokumentation:

    http://localhost:8000/docs

Dort können Requests direkt im Browser ausgeführt werden.

### Beispiel: Session erstellen

1. Endpoint `POST /sessions` auswählen
2. "Try it out" klicken
3. Request Body einfügen:

    {
      "client_id": "client-1",
      "stream_profile": "480p",
      "transport": "udp"
    }

4. "Execute" klicken

Erwartung:

- Die ersten Requests werden erfolgreich einem Worker zugewiesen
- Sobald alle Worker reserviert sind:
  → Response: `No warm workers available`

Swagger eignet sich besonders für:

- schnelles Debugging
- manuelles Testen
- Exploration der API

---

## Alternative: curl

Für automatisierte Tests oder Skripting kann weiterhin curl verwendet werden:

    curl -X POST http://localhost:8000/sessions \
      -H "Content-Type: application/json" \
      -d "{\"client_id\":\"client-1\",\"stream_profile\":\"480p\",\"transport\":\"udp\"}"

Erwartetes Verhalten:

* 3 Requests → erfolgreich (bei 3 Workern)
* weiterer Request → `No warm workers available`

---

## Redis Debugging

```
docker compose exec redis redis-cli
```

### Warm Pool

```
SMEMBERS workers:warm
```

### Worker

```
GET worker:worker-1
TTL worker:worker-1
```

### Session

```
GET session:<session_id>
```

---

## Lokaler Start (ohne Docker)

Redis starten:

```
docker run -p 6379:6379 redis:7
```

---

### session_control

```
set REDIS_URL=redis://localhost:6379/0
uvicorn session_control.app.main:app --host 0.0.0.0 --port 8000
```

---

### worker

```
set REDIS_URL=redis://localhost:6379/0
set WORKER_ID=worker-1
set WORKER_PORT=9000

uvicorn worker.app.main:app --host 0.0.0.0 --port 9000
```

---

## Wichtige Hinweise

### Netzwerkverhalten

| Kontext    | Redis Host |
| ---------- | ---------- |
| Lokal      | localhost  |
| Docker     | redis      |
| Kubernetes | redis      |

---

### Worker ID

* Muss eindeutig sein
* Wird aktuell per Environment Variable gesetzt
* Wird später durch Orchestrator (Kubernetes) injiziert

---

### Häufige Fehler

* `localhost` innerhalb von Containern verwenden
* falsches Docker-Netzwerk
* mehrere Redis-Instanzen
* fehlendes Port-Mapping

---

## Aktuelle Einschränkungen

1. Keine Medienverarbeitung (UDP / WebRTC fehlt)
2. Redis Single-Instance (keine Verteilung / HA)
3. Kein zentraler Reconciliation Loop
4. Keine echte Service Discovery
5. Minimaler Zustandsautomat (`warm`, `reserved`)

---

## Nächste Schritte

* Kubernetes Deployment (k3d / k3s)
* Worker-Autoscaling basierend auf verfügbarem Pool
* Service Discovery
* Ingest/Relay Layer
* UDP Streaming
* spätere WebRTC Integration

---

## Hinweise

Dieses Projekt wird iterativ entwickelt.

Der Fokus liegt aktuell auf:

* deterministischem Worker-Management
* klaren Zustandsübergängen
* stabiler Control Plane

---
