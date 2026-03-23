# RTC Streaming Plattform

## Überblick

Dieses Projekt dient als Grundlage für eine Plattform zur Annahme und Verarbeitung von Echtzeit-Streams.

Der Fokus liegt aktuell auf dem Aufbau einer **sauberen Service-Struktur** und einer **lauffähigen Control Plane**, die später um Streaming- und Worker-Logik erweitert wird.

---

## Aktueller Stand

Der aktuelle Stand ist eine erste lauffähige Basis.

### Vorhanden

* `session_control` Service (FastAPI)
* Startbarer Server (Uvicorn)
* Redis-Anbindung
* Startup-Validierung (Service startet nur, wenn Redis erreichbar ist)
* Health Endpoint (`/health`)
* Metrics Endpoint (`/metrics`, Prometheus-kompatibel)
* Grundstruktur für weitere Komponenten (`worker`, `shared`)

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

### session_control

Der aktuell implementierte Service.

Verantwortung:

* Starten des Systems
* Redis-Verbindung initialisieren
* Health-Status bereitstellen
* Basis für zukünftige Session-Logik

---

### worker

Strukturell vorbereitet, aber funktional noch nicht implementiert.

Geplant:

* Annahme von Streams
* Verarbeitung von Sessions
* Registrierung im System

---

### Redis

Wird aktuell verwendet für:

* Verfügbarkeitsprüfung beim Startup
* zukünftige Zustandsverwaltung (noch nicht implementiert)

---

## Endpunkte

### Health

```text
GET /health
```

Beispielantwort:

```json
{
  "service": "session-control",
  "status": "ok",
  "redis": true
}
```

---

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

* aktuell nur Stub
* noch keine Logik implementiert

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

* Implementierung von Session-Logik (`POST /sessions`)
* Speicherung von Zuständen in Redis
* Worker-Registrierung
* Zuweisung von Sessions zu Workern

---

## Hinweise

Dieses Projekt wird iterativ entwickelt.
Die Dokumentation beschreibt den aktuellen Stand und wird mit der Implementierung erweitert.
