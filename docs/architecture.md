
# Architecture

## Zweck

Dieses Dokument ist die kanonische Architektur-Referenz für das Projekt. Es beschreibt:

- den aktuell implementierten Zwischenstand
- das angestrebte Zielbild
- die Rollen und Grenzen aller Komponenten
- die Zustandsverträge in Redis
- die Begründungen für zentrale Architekturentscheidungen

Die Root-[README.md](../README.md) beschreibt nur den aktuellen Ist-Zustand. Dieses Dokument darf deutlich weiter nach vorne schauen und das Zielsystem vollständig beschreiben.

## Aktuell implementierter Zwischenstand

Der aktuelle Repository-Stand implementiert bereits die Control- und Ingest-Kette:

```text
Client oder Dummy-Client -> session-control
     -> reserviert relay + worker
     -> bindet Session an relay

Client oder Dummy-Client -> relay
     -> nimmt Session-Ingest an
     -> erneuert Session-TTL
     -> leitet Payload an worker weiter

worker
  -> verarbeitet die Session intern
  -> schreibt Media-Statistiken nach Redis
```

Bereits umgesetzt sind:

- ein eigenständiger Relay-Service in Go
- Relay-Registrierung und Kapazitätsverwaltung in Redis
- atomare Zuweisung von Relay und Worker in `session-control`
- workerseitige interne Bind- und Ingest-Endpunkte
- TTL-basierte Session-Liveness über den Relay-Ingest

Noch nicht umgesetzt sind:

- WebRTC-Signaling
- SDP Offer/Answer
- ICE, STUN, TURN
- echte RTC-Terminierung auf dem Relay
- Dual-Ingest- oder Promotion-Logik
- Draining für Relays und Worker

Der aktuelle Zustand ist also bewusst ein sauberer Relay-Zwischenstand, nicht das Endsystem.

## Architekturziele

Die Zielarchitektur folgt diesen Grundsätzen:

- `session-control` bleibt Control Plane und Signaling-Orchestrator
- `relay` wird die einzige clientnahe Medienkante
- `worker` bleibt die interne Session-Verarbeitung hinter dem Relay
- Redis bleibt Koordinationsstore, nicht Medienpfad
- Clients sprechen nie direkt mit Workers
- öffentliche Medienskalierung erfolgt über Media-Nodes
- pro Media-Node läuft genau eine Relay-Instanz

Diese Ziele existieren aus drei Gründen:

1. öffentliche und interne Verantwortung sollen hart getrennt bleiben
2. die Medienkante soll skalierbar und operativ klar adressierbar sein
3. die Control Plane soll keinen Medienverkehr terminieren oder weiterleiten müssen

## Cloud- und Skalierungsmodell

Die Architektur ist bewusst als verteiltes Cluster-Modell aufgebaut und nicht als einzelner Monolith.

Zielbild im Betrieb:

```text
Clients
  -> session-control
       -> Redis für Koordination und Scheduling
       -> weist konkreten relay und konkreten worker zu

Clients
  -> relay auf einem Media-Node
       -> terminiert später RTC
       -> nimmt Medien an
       -> leitet intern an worker weiter

worker
  -> verarbeitet Session intern
  -> bleibt nicht öffentlich exponiert
```

Die Trennung existiert nicht aus Stilgründen, sondern aus Betriebsgründen:

- die Lastprofile der Komponenten sind unterschiedlich
- die Fehlerbilder der Komponenten sind unterschiedlich
- die öffentliche Medienkante muss anders skaliert werden als die Control Plane
- interne Verarbeitungs-Worker sollen austauschbar bleiben, ohne den Client-Pfad umzubauen

### Warum kein Monolith

Ein einzelner Service für Session-Orchestrierung, Medienannahme, RTC, Worker-Logik und Scheduling würde mehrere Probleme erzeugen:

- jede Medienlast würde direkt auf den Control-Plane-Prozess durchschlagen
- horizontale Skalierung wäre unklar, weil API-Last und Medienlast gemeinsam wachsen
- Fehler in der Medienverarbeitung hätten größere Blast Radius auf Session-Erzeugung und Signaling
- öffentliche Erreichbarkeit und interne Verarbeitung wären nicht mehr sauber getrennt

Die Architektur trennt diese Verantwortungen deshalb absichtlich in:

- `session-control` für Orchestrierung
- `relay` für öffentliche Medienkante
- `worker` für interne Session-Verarbeitung
- `redis` für gemeinsame Koordination

### Unabhängige Skalierung

Die Komponenten sollen bewusst getrennt wachsen können:

- `session-control` skaliert nach API-, Scheduling- und Signaling-Last
- `relay` skaliert nach öffentlicher Medienlast und Verbindungsdichte
- `worker` skaliert nach eigentlicher Session-Verarbeitungsarbeit
- Redis skaliert nicht mit Medienpayload, sondern mit Zustands- und Koordinationslast

Das ist wichtig, weil diese Lastarten in realen Systemen selten proportional sind.

Beispiele:

- viele Session-Anfragen bei wenig Medienvolumen belasten primär `session-control`
- wenige, aber sehr schwere Medienstreams belasten primär `relay` und `worker`
- neue Analyse- oder Recording-Features erhöhen primär die `worker`-Last

### Rolle der Media-Nodes

Der Relay wird nicht als austauschbarer API-Pod betrachtet, sondern als Repräsentant eines Media-Nodes.

Das Zielmodell ist:

- ein Media-Node stellt eine klar messbare Medienkapazität bereit
- genau ein Relay repräsentiert diese Medienrolle auf dem Node
- `session-control` wählt nicht "irgendeinen Pod", sondern eine konkrete Medienkante

Das verbessert:

- Routing-Transparenz
- Kapazitätsmessung pro Medienkante
- spätere RTC-Terminierung auf genau dem Knoten, der dem Client zugewiesen wurde
- operative Debugbarkeit bei Last, Ausfall und Draining

### Warum Worker separat horizontal skalieren

Worker bleiben hinter den Relays, weil ihre Skalierungslogik eine andere ist als die der Medienkante.

Worker können später sehr unterschiedliche Arbeit tragen:

- Decode
- Analyse
- Recording
- Encoding
- Weiterleitung an nachgelagerte Systeme

Diese Arbeit kann CPU-, RAM- oder später auch GPU-lastig sein. Deshalb sollen Worker separat von den Relays skaliert werden können.

Der Relay muss dagegen vor allem:

- Sessions annehmen
- Verbindungen stabil halten
- Medien ingress-seitig terminieren oder weiterreichen

Die Architektur trennt deshalb bewusst:

- Edge- und Transportverantwortung auf dem Relay
- eigentliche Session-Arbeit auf dem Worker

### Fehlerisolation und Blast Radius

Die Trennung reduziert bewusst die Auswirkungen einzelner Fehler:

- ein überlasteter Worker soll nicht die Session-Erzeugung blockieren
- ein Problem im Dashboard oder in der Control Plane soll nicht direkt Medienstreams terminieren
- ein defekter Media-Node soll als konkrete Relay-Fehlerdomäne sichtbar werden
- ein Worker-Restart soll nicht bedeuten, dass Clients direkt einen anderen öffentlichen Pfad lernen müssen

Damit wird das System nicht automatisch fehlertolerant, aber beobachtbarer und kontrollierbarer.

### Warum Redis nicht im Medienpfad liegt

Redis ist in diesem Modell der gemeinsame Koordinationsstore, nicht der Ort für Medienfluss.

Das ist wichtig für Skalierung und Einfachheit:

- Medienpayloads dürfen nicht durch den zentralen Store laufen
- Redis speichert nur Ownership, Liveness, Scheduling und beobachtbare Statistiken
- dadurch bleibt Redis klein, schnell und für atomare Entscheidungen geeignet

Das Zielbild ist also explizit:

- verteilte Medienverarbeitung
- zentral koordinierter Zustand
- keine zentrale Medienvermittlung über Redis oder `session-control`

## Komponenten und Verantwortlichkeiten

### `session-control`

Rolle:

- REST-Einstiegspunkt
- Session-Orchestrator
- Signaling-Orchestrator
- Scheduling-Entscheider

Verantwortung:

- Session-Anfragen annehmen
- Relay und Worker auswählen
- Session-State schreiben
- Relay-Bind auslösen
- später SDP und ICE vermitteln

Nicht-Verantwortung:

- keine Medienverarbeitung
- keine WebRTC-Terminierung
- keine direkte Client-Medienverbindung

### `relay`

Aktuelle Rolle:

- sessiongebundener Medien-Ingress
- Redis-registrierter Relay mit Heartbeat und Kapazität
- Weiterleiter von Session-Ingest an den Worker

Zielrolle:

- RTC-fähiger Media-Node-Relay
- einziger öffentlicher Medienendpunkt pro zugewiesener Session
- Terminierung von WebRTC und clientnaher Medienlogik

Verantwortung:

- Registrierung des Relay-Zustands
- Veröffentlichung von internem und öffentlichem Endpunkt
- Verwaltung gebundener Sessions
- Session-Liveness während aktiven Ingests
- Weiterleitung zum zuständigen Worker
- später WebRTC, ICE, STUN/TURN-Nutzung und echte Medien-Terminierung

### `worker`

Aktuelle Rolle:

- interner Session-Prozessor
- Empfänger von relayseitigem Session-Ingest
- Producer von workerseitigen Media-Statistiken

Zielrolle:

- interne Verarbeitungsinstanz pro Session
- Ort für Decode, Analyse, Recording, Encoding, Weiterverarbeitung oder nachgelagerte Medienlogik

Verantwortung:

- Heartbeat und Worker-State
- Session-Bindings
- interne Medienannahme
- aktive Session-Verarbeitung

Nicht-Verantwortung:

- keine direkte Client-Konnektivität
- keine öffentliche Signaling- oder Medienkante

### `redis`

Rolle:

- zentraler Zustands- und Koordinationsstore

Verantwortung:

- Session-State
- Relay-State
- Worker-State
- TTL-basierte Liveness
- Scheduling-Sets
- atomare Reservierungspfad-Logik via Lua

Redis speichert keine Medienpayloads und keine RTC-Zustände im Sinne laufender ICE-, DTLS- oder SRTP-Kontexte.

### `coturn`

Aktueller Stand:

- nicht im Runtime-Pfad implementiert

Zielrolle:

- separate STUN/TURN-Infrastruktur

Verantwortung:

- Adress- und Kandidatenermittlung via STUN
- Relay-Fallback via TURN, wenn direkte Client-zu-Relay-Konnektivität scheitert

Wichtig: TURN gehört nicht in `session-control` und nicht in den Worker. Es ist eine eigenständige RTC-Infrastrukturrolle.

## Control Plane und Media Plane

### Control Plane

Zur Control Plane gehören:

- `session-control`
- Redis-State und Scheduling
- Heartbeats und TTLs
- Session-Orchestrierung
- Signaling-Orchestrierung
- Dashboard und Beobachtbarkeit

### Media Plane

Zur Media Plane gehören:

- Relay-Ingest
- später WebRTC auf dem Relay
- interne Weiterleitung zum Worker
- workerseitige Verarbeitung

Diese Trennung ist absichtlich hart. Sie verhindert, dass der Control-Plane-Service schleichend zum Medienknoten wird oder dass Worker öffentliche Client-Verbindungen übernehmen müssen.

## Warum der Relay zum Media-Node werden soll

Die zentrale Zielentscheidung ist:

- öffentliche Medienskalierung soll über Media-Nodes erfolgen
- ein Relay repräsentiert die Medienrolle eines Media-Nodes

Begründung:

- der öffentliche Medienendpunkt ist dann klar einem Relay zugeordnet
- Fehlerdomänen werden verständlicher
- Kapazität wird pro Media-Node messbar
- Scheduling und Routing bleiben transparent

Das Zielmodell ist ausdrücklich nicht:

- beliebige Relay-Pods hinter einer undurchsichtigen Shared-Edge
- direkte Worker-Exposure
- ein NLB-Port-Pool als dauerhaftes Architekturzentrum

Stattdessen ist das Ziel:

- `1 relay ~= 1 media-node`
- `session-control` wählt eine konkrete Medienkante aus
- der Client spricht für Medien danach mit genau diesem Relay

## Warum Workers hinter Relays bleiben

Workers bleiben intern, weil die Rollen bewusst getrennt sind:

- Relay = öffentliche Medienkante und später RTC-Terminator
- Worker = interne Session-Verarbeitung

Diese Trennung bringt:

- weniger öffentliche Angriffsfläche
- klarere Debugging- und Zuständigkeitsgrenzen
- unabhängige Skalierung von Relay und Worker
- die Möglichkeit, Worker-Technik intern zu verändern, ohne den Client-Pfad neu zu definieren

## Aktueller End-to-End-Flow

### 1. Relay startet

- Relay lädt seine Konfiguration
- registriert sich in Redis
- startet Heartbeats
- veröffentlicht Kapazität und Verfügbarkeit

### 2. Worker startet

- Worker registriert sich in Redis
- startet Heartbeats
- meldet sich als warm

### 3. Client fordert Session an

- `POST /sessions` geht an `session-control`

### 4. `session-control` weist Ressourcen zu

- atomare Auswahl von einem verfügbaren Relay
- atomare Auswahl von einem warmen Worker
- Persistenz der Session
- interner Bind-Call an den Relay

### 5. Relay bindet Worker

- Relay lädt den Worker-Record
- markiert den Worker aktiv
- bindet die Mediensession auf dem Worker
- speichert die Session lokal im Relay-Zustand

### 6. Session-Ingest läuft

- Sender liefert Payload an den Relay
- Relay prüft die gebundene Session
- Relay leitet die Payload an den Worker weiter
- Relay erneuert in Intervallen die Session-TTL
- Relay und Worker schreiben Media-Statistiken

### 7. Session endet oder läuft aus

- bei ausbleibendem Ingest läuft die Session-TTL aus
- Relay räumt die gebundene Session aus seinem lokalen Zustand
- Relay gibt den Worker wieder frei
- Worker-Heartbeat räumt den eigenen Zustand zusätzlich ab

## Ziel-End-to-End-Flow mit RTC

### 1. Relay veröffentlicht einen erreichbaren öffentlichen Medienendpunkt

In der Zielarchitektur veröffentlicht der Relay:

- `relay_id`
- `internal_endpoint`
- `public_endpoint`
- Kapazität
- Heartbeat

### 2. `session-control` wählt Relay und Worker

- der Session-State kennt Relay und Worker bereits vor Medienbeginn
- `session-control` bleibt erster öffentlicher Einstiegspunkt

### 3. Signaling

- Client startet mit `session-control`
- `session-control` vermittelt Offer/Answer
- `session-control` vermittelt ICE-Kandidaten

### 4. Medienaufbau

- Client baut WebRTC zum zugewiesenen Relay auf
- der Relay terminiert die RTC-Verbindung
- der Relay leitet Medien intern an den Worker weiter

### 5. Interne Verarbeitung

- Worker verarbeitet die Session intern
- der Worker bleibt von externer Client-Konnektivität entkoppelt

## ICE, STUN und TURN in diesem Modell

Wofür sie nicht da sind:

- nicht für Cluster-Scheduling
- nicht für Worker-Zuweisung
- nicht als Ersatz für Redis-State

Wofür sie da sind:

- Aufbau einer echten RTC-Verbindung zwischen externem Client und zugewiesenem Relay

Die Reihenfolge ist daher:

1. `session-control` wählt Relay und Worker
2. `session-control` vermittelt Signaling
3. Client und Relay bauen RTC über SDP und ICE auf
4. STUN/TURN helfen bei Konnektivität, nicht beim Scheduling

## Redis-Verträge

### Aktuelle Schlüssel

```text
session:{session_id}
relay:{relay_id}
worker:{worker_id}
session-media-relay:{session_id}
session-media-worker:{session_id}
relays:available
workers:warm
```

### Aktueller Session-Record

Der Session-Record enthält aktuell mindestens:

- `session_id`
- `client_id`
- `status`
- `relay_id`
- `relay_internal_endpoint`
- `relay_public_endpoint`
- `worker_id`
- `stream_profile`
- `transport`
- `created_at`

### Aktueller Relay-Record

Der Relay-Record enthält aktuell mindestens:

- `relay_id`
- `status`
- `public_endpoint`
- `internal_endpoint`
- `last_heartbeat`
- `current_sessions`
- `max_sessions`

### Aktueller Worker-Record

Der Worker-Record enthält aktuell mindestens:

- `worker_id`
- `status`
- `endpoint`
- `last_heartbeat`
- `assigned_session_id`

## Warum wir Lua nutzen

Lua wird im Projekt bewusst nur für den schmalen, kritischen Koordinationspfad verwendet:

- Ressourcenreservierung von Relay und Worker
- spätere kontrollierte Freigabe

Begründung:

- die Entscheidung muss atomar in Redis stattfinden
- mehrere `session-control`-Instanzen dürfen denselben Worker oder Relay nicht gleichzeitig reservieren
- Roundtrip-Ketten aus `GET`, `SET`, `SPOP`, `SADD`, `SREM` im Anwendungscode würden Race Conditions erzeugen

Die Lua-Skripte sind damit kein allgemeines Business-Logic-Layer, sondern ein gezieltes Werkzeug für:

- atomare Auswahl
- atomare Statusübergänge
- konsistente Rollbacks bei Teilfehlern

Der aktuelle stale-worker-Fix ist ein gutes Beispiel: Ein veralteter Worker-Eintrag im `workers:warm`-Set darf die gesamte Session-Zuweisung nicht mehr scheitern lassen. Diese Korrektur gehört direkt in den atomaren Scheduling-Pfad und damit sinnvoll in Lua.

## TTLs, Heartbeats und Liveness

Die Architektur setzt bewusst auf TTLs und Heartbeats:

- Worker und Relays melden Liveness über Heartbeats
- Sessions haben eine TTL
- Relay-Ingest erneuert die Session-TTL während aktiver Medienzufuhr

Warum:

- verteilte Liveness wird explizit sichtbar
- abgerissene Zustände können ohne globale Locks bereinigt werden
- die Control Plane bleibt zustandsarm und beobachtbar

## Zielmodell für Failover

Das langfristige Zielbild für redundanten Ingest ist:

- eine Session kann einen Primary- und einen Secondary-Relay besitzen
- beide Pfade können bereits Ingest sehen
- nur ein Worker verarbeitet aktiv
- Promotion wird explizit durch die Control Plane oder einen Watchdog entschieden

Wesentliche Zielpunkte:

- `primary_relay_id`
- `secondary_relay_id`
- `primary_worker_id`
- `secondary_worker_id`
- `active_relay_id`
- `active_worker_id`
- klarer Session-State für Promotion und Fehlerfall

Wichtig:

- Failover ist nicht gleich nahtloses Handover
- Redis kann Liveness und Ownership modellieren
- laufende RTC-Kontexte werden nicht allein durch Redis übertragbar

## Technologieentscheidungen

### `session-control` in FastAPI

Begründung:

- API- und zustandsorientierte Logik
- schnelle Iteration für Control-Plane-Endpunkte
- gute Passung für Orchestrierung und Signaling

### `relay` in Go

Begründung:

- netzwerknahe, lang laufende Sessionarbeit
- gute Passung für hohe Verbindungsparallelität
- günstiger Weg in Richtung RTC-/Medienknoten

### `worker` vorerst in Python

Begründung:

- Worker ist aktuell interner Prozessor und Zustandsmanager
- Medienlogik kann schrittweise hinter den vorhandenen Endpunkten wachsen
- die technologische Entscheidung für die eigentliche Verarbeitungsengine bleibt offen

## Nicht-Ziele

Dieses Dokument behauptet nicht:

- dass der aktuelle Repository-Stand bereits RTC-fähig ist
- dass der aktuelle Relay bereits ICE, DTLS oder SRTP terminiert
- dass Draining und Rolling Updates bereits umgesetzt sind
- dass Dual-Ingest- oder Promotion-Logik schon implementiert ist

## Verwandte Dokumente

- [../README.md](../README.md)
- [runtime-lifecycle.md](runtime-lifecycle.md)
- [kubernetes.md](kubernetes.md)
