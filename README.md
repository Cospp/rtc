# RTC Streaming Plattform

## Überblick

Dieses Projekt dient als Grundlage für eine Plattform zur Annahme und Verarbeitung von Echtzeit-Streams.

Der Fokus liegt aktuell auf dem Aufbau einer **sauberen Service-Struktur** und einer **lauffähigen Control Plane**, die später um Streaming- und Worker-Logik erweitert wird.

---

## Aktueller Stand

Der aktuelle Stand ist eine erste lauffähige Basis mit funktionaler Control Plane und Worker-Zuweisung.

### Vorhanden

* `session_control` Service (FastAPI)
* Startbarer Server (Uvicorn)
* Redis-Anbindung
* Startup-Validierung (Service startet nur, wenn Redis erreichbar ist)
* Health Endpoint (`/health`)
* Metrics Endpoint (`/metrics`, Prometheus-kompatibel)
* Grundstruktur für weitere Komponenten (`worker`, `shared`)

### Zusätzlich implementiert:

* Session-Erstellung (POST /sessions)
* Speicherung von Sessions in Redis (inkl. TTL)
* Worker-Registrierung in Redis
* Worker-Heartbeat (TTL-basierte Liveness)
* Worker-Zuweisung aus workers:warm
* Zuweisung von Sessions zu verfügbaren Workern
* automatische Freigabe reservierter Worker bei abgelaufener Session


### Offene Punkte: 

* keine atomare Zuweisung der Worker
* keine echte Stream-/UDP-Kopplung
* kein Reconciliation-Loop außerhalb des Workers (globale prüfinstanz der serverintegrität)
* Endpoint-Konfiguration noch grob
---

## Projektstruktur

```text
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
```

---

## Komponenten (aktueller Zustand)

Der aktuell implementierte Service.

### session_control

Verantwortung

* Starten des Systems
* Redis-Verbindung initialisieren
* Health-Status bereitstellen
* Entgegennahme von Client-Anfragen
* Erzeugung von Sessions
* Auswahl eines freien Workers
* Zuweisung von Sessions zu Workern
* Speicherung von Session-Zuständen in Redis

---

### worker

Verantwortung

* Registrierung im System (Redis)
* Periodischer Heartbeat (Liveness über TTL)
* Bereitstellung eines Endpoints (zukünftig für Streaming)
* Verwaltung des eigenen Zustands (warm, reserved)

---

### Redis

Wird aktuell verwendet für:

* Verfügbarkeitsprüfung beim Startup
* Session-State (session:<id>)
* Worker-State (worker:<id>)
* Worker-Discovery (workers:warm Set)
* TTL-basierte Liveness und automatische Bereinigung

---

## Endpunkte

### Health

```text
GET /health
```

### Metrics

```text
GET /metrics
```

* Prometheus-kompatibler Endpoint
* aktuell nur Default-Metriken

---

### Sessions (Placeholder)

```text
POST /sessions
```

* Erzeugt eine neue Session und weist einen verfügbaren Worker zu.

Beispiel Post: 
{
  "client_id": "client-1",
  "stream_profile": "480p",
  "transport": "udp"
}

Beispiel Response:
{
  "session_id": "...",
  "client_id": "client-1",
  "status": "assigned",
  "worker_id": "worker-1",
  "ttl_seconds": 60
}

---

## Voraussetzungen

* Python 3.11
* Redis (lokal oder Docker)

Redis starten (Beispiel mit Docker):

```bash
docker run -p 6379:6379 redis:7
```

---

## Starten

Im Projektroot:

```bash
python -m uvicorn session_control.app.main:app
```

Dann erreichbar unter:

```text
http://127.0.0.1:8000
```

---

## Nächste Schritte

* Automatische Worker-Freigabe bei abgelaufenen Sessions
* Atomare Worker-Reservation (z. B. via Redis Lua Script)
* Einführung eines Reconciliation-Loops
* Erweiterung der Worker-Zustandsmaschine (active, streaming, etc.)
* Integration des tatsächlichen Streaming-Protokolls (UDP / WebRTC)

---

## Hinweise

Dieses Projekt wird iterativ entwickelt.
Die Dokumentation beschreibt den aktuellen Stand und wird mit der Implementierung erweitert.
