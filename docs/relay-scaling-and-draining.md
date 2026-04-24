# Relay Scaling and Draining

## Zweck

Dieses Dokument beschreibt das Zielmodell für:

- skalierbare Relay-Kapazität über Media-Nodes
- externe Erreichbarkeit der Relays für späteres WebRTC
- parallelen Betrieb von `warm`- und `draining`-Relays
- kontrollierte Relay-Rollouts mit GitHub Actions als Trigger

Es beschreibt bewusst das angestrebte Betriebsmodell und nicht den heute bereits implementierten Zwischenstand.

## Kernentscheidung

Die Relay-Architektur folgt diesen Regeln:

- `relay` bleibt an die Rolle eines Media-Nodes gekoppelt
- pro Media-Node läuft genau eine Relay-Instanz
- Relay-Skalierung erfolgt über neue Media-Nodes, nicht über beliebige zusätzliche Relay-Pods auf demselben Node
- jeder Relay besitzt einen eigenen extern erreichbaren Endpunkt
- `session-control` weist einer Session immer einen konkreten Relay zu und gibt genau dessen Endpunkt an den Client zurück

Kurzform:

- `1 relay = 1 media-node`
- `1 media-node = 1 externe Relay-Identität`

## Warum dieses Modell

Dieses Modell existiert aus vier Gründen:

- ein Relay ist keine austauschbare Shared-Edge, sondern die konkrete Medienkante eines Media-Nodes
- `session-control` soll nicht "irgendeinen Relay" ausliefern, sondern eine konkrete, später für WebRTC adressierbare Medienkante
- `draining` funktioniert nur sauber, wenn neue Relays parallel bereitstehen können, ohne dieselbe Identität oder denselben Außenendpunkt zu beanspruchen
- Kapazität, Fehlerdomänen und Rollouts bleiben pro Media-Node operativ sichtbar

## Externe Erreichbarkeit

Jeder Relay braucht einen stabilen öffentlichen Endpunkt:

- `public_endpoint = <node-public-address>:<relay-port>`

Dabei gelten diese Regeln:

- alle Media-Nodes dürfen denselben Relay-Port verwenden
- die Kollision wird über unterschiedliche öffentliche Adressen vermieden
- der Port muss nicht clusterweit einzigartig sein
- die Adresse pro Media-Node muss eindeutig sein

Beispiel:

```text
relay-a -> 203.0.113.10:31080
relay-b -> 203.0.113.11:31080
relay-c -> 203.0.113.12:31080
```

Das ist gültig, weil `IP:Port` eindeutig ist, auch wenn der Port auf allen Nodes derselbe bleibt.

## Skalierung

### Lastgetriebenes Hochskalieren

Relay-Skalierung bedeutet in diesem Modell:

- mehr Media-Nodes bereitstellen
- dadurch automatisch mehr Relays erhalten

Der Ablauf ist:

1. Metriken zeigen, dass die Relay-Kapazität knapp wird.
2. Ein Scaler entscheidet, dass weitere Media-Nodes benötigt werden.
3. Die Media-Node-Gruppe wird vergrößert.
4. Auf den neuen Nodes startet das Relay-DaemonSet automatisch genau einen neuen Relay.
5. Der neue Relay registriert sich in Redis.
6. Sobald er betriebsbereit ist, setzt er sich auf `warm`.
7. `session-control` kann ihn ab dann für neue Sessions verwenden.

### Welche Metriken dafür geeignet sind

Typische Signale für diese Entscheidung sind:

- `current_sessions` pro Relay
- Auslastungsgrad relativ zu `max_sessions`
- CPU- oder Bandbreitenlast pro Relay
- Queueing oder andere spätere RTC-relevante Lastsignale

Prometheus sammelt die Metriken. Die Skalierungsentscheidung selbst kommt typischerweise von:

- HPA mit passendem Metrics Adapter
- KEDA
- einem eigenen Capacity-Controller
- und bei Node-Skalierung zusätzlich einer autoskalierenden Media-Node-Gruppe

Prometheus beobachtet also nur. Es startet keine Nodes oder Pods direkt.

## Relay-Statusmodell

Relays sollen langfristig diese Status besitzen:

- `starting`
- `warm`
- `full`
- `draining`
- optional später `dead`

### Bedeutung der Status

- `starting`: Relay registriert sich, ist aber noch nicht schedulbar
- `warm`: Relay darf neue Sessions annehmen
- `full`: Relay ist gesund, aber ohne freie Session-Kapazität
- `draining`: Relay bleibt für bestehende Sessions aktiv, nimmt aber keine neuen Sessions mehr an
- `dead`: Relay ist nicht mehr aktiv oder bewusst aus dem Scheduling entfernt

### Scheduling-Regel

`session-control` darf nur Relays mit Status `warm` für neue Sessions verwenden.

Das bedeutet:

- `warm` ist schedulbar
- `full` ist nicht schedulbar
- `draining` ist nicht schedulbar
- `starting` ist nicht schedulbar

## Redis-Vertrag für Relays

Ein Relay-Record sollte mindestens diese Felder tragen:

```text
relay_id
version
status
public_endpoint
internal_endpoint
current_sessions
max_sessions
last_heartbeat
drain_requested_at
```

Zusatzregeln:

- nur `warm`-Relays dürfen in `relays:available` enthalten sein
- `draining`-Relays dürfen dort nie enthalten sein
- ein drainender Relay darf durch Session-Abbau nicht automatisch wieder auf `warm` springen

## Draining-Modell

### Ziel

Ein Relay im Status `draining` soll:

- keine neuen Sessions mehr bekommen
- laufende Sessions aber kontrolliert zu Ende bedienen

### Verhalten eines drainenden Relay

Sobald ein Relay auf `draining` gesetzt wird, muss er:

- seinen Status sofort auf `draining` setzen
- sich sofort aus `relays:available` entfernen
- neue `BindSession`-Anfragen ablehnen
- bestehende Sessions weiter bedienen
- Heartbeats und Session-Liveness weiter publizieren

Wichtig:

- `draining` bedeutet nicht sofortiger Shutdown
- `draining` bedeutet kontrolliertes Auslaufen

### Exit-Regel

Ein Relay darf sich erst selbst beenden oder beendet werden, wenn beide Bedingungen gelten:

- `status == draining`
- `current_sessions == 0`

Diese Regel ist wichtig, damit ein frisch gestarteter `warm`-Relay mit `current_sessions == 0` nicht versehentlich als "leer" beendet wird.

## Paralleler Betrieb von `warm` und `draining`

Der Parallelbetrieb ist ausdrücklich gewollt.

Während eines Rollouts oder während Kapazitätsverschiebungen können gleichzeitig existieren:

- neue `warm`-Relays für neue Sessions
- alte `draining`-Relays für bestehende Sessions

Das ist die eigentliche Betriebsform für unterbrechungsarme Updates.

Die zentrale Reihenfolge ist immer:

1. neue Kapazität bereitstellen
2. neue Relays `warm` werden lassen
3. alte Relays auf `draining` setzen
4. auf `current_sessions == 0` warten
5. alte Relays sauber beenden

Nie umgekehrt.

## Rollout-Modell

### Rolle von GitHub Actions

GitHub Actions ist in diesem Modell der Trigger und Orchestrator für den Rollout.

GitHub Actions soll:

- nach erfolgreicher CI auf `main` starten
- neue Images bauen und veröffentlichen
- die Zielversion für die Relays ausrollen
- einen Rollout-Job oder ein Rollout-Skript starten

GitHub Actions ist damit nicht "die" Relay-Logik, sondern die Automation, die den Rollout-Prozess anstößt.

### Empfohlenes Setup

Die Relay-spezifische Rollout-Logik sollte in einem normalen Repo-Skript oder Admin-Tool liegen, zum Beispiel:

- `scripts/rollout_relays.py`
- `scripts/rollout_relays.sh`

GitHub Actions ruft dieses Skript auf.

Das ist sauberer, als die gesamte Rollout-Logik direkt in YAML auszudrücken.

## Detaillierter Rollout-Ablauf

### 1. Trigger

Ein Merge auf `main` triggert GitHub Actions.

### 2. Build und Publish

GitHub Actions:

- baut das neue Relay-Image
- pusht das neue Image in die Registry
- markiert die Zielversion, zum Beispiel `relay:v2`

### 3. Zusatzkapazität bereitstellen

Bevor alte Relays gedraint werden, muss zunächst neue Kapazität bereitstehen.

Der Rollout-Prozess:

- vergrößert die Media-Node-Gruppe
- oder stellt sicher, dass bereits freie neue Media-Nodes vorhanden sind

### 4. Neue Relays starten

Auf jedem neuen Media-Node startet das Relay-DaemonSet automatisch einen neuen Relay mit der neuen Version.

Der neue Relay:

- registriert `relay_id`
- registriert `version`
- registriert `public_endpoint`
- registriert `internal_endpoint`
- setzt zunächst `status=starting`

### 5. Neue Relays werden `warm`

Sobald ein neuer Relay komplett betriebsbereit ist:

- setzt er seinen Status auf `warm`
- trägt sich in `relays:available` ein

Ab dann darf `session-control` ihn für neue Sessions verwenden.

### 6. Alte Relays identifizieren

Der Rollout-Prozess sucht nun alte Relays, typischerweise:

- `version != target_version`
- `status in {warm, full}`

### 7. Draining anstoßen

Für genau einen alten Relay wird ein interner Drain-Aufruf ausgeführt, zum Beispiel:

```text
POST /internal/v1/admin/drain/{relay_id}
```

Der Relay setzt daraufhin lokal:

- `status = draining`
- Entfernen aus `relays:available`

Lua ist für diesen Schritt nicht zwingend nötig, solange akzeptiert wird, dass während des Übergangs noch ein kleines Race für eine letzte Session möglich ist.

### 8. Verhalten nach Drain-Start

Nach dem Drain-Aufruf gilt:

- neue Sessions gehen nur auf andere `warm`-Relays
- bestehende Sessions bleiben auf dem drainenden Relay
- der drainende Relay bedient diese Sessions normal weiter

### 9. Warten auf Leerlauf

Der Rollout-Prozess wartet für diesen Relay auf:

- `status == draining`
- `current_sessions == 0`

Erst dann ist der Relay leer.

### 10. Beenden des alten Relay

Wenn der alte Relay leer ist:

- beendet er sich selbst sauber
- oder wird kontrolliert durch den Rollout-Prozess entfernt
- optional wird danach der zugehörige alte Media-Node wieder abgebaut

### 11. Wiederholen

Danach wird der nächste alte Relay gedraint.

Der Rollout läuft also relayweise oder nodeweise, nicht als globaler Big Bang.

## Rollen und Verantwortlichkeiten

### GitHub Actions

- Trigger durch Merge auf `main`
- Build und Publish
- Start des Relay-Rollout-Skripts

### Rollout-Skript oder Rollout-Job

- Zielversion festlegen
- sicherstellen, dass genug neue `warm`-Relays existieren
- alte Relays nacheinander auf `draining` setzen
- auf leere drainende Relays warten
- alte Nodes oder Pods kontrolliert abbauen

### Relay

- eigenen Status in Redis publizieren
- `draining` lokal erzwingen
- neue Sessions ablehnen, wenn `draining`
- bestehende Sessions weiter bedienen
- bei `draining && current_sessions == 0` sauber beenden

### `session-control`

- nur `warm`-Relays für neue Sessions verwenden
- bestehende Sessions nicht während des Drains migrieren
- den konkreten `public_endpoint` des gewählten Relays an den Client zurückgeben

## Wichtige Invarianten

- Nie einen Relay drainen, wenn danach nicht genug `warm`-Kapazität vorhanden ist.
- Nie einen drainenden Relay wieder auf `warm` setzen, nur weil `current_sessions` sinkt.
- Nie einen drainenden Relay terminieren, solange `current_sessions > 0`.
- Neue Sessions gehen immer nur auf `warm`.
- Bestehende Sessions bleiben auf ihrem bereits zugewiesenen Relay.
- Rollouts skalieren erst hoch und drainen erst danach.

## Nicht-Ziele dieses Modells

Dieses Design versucht ausdrücklich nicht:

- laufende Sessions während eines Drains auf einen anderen Relay zu migrieren
- eine Shared-Edge vor alle Relays zu setzen, die die konkrete Relay-Identität versteckt
- Relay-Skalierung als beliebige Pod-Replikation auf denselben Media-Nodes zu modellieren

## Verhältnis zu WebRTC

Für späteres WebRTC bleibt die Rollenverteilung:

- `session-control` vermittelt Signaling
- der Client baut danach die Medienverbindung zu genau dem Relay auf, den `session-control` ausgewählt hat
- der Relay bleibt die konkrete öffentliche Medienkante der Session

TURN ist davon getrennt zu betrachten:

- TURN kann später für Konnektivitätsprobleme benötigt werden
- TURN ersetzt aber nicht die Relay-Auswahl durch `session-control`

## Verwandte Dokumente

- [architecture.md](architecture.md)
- [runtime-lifecycle.md](runtime-lifecycle.md)
- [kubernetes.md](kubernetes.md)
- [observability-and-metrics.md](observability-and-metrics.md)
- [../README.md](../README.md)
