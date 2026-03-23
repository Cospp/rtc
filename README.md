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

Der grundlegende Datenfluss sieht derzeit so aus:

    Client -> session_control -> Redis <- worker

### Rollen

#### session_control

Die Control Plane.

Verantwortung:
- Entgegennahme von Session-Anfragen
- Auswahl freier Worker
- atomare Worker-Reservation
- Speicherung von Session-Zuständen

#### worker

Die Worker-Komponente.

Verantwortung:
- Registrierung in Redis
- periodischer Heartbeat
- Verwaltung des eigenen Zustands
- automatische Freigabe bei abgelaufenen Sessions

#### redis

Koordinations- und Zustandslayer.

Wird aktuell verwendet für:
- Session-State (`session:<id>`)
- Worker-State (`worker:<id>`)
- Worker-Discovery (`workers:warm`)
- TTL-basierte Liveness

---

## Aktueller Stand

Das System ist funktional lauffähig und implementiert bereits den vollständigen Worker-Lifecycle:

    warm -> reserved -> warm

### Implementierte Funktionen

- `session_control` Service (FastAPI)
- startbarer Server (Uvicorn)
- Redis-Anbindung
- Startup-Validierung (Service startet nur bei erreichbarem Redis)
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

Die gesamte Operation erfolgt atomar innerhalb von Redis.

Hinweis:
Die Atomarität gilt aktuell nur auf Ebene einer einzelnen Redis-Instanz.

---

### Session-Modell

Sessions repräsentieren einen Verarbeitungsauftrag.

    session:<id> -> {
      status: assigned,
      worker_id: <worker_id>,
      ...
    }

Eigenschaften:

- Sessions besitzen eine TTL
- Ablauf der TTL löscht den Session-Key automatisch
- Worker erkennen den Verlust und geben sich frei

---

### Worker Self-Healing

Worker prüfen im Heartbeat:

    wenn status == reserved und session nicht existiert -> setze status = warm

Damit werden inkonsistente Zustände automatisch bereinigt.

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
      "worker_id": "worker-1",
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
        app/
          api/
          core/
          redis/
          services/
          models/
          main.py

      worker/
        app/
          network/
          redis/
          services/
          models/
          core/
          main.py

      docs/

---

## Voraussetzungen

- Python 3.11
- Redis

Redis lokal starten:

    docker run -p 6379:6379 redis:7

---

## Starten

### session_control

    python -m uvicorn session_control.app.main:app

---

### worker

    python -m uvicorn worker.app.main:app --port 9000

---

## Aktuelle Einschränkungen

1. Keine echte Medienverarbeitung  
   (kein UDP / WebRTC)

2. Atomarität ist Redis-instanzlokal  
   (Lua basiert auf Single-Instance-Modell)

3. Kein zentraler Reconciliation-Loop  
   (nur Worker-internes Self-Healing)

4. Endpoint-Konfiguration noch lokal  
   (`127.0.0.1` statt Service Discovery)

5. Zustandsmaschine minimal  
   (nur `warm`, `reserved`)

---

## Nächste Schritte

- Dockerisierung der Services
- docker-compose Setup
- Vorbereitung für Kubernetes
- UDP-basierte Verarbeitung im Worker
- später WebRTC (ICE / STUN / TURN)

---

## Hinweise

Dieses Projekt wird iterativ entwickelt.

Die Dokumentation beschreibt den aktuellen Implementierungsstand und wird fortlaufend erweitert.