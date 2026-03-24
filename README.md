# RTC Streaming Plattform

## Überblick

Dieses Projekt implementiert eine experimentelle Plattform zur Annahme und Verarbeitung von Echtzeit-Streams.

Der Fokus liegt aktuell auf dem Aufbau einer zustandsbasierten Control Plane, die:

- Clients Sessions zuweist
- verfügbare Worker verwaltet
- Worker atomar reserviert
- inkonsistente Zustände selbständig bereinigt

Die eigentliche Medienverarbeitung (UDP / WebRTC) ist aktuell noch nicht Bestandteil des Systems.

---

## Architektur

Das System besteht aktuell aus drei zentralen Komponenten:

- `session_control`
- `worker`
- `redis`

Der grundlegende Datenfluss:

    Client -> session_control -> Redis <- worker

### Rollen

#### session_control

Verantwortung:
- Entgegennahme von Session-Anfragen
- Auswahl freier Worker
- atomare Worker-Reservation
- Speicherung von Session-Zuständen

#### worker

Verantwortung:
- Registrierung in Redis
- periodischer Heartbeat
- Verwaltung des eigenen Zustands
- automatische Freigabe bei abgelaufenen Sessions

#### redis

Koordinations- und Zustandslayer.

Verwendung:
- Session-State (`session:<id>`)
- Worker-State (`worker:<id>`)
- Worker-Discovery (`workers:warm`)
- TTL-basierte Liveness

---

## Aktueller Stand

Das System ist funktional lauffähig und implementiert den vollständigen Worker-Lifecycle:

    warm -> reserved -> warm

---

## Implementierte Funktionen

- `session_control` Service (FastAPI)
- Redis-Anbindung
- Startup-Validierung (Start nur bei erreichbarem Redis)
- Health Endpoint (`/health`)
- Metrics Endpoint (`/metrics`)
- Session-Erstellung (`POST /sessions`)
- Speicherung von Sessions in Redis (inkl. TTL)
- Worker-Registrierung
- Worker-Heartbeat
- Worker-Discovery über `workers:warm`
- atomare Worker-Reservation via Redis Lua
- automatische Freigabe reservierter Worker bei abgelaufenen Sessions

---

## Zentrale Konzepte

### Worker Lifecycle

    warm -> reserved -> warm

- `warm`: Worker ist verfügbar
- `reserved`: Worker ist einer Session zugewiesen
- Rückkehr zu `warm`: erfolgt automatisch bei Ablauf der Session

---

### Atomare Worker-Reservation

Die Zuweisung eines Workers erfolgt über ein Redis Lua Script.

Ablauf:

1. Worker wird aus `workers:warm` entfernt
2. Worker-State wird geprüft (`status == warm`)
3. Worker wird auf `reserved` gesetzt
4. `assigned_session_id` wird gesetzt

Die gesamte Operation erfolgt atomar innerhalb von Redis (Single-Instance-Annahme).

---

### Session-Modell

    session:<id> -> {
      status: assigned,
      worker_id: <worker_id>
    }

Eigenschaften:

- Sessions besitzen eine TTL
- Ablauf der TTL löscht den Session-Key automatisch
- Worker erkennen den Verlust und geben sich frei

---

### Worker Self-Healing

Worker prüfen im Heartbeat:

    wenn status == reserved und session nicht existiert -> setze status = warm

---

## Redis-Struktur

### Session

    session:<session_id>

### Worker

    worker:<worker_id>

### Worker-Pool

    workers:warm

Set mit verfügbaren Workern.

---

## API

### Session erstellen

    POST /sessions

Request:

    {
      "client_id": "client-1",
      "stream_profile": "480p",
      "transport": "udp"
    }

Response:

    {
      "session_id": "...",
      "client_id": "client-1",
      "status": "assigned",
      "worker_id": "worker-xyz",
      "ttl_seconds": 60
    }

---

### Health

    GET /health

---

### Metrics

    GET /metrics

Prometheus-kompatibel (aktuell Standardmetriken).

---

## Projektstruktur

    rtc/
      session_control/
      worker/
      deploy/
      docs/
      docker-compose.yml

---

## Voraussetzungen

- Docker
- Docker Compose

Prüfen:

    docker --version
    docker compose version

---

## Schnellstart mit Docker Compose (empfohlen)

Das System wird vollständig über Docker Compose gestartet.

### Start

Im Projekt-Root:

    docker compose up --build

Im Hintergrund:

    docker compose up --build -d

### Stoppen

    docker compose down

Mit Entfernen des Laufzeit-Zustands:

    docker compose down -v

---

## Services (Compose)

Das Compose-Setup startet:

- `redis`
- `session_control`
- `worker-1`
- `worker-2`
- `worker-3`

Interne Kommunikation erfolgt über Service-DNS (z. B. `redis`).

---

## Erreichbarkeit

Nach dem Start ist `session_control` erreichbar unter:

    http://localhost:8000

---

## Funktionstest

### Session anlegen

    curl -X POST http://localhost:8000/sessions -H "Content-Type: application/json" -d "{\"client_id\":\"client-1\",\"stream_profile\":\"480p\",\"transport\":\"udp\"}"

Mehrfach ausführen:

- 3 Requests: erfolgreich, jeweils anderer `worker_id`
- 4. Request: Fehler

      No warm workers available

Nach Ablauf der Session-TTL werden Worker automatisch wieder freigegeben.

---

## Redis-Status prüfen

In Redis einloggen:

    docker compose exec redis redis-cli

Verfügbare Worker:

    SMEMBERS workers:warm

Worker-Status:

    GET worker:worker-1
    GET worker:worker-2
    GET worker:worker-3

Session prüfen:

    GET session:<session_id>

TTL prüfen:

    TTL session:<session_id>

Interpretation:

- TTL > 0: Session aktiv
- TTL = -2: Session existiert nicht mehr (abgelaufen/gelöscht)

---

## Logs

Alle Logs:

    docker compose logs -f

Einzelne Services:

    docker compose logs -f session-control
    docker compose logs -f worker-1
    docker compose logs -f worker-2
    docker compose logs -f worker-3
    docker compose logs -f redis

---

## Optional: manueller Start ohne Compose

Nur für Debugging-Zwecke.

### Redis

    docker run -p 6379:6379 redis:7

### session_control

    set REDIS_URL=redis://localhost:6379/0
    uvicorn session_control.app.main:app --host 0.0.0.0 --port 8000

### worker

    set REDIS_URL=redis://localhost:6379/0
    set WORKER_ID=worker-1
    set WORKER_PORT=9000
    uvicorn worker.app.main:app --host 0.0.0.0 --port 9000

---

## Wichtige Hinweise

### Netzwerkverhalten

| Kontext | Redis Host |
|--------|-----------|
| Lokal (Python) | localhost |
| Docker Compose | redis |
| Kubernetes | redis |

---

### Worker ID

- Muss eindeutig sein
- Wird per Environment Variable gesetzt
- In orchestrierten Umgebungen (z. B. Kubernetes) durch die Runtime vergeben

---

### Häufige Fehler

- Verwendung von `localhost` innerhalb von Containern
- falsche Redis-URL je nach Umgebung
- nicht gebaute Images bei Compose (`--build` vergessen)
- mehrere Redis-Instanzen parallel aktiv

---

## Aktuelle Einschränkungen

1. Keine Medienverarbeitung (kein UDP / WebRTC)
2. Redis Single-Instance
3. Kein globaler Reconciliation-Loop
4. Service Discovery abhängig von Umgebung (`localhost` vs. `redis`)
5. Minimaler Zustandsautomat (`warm`, `reserved`)

---

## Nächste Schritte

- Kubernetes Deployment (z. B. k3d)
- Service Discovery über Kubernetes Services
- Ingest / Relay Layer
- UDP-basierte Verarbeitung
- spätere WebRTC Integration

---

## Hinweise

Dieses Projekt wird iterativ entwickelt.

Der Fokus liegt aktuell auf:

- klarer Trennung von Control Plane und Worker
- deterministischem Worker-Management
- konsistentem Zustandsmodell