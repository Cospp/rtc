# RTC Streaming Platform

## Überblick

Dieses Repository enthält den aktuell funktionierenden Zwischenstand der Plattform:

- `session-control` nimmt Sessions an und weist Ressourcen zu
- `relay` ist die vorgelagerte Medienkante für eine Session
- `worker` verarbeitet den intern weitergeleiteten Session-Stream
- `redis` ist der verteilte Zustands- und Koordinationsstore

Der aktuelle Runtime-Pfad ist:

```text
Client / Dummy Client
  -> session-control
     -> reserviert relay + worker
     -> bindet die Session an relay

Client / Dummy Client
  -> relay
     -> nimmt Ingest für die Session an
     -> erneuert die Session-TTL während aktiver Datenzufuhr
     -> leitet Payload intern an den gebundenen worker weiter

worker
  -> verarbeitet den Session-Ingest
  -> schreibt Media-Statistiken nach Redis
```

Wichtig: Im aktuellen Stand ist der Relay noch kein RTC-/WebRTC-Endpunkt. Der implementierte Medienpfad ist ein interner, HTTP-basierter Ingest für Sessions und Dummy-Clients.

## Aktueller Systemfluss

1. Ein Client fordert über `POST /sessions` bei `session-control` eine Session an.
2. `session-control` reserviert atomar genau einen verfügbaren Relay und genau einen warmen Worker in Redis.
3. `session-control` legt den Session-Record an und bindet die Session an den zugewiesenen Relay.
4. Der Relay bindet die Session intern an den zugewiesenen Worker und markiert ihn aktiv.
5. Ein Sender liefert Medienpayload an den Relay. Der Relay leitet die Payload an den Worker weiter und erneuert die Session-TTL, solange Ingest ankommt.
6. Wenn kein Ingest mehr ankommt, läuft die Session-TTL aus. Relay und Worker räumen den Zustand anschließend wieder auf.

## Services

### `session-control`

Verantwortung:

- öffentlicher REST-Einstiegspunkt
- Session-Erstellung und Session-Reads
- atomare Zuweisung von `relay + worker`
- Persistenz des Session-Zustands in Redis
- Bind-Aufruf an den zugewiesenen Relay

Wichtige Funktionen:

- `POST /sessions`
- `GET /sessions/{session_id}`
- Redis-Lua-basierte Ressourcenreservierung
- Rückgabe von `relay_id`, `relay_public_endpoint` und `worker_id`

### `relay`

Verantwortung:

- Registrierung und Heartbeat in Redis
- Kapazitäts- und Sessionverwaltung pro Relay
- Annahme von sessiongebundenem Ingest
- TTL-Erneuerung für aktive Sessions
- interne Weiterleitung der Session-Payload an den gebundenen Worker

Wichtige Funktionen:

- `GET /healthz`
- `GET /readyz`
- `POST /internal/v1/sessions/bind`
- `POST /internal/v1/media/ingest/{session_id}`
- Persistenz von `session-media-relay:{session_id}`

### `worker`

Verantwortung:

- Registrierung und Heartbeat in Redis
- interner Session-Bind für Medienverarbeitung
- Annahme von Relay-Ingest
- Persistenz von workerseitigen Media-Statistiken
- Freigabe eigener Session-Bindings, wenn Session-State ausläuft

Wichtige Funktionen:

- `GET /health`
- `POST /internal/v1/media/bind/{session_id}`
- `POST /internal/v1/media/ingest/{session_id}`
- Persistenz von `session-media-worker:{session_id}`

### `redis`

Verantwortung:

- Quelle der Wahrheit für Session-, Relay- und Worker-Zustand
- TTL-basierte Liveness
- Scheduling-relevante Sets und Records
- atomare Koordination über Lua für den kritischen Assignment-Pfad

Wichtige Keys:

```text
session:{session_id}
relay:{relay_id}
worker:{worker_id}
session-media-relay:{session_id}
session-media-worker:{session_id}
relays:available
workers:warm
```

## Aktuell implementierter Funktionsumfang

- Go-basierter Relay-Service mit Health, Readiness, Bind und Ingest
- Relay-Deployment als DaemonSet auf Media-Nodes in Kubernetes
- atomare Zuweisung von Relay und Worker in `session-control`
- Session-Bind zwischen `session-control` und Relay
- workerseitige Bind- und Ingest-Endpunkte für relayed Sessions
- relay- und workerseitige Media-Statistiken in Redis
- Dummy-Client für Session-Erstellung, Relay-Probing und Datei-Ingest
- Stress-Skript für parallele Session- und Ingest-Last
- Swagger unter `/docs`
- einfaches Dashboard unter `/dashboard`

## Aktueller Stand und Grenzen

Der aktuelle Repository-Stand bildet bewusst einen sauberen Zwischenstand:

- Sessions laufen bereits über `session-control -> relay -> worker`
- Session-Liveness hängt an aktivem Ingest auf dem Relay
- Worker bleiben interne Cluster-Komponenten
- Relays sind noch keine RTC-fähigen Media-Nodes

Nicht im aktuellen Stand enthalten:

- WebRTC-Signaling
- SDP Offer/Answer
- ICE, STUN oder TURN im Runtime-Pfad
- Relay-Draining und Rolling-Update-Semantik
- Dual-Ingest- oder Failover-Logik

## Lokale Entwicklung

### Kubernetes mit k3d

Komplettaufbau:

```bash
./scripts/dev.sh
```

Wichtige Parameter:

```bash
MEDIA_NODE_COUNT=4 RTC_DEPLOY_MODE=dev ./scripts/dev.sh
RTC_DEPLOY_MODE=cloud ./scripts/dev.sh
```

Nützliche Redeploys:

```bash
./scripts/redeploy.sh relay
./scripts/redeploy.sh worker
./scripts/redeploy.sh session-control
./scripts/redeploy.sh all
```

Zugriff im Standard-Setup:

- Swagger: `http://localhost:8080/docs`
- Dashboard: `http://localhost:8080/dashboard`
- Relay-Health im Dev-Modus: `http://localhost:31080/healthz`, `http://localhost:31081/healthz`, ...

### Docker Compose

Für einen schnellen lokalen Compose-Start:

```bash
docker compose up --build
```

### Dummy Clients und Last

Datei-Streaming:

```bash
python scripts/dummy_rtc_client.py "C:/Users/cosku/Desktop/cb.mp4"
```

Mehrere parallele Clients:

```bash
./scripts/spawn_dummy_clients.sh 4 "C:/Users/cosku/Desktop/cb.mp4"
```

## Weiterführende Dokumentation

- [docs/architecture.md](docs/architecture.md)
  Detailliertes Zielbild, Architekturentscheidungen und Begründungen.
- [docs/runtime-lifecycle.md](docs/runtime-lifecycle.md)
  Laufzeitverhalten, TTL-Semantik, Cleanup, Draining und Failover-Modell.
- [docs/kubernetes.md](docs/kubernetes.md)
  Operativer Leitfaden für k3d, Deployments und Redeploys.
