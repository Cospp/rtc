# RTC Zielarchitektur

## Inhaltsverzeichnis

- [Ziel dieses Dokuments](#ziel-dieses-dokuments)
- [Architekturprinzipien](#architekturprinzipien)
- [Systemübersicht](#systemübersicht)
- [Rollen der Komponenten](#rollen-der-komponenten)
- [End-to-End-Flow](#end-to-end-flow)
- [Zustandsmodell in Redis](#zustandsmodell-in-redis)
- [Technologieentscheidungen](#technologieentscheidungen)
- [Control Plane und Media Plane](#control-plane-und-media-plane)
- [Fehlerfälle und Recovery](#fehlerfälle-und-recovery)
- [Laufzeit und Betriebslogik](#laufzeit-und-betriebslogik)
- [Skalierung und Zielbild für Cluster](#skalierung-und-zielbild-für-cluster)
- [Implementierungsreihenfolge](#implementierungsreihenfolge)

## Ziel dieses Dokuments

Dieses Dokument beschreibt die geplante Zielarchitektur des Systems vom ersten Client-Request bis zur Verarbeitung des Streams im Worker.

Es ist die zentrale fachliche Referenz für:

- Zuständigkeiten der Services
- Redis als Koordinationsschicht
- Session-, Relay- und Worker-Zustand
- den zukünftigen Medienpfad
- die festgelegten Technologiegrenzen

Dieses Dokument beschreibt das Sollbild. Der aktuelle Ist-Zustand des Repositories steht weiterhin in der Root-[README.md](/C:/Users/cosku/Desktop/rtc/README.md).

## Architekturprinzipien

Die Architektur folgt diesen Grundsätzen:

- `session-control` ist die Control Plane
- `relay` ist die einzige clientseitige Medienkante
- `worker` ist die interne Verarbeitungsinstanz hinter dem Relay
- Redis speichert ausschließlich verteilten Zustand, keine Medienpayloads
- Browser und andere Clients verbinden sich nie direkt mit einem Worker
- WebRTC-Terminierung liegt vollständig im Relay
- Worker verarbeiten den intern weitergeleiteten Stream über einen separaten Medienprozess

## Systemübersicht

```text
Client
  -> session-control
     -> Redis
     -> ordnet relay zu + reserviert worker exklusiv

Client
  -> relay
     -> WebRTC / Signaling / STUN / ICE
     -> interner Medienfluss zum worker

worker
  -> separater Medienprozess
  -> Verarbeitung / Encoding / weitere Medienlogik

relay, worker, session-control
  <-> Redis für State, Heartbeats, TTLs und Zuordnung
```

## Rollen der Komponenten

### session-control

`session-control` ist der zentrale REST-Einstiegspunkt für Clients vor Beginn des Medienflusses.

Verantwortung:

- Session-Requests annehmen
- Session-Objekt erzeugen
- einen geeigneten Relay auswählen
- einen geeigneten Worker auswählen
- einen Relay mit freier Kapazität der Session zuordnen
- einen Worker exklusiv für die Session reservieren
- Session-State in Redis schreiben
- dem Client die öffentliche Relay-Verbindung zurückgeben

`session-control` verarbeitet keinen Videostream und terminiert keine WebRTC-Verbindung.

### relay

Der `relay` ist die einzige clientnahe Medienkomponente.

Verantwortung:

- nimmt viele Clients parallel an
- führt die vollständige clientseitige RTC-Logik aus
- terminiert WebRTC-Verbindungen
- verarbeitet Signaling, STUN, ICE und später TURN-nahe Logik
- kennt die interne Zuordnung `session -> relay + worker`
- leitet den Medienfluss an den reservierten Worker weiter
- schreibt Relay-State und Heartbeats nach Redis

Der Relay ist keine passive Weiterleitung, sondern eine zustandsbehaftete Edge-Komponente.

### worker

Der `worker` ist die interne Verarbeitungsinstanz pro Session.

Verantwortung:

- registriert sich in Redis
- sendet Heartbeats
- hält den Worker-State aktuell
- wird durch `session-control` einer Session zugewiesen
- erhält den Stream intern vom Relay
- startet und überwacht einen separaten Medienprozess
- führt Encoding, Transcoding oder weitere Medienlogik aus

Wichtig:

Der Worker spricht nie direkt mit Browsern oder sonstigen Clients.

### redis

Redis ist der zentrale Koordinationsstore.

Verantwortung:

- Session-State
- Relay-State
- Worker-State
- Heartbeats
- TTL-basierte Liveness
- Reservation und Zuordnung

Redis speichert keine Medienframes und keinen Video-Transport.

## End-to-End-Flow

### 1. Relay startet

- Relay registriert sich in Redis
- setzt sich zunächst auf `starting`
- startet Heartbeats
- meldet sich bei Einsatzbereitschaft als `warm`

### 2. Worker startet

- Worker registriert sich in Redis
- setzt sich auf `starting`
- startet den lokalen Medienprozess
- startet Heartbeats
- meldet sich bei Einsatzbereitschaft als `warm`

### 3. Client fordert Session an

Der Client ruft `POST /sessions` auf `session-control` auf.

### 4. session-control ordnet Ressourcen zu

`session-control` wählt:

- einen Relay mit freier Kapazität
- einen warmen Worker

Dann wird eine Session mit mindestens diesen Feldern angelegt:

- `session_id`
- `client_id`
- `relay_id`
- `worker_id`
- `status`

### 5. session-control antwortet dem Client

Der Client erhält:

- `session_id`
- Relay-Verbindungsinformationen
- spätere Signaling- oder Transportdaten

Wichtig:

Die interne Zuordnung zu `relay` und `worker` ist bereits fest, bevor der Client senden darf. Der Relay wird dabei nicht exklusiv reserviert, sondern anhand seines Kapazitätsmodells ausgewählt.

### 6. Client verbindet sich mit dem Relay

Der Client spricht ausschließlich mit dem Relay.

Der Relay übernimmt:

- Signaling
- STUN
- ICE
- WebRTC-Terminierung

### 7. Relay koppelt die Session an den Worker

Der Relay kennt über Redis oder über die Session-Antwort den zugehörigen Worker.

Danach wird der eingehende Stream intern an den der Session exklusiv zugeordneten Worker weitergeleitet.

### 8. Worker verarbeitet den Stream

Der Worker-Control-Layer:

- hält den Status in Redis aktuell
- überwacht den Medienprozess
- markiert den Worker bei aktiver Verarbeitung als `active`

Der Medienprozess übernimmt die eigentliche Streamverarbeitung.

### 9. Session endet

- Session wird geschlossen oder als fehlgeschlagen markiert
- Worker geht auf `warm` zurück oder wird ersetzt
- Relay reduziert seine belegte Kapazität

## Zustandsmodell in Redis

### Session

Key:

`session:{session_id}`

Beispiel:

```json
{
  "session_id": "sess-001",
  "client_id": "client-123",
  "relay_id": "relay-02",
  "worker_id": "worker-44",
  "status": "assigned",
  "stream_profile": "720p",
  "transport": "webrtc",
  "created_at": "2026-03-30T12:00:00Z",
  "updated_at": "2026-03-30T12:00:00Z"
}
```

### Relay

Key:

`relay:{relay_id}`

Beispiel:

```json
{
  "relay_id": "relay-02",
  "status": "warm",
  "public_endpoint": "relay-02.example.net:443",
  "internal_endpoint": "relay-02.rtc.svc:8443",
  "last_heartbeat": "2026-03-30T12:00:00Z",
  "current_sessions": 12,
  "max_sessions": 50
}
```

Mögliche Statuswerte:

- `starting`
- `warm`
- `degraded`
- `full`
- `dead`

### Worker

Key:

`worker:{worker_id}`

Beispiel:

```json
{
  "worker_id": "worker-44",
  "status": "reserved",
  "endpoint": "worker-44.rtc.svc:9000",
  "last_heartbeat": "2026-03-30T12:00:00Z",
  "assigned_session_id": "sess-001"
}
```

Mögliche Statuswerte:

- `starting`
- `warm`
- `reserved`
- `active`
- `dead`

### Zusätzliche Indizes

- `workers:warm`
- `relays:available`

## Technologieentscheidungen

### session-control

Bleibt in FastAPI.

Grund:

- API- und State-orientiert
- keine zeitkritische Medienverarbeitung
- gute Eignung als Control-Plane-Service

### relay

Soll in Go gebaut werden.

Grund:

- viele parallele Verbindungen
- WebRTC-nahe Aufgaben
- lang laufende, zustandsbehaftete Sessions
- geeignete Laufzeit für Netzwerk- und Mediennähe

### worker

Kann vorerst als FastAPI-basierter Control-Layer bestehen bleiben.

Wichtig dabei:

- FastAPI im Worker verwaltet nur Zustand und Prozessorchestrierung
- FastAPI im Worker führt keine Browser- oder WebRTC-Terminierung aus
- die eigentliche Medienverarbeitung läuft in einem separaten Framework oder Prozess

Das bedeutet konkret:

- FastAPI schreibt Worker-State nach Redis
- FastAPI überwacht Heartbeats und Prozesszustand
- der Medienprozess übernimmt Streamannahme, Verarbeitung und Encoding

## Control Plane und Media Plane

### Control Plane

Gehört zu:

- `session-control`
- Redis-State
- Heartbeats
- Reservation
- Zuweisung
- Dashboard
- Debugging

### Media Plane

Gehört zu:

- `relay`
- interner Weiterleitungspfad zum Worker
- separater Medienprozess im Worker

Diese Trennung ist bewusst hart gezogen. Die WebRTC- und Client-Logik wächst nicht in `session-control` oder in den Worker-Control-Layer hinein.

## Fehlerfälle und Recovery

### Relay fällt aus

- Relay-Heartbeat läuft aus
- Session kann als `failed` oder `reconnecting` markiert werden
- `session-control` weist den Relay nicht mehr neu zu

Wichtig:

Der in Redis gespeicherte Relay-State reicht nicht aus, um eine laufende WebRTC-Verbindung nahtlos auf eine neue Relay-Instanz zu übernehmen.

### Worker fällt aus

- Worker-Heartbeat läuft aus
- Session schlägt fehl
- Relay beendet oder räumt die betroffene Session auf

Wichtig:

Auch beim Worker gilt: Redis-State reicht aus, um den Ausfall festzustellen und die Session kontrolliert als Fehlerfall zu behandeln. Redis allein reicht aber nicht aus, damit eine andere Worker-Instanz die laufende Verarbeitung nahtlos übernimmt.

### Client verbindet sich nicht rechtzeitig

- Session-TTL läuft aus
- Relay- und Worker-Reservierung werden freigegeben

### Medienprozess im Worker fällt aus

- Worker-Control-Layer erkennt den Fehler
- Worker wird als `dead` oder `failed` markiert
- Session wird beendet oder als Fehlerzustand markiert

## Laufzeit und Betriebslogik

Details zu:

- Draining und graceful shutdown
- Recovery statt Handover
- Relay- und Worker-Lifecycle
- redundanter Betriebslogik wie Dual-Ingest

stehen in:

- [runtime-lifecycle.md](/C:/Users/cosku/Desktop/rtc/docs/runtime-lifecycle.md)

## Skalierung und Zielbild für Cluster

Die Zielarchitektur ist auch für spätere Cluster-Deployments geeignet, etwa in Azure Kubernetes Service.

Wichtig dafür:

- `session-control` gibt dem Client die richtige öffentliche Relay-Adresse zurück
- Relay-Records unterscheiden sinnvoll zwischen interner und externer Erreichbarkeit
- Worker bleiben interne Cluster-Komponenten
- Clients sprechen nie direkt mit Worker-Endpunkten

Das System skaliert dann grundsätzlich über:

- mehrere `relay`-Instanzen mit Kapazitätsmodell
- viele Worker-Instanzen
- Redis als zentralen Koordinationsstore

## Implementierungsreihenfolge

1. `RelayRecord` als gemeinsames Modell einführen
2. Session-Modell um `relay_id` erweitern
3. Relay-Repository und Relay-Heartbeat definieren
4. atomische Zuweisung für `relay + worker` entwerfen
5. Relay-Service in Go anlegen
6. Worker-Control-Layer um Medienprozess-Orchestrierung erweitern
7. Dashboard später um Relay-State ergänzen

## Verwandte Dokumente

- [README.md](/C:/Users/cosku/Desktop/rtc/README.md)
- [runtime-lifecycle.md](/C:/Users/cosku/Desktop/rtc/docs/runtime-lifecycle.md)
- [kubernetes.md](/C:/Users/cosku/Desktop/rtc/docs/kubernetes.md)
