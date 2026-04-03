# Runtime Lifecycle und Betriebslogik

## Inhaltsverzeichnis

- [Ziel](#ziel)
- [Grundidee](#grundidee)
- [Relay-Lifecycle](#relay-lifecycle)
- [Worker-Lifecycle](#worker-lifecycle)
- [Graceful Shutdown und Draining](#graceful-shutdown-und-draining)
- [Recovery statt Handover](#recovery-statt-handover)
- [Redundanter Dual-Ingest](#redundanter-dual-ingest)
- [Offene Fragen](#offene-fragen)

## Ziel

Dieses Dokument beschreibt die betriebliche Laufzeitlogik des Systems.

Es ergänzt die Zielarchitektur aus [architecture.md](/C:/Users/cosku/Desktop/rtc/docs/architecture.md) um:

- Lifecycle von Relay und Worker
- Draining und graceful shutdown
- Verhalten bei Ausfällen
- spätere Betriebsoptionen wie redundanten Dual-Ingest

## Grundidee

Die Architektur ist so angelegt, dass Zustände explizit modelliert und in Redis sichtbar gemacht werden.

Dadurch wird möglich:

- neue Sessions nur auf geeignete Instanzen zu schedulen
- bestehende Sessions kontrolliert auslaufen zu lassen
- Ausfälle zu erkennen
- Recovery-Entscheidungen auf Control-Plane-Ebene zu treffen

Nicht automatisch enthalten ist:

- nahtloses Live-Handover laufender WebRTC-Sessions
- transparentes Übernehmen eines aktiven Medienpfads durch eine andere Instanz

## Relay-Lifecycle

Ein Relay trägt mehrere Sessions parallel und wird nicht exklusiv für genau eine Session reserviert.

Sinnvolle Zustände:

- `starting`
- `warm`
- `degraded`
- `full`
- `draining`
- `dead`

Bedeutung:

- `starting`
  Relay ist noch nicht einsatzbereit

- `warm`
  Relay ist gesund und kann neue Sessions annehmen

- `degraded`
  Relay ist grundsätzlich nutzbar, aber unter eingeschränkten Bedingungen

- `full`
  Relay ist gesund, nimmt aber wegen Kapazitätsgrenze keine neuen Sessions mehr an

- `draining`
  Relay nimmt keine neuen Sessions mehr an, bestehende Sessions laufen weiter

- `dead`
  Relay ist ausgefallen oder nicht mehr erreichbar

Zusätzliche Felder im Redis-State:

- `current_sessions`
- `max_sessions`
- `last_heartbeat`

## Worker-Lifecycle

Ein Worker bleibt im aktuellen Zielbild exklusiv pro Session.

Sinnvolle Zustände:

- `starting`
- `warm`
- `reserved`
- `active`
- `draining`
- `dead`

Bedeutung:

- `starting`
  Worker oder Medienprozess ist noch nicht bereit

- `warm`
  Worker ist frei und sofort zuweisbar

- `reserved`
  Worker ist einer Session exklusiv zugeordnet, verarbeitet aber noch nicht aktiv

- `active`
  Worker verarbeitet den Stream aktiv

- `draining`
  Worker nimmt keine neue Session mehr an, beendet aber die aktuelle Verarbeitung kontrolliert

- `dead`
  Worker oder Medienprozess ist ausgefallen

## Graceful Shutdown und Draining

Die Zielarchitektur ist bewusst so aufgebaut, dass später `draining` und `graceful shutdown` ergänzt werden können.

### Relay Draining

Wenn ein Relay gepatcht, neu gestartet oder kontrolliert entfernt werden soll:

- Relay setzt seinen Zustand auf `draining`
- `session-control` weist diesem Relay keine neuen Sessions mehr zu
- bestehende Sessions bleiben aktiv
- sobald alle Sessions beendet sind, kann der Relay sauber abgeschaltet werden

Das Ziel ist:

- keine Unterbrechung bereits laufender Streams
- kontrollierter Rollout
- kontrolliertes Patchen einzelner Relays

### Worker Draining

Wenn ein Worker gepatcht oder entfernt werden soll:

- Worker setzt seinen Zustand auf `draining`
- `session-control` reserviert ihn nicht mehr für neue Sessions
- bestehende Session läuft zu Ende
- danach kann der Worker kontrolliert beendet oder ersetzt werden

Das Ziel ist auch hier:

- bestehende Streams bleiben unangetastet
- neue Sessions landen auf anderen Instanzen

### Scheduling-Regel

Wichtige Konsequenz für die Control Plane:

- `draining`-Relays dürfen keine neuen Sessions annehmen
- `draining`-Worker dürfen nicht neu reserviert werden

## Recovery statt Handover

Redis-State reicht aus, um Ausfälle zu erkennen und Recovery-Entscheidungen zu treffen.

### Relay-Ausfall

Wenn ein Relay ausfällt:

- Heartbeat läuft aus
- Session kann als `failed` oder später `reconnecting` markiert werden
- ein neuer Relay kann für eine neue oder wiederaufgebaute Session verwendet werden

Nicht automatisch möglich:

- nahtlose Übernahme einer laufenden WebRTC-Verbindung durch eine neue Relay-Instanz

Grund:

aktive Verbindungen, ICE-, DTLS- und SRTP-Kontext sowie weitere Laufzeitzustände liegen im Speicher des Relay und nicht vollständig in Redis.

### Worker-Ausfall

Wenn ein Worker ausfällt:

- Heartbeat läuft aus
- Session wird als Fehlerfall behandelt
- ein neuer Worker kann später neu zugewiesen werden

Nicht automatisch möglich:

- nahtlose Übernahme einer laufenden Verarbeitung durch eine andere Worker-Instanz

Auch hier gilt:

Redis liefert Beobachtbarkeit und Recovery-Basis, aber kein automatisches Live-Handover.

## Redundanter Dual-Ingest

Eine spätere Betriebsoption ist redundanter Ingest über zwei getrennte Client-Uplinks oder Modems.

Zielbild:

- ein Client sendet denselben Quellstream doppelt
- die beiden Streampfade landen auf zwei verschiedenen Relays
- die Relays sollten möglichst unterschiedlichen Failure Domains zugeordnet sein
- ein einzelner Relay-Ausfall soll nicht automatisch den gesamten Ingest abbrechen

Folgen für die Architektur:

- eine Session könnte mehr als einen Relay-Bezug erhalten
- es könnten zusätzliche Felder nötig werden, etwa:
  - `primary_relay_id`
  - `secondary_relay_id`
- alternativ wäre ein eigenes Ingest-Modell pro Session denkbar

Offene technische Fragen:

- welcher Ingest-Pfad ist primär?
- wo wird bei Ausfall oder Drift umgeschaltet?
- wo findet Deduplizierung statt?
- wie wird verhindert, dass beide Relays in derselben Failure Domain liegen?

Diese Betriebsoption ist mit der Zielarchitektur vereinbar, aber nicht Teil des ersten Implementierungsschnitts.

## Offene Fragen

Folgende Punkte bleiben bewusst für spätere Phasen offen:

- Reconnect-Semantik bei Relay-Ausfall
- Reassignment-Strategien für Worker
- genaue Modellierung von `draining`
- Regeln für Rollouts und Patch-Fenster
- Redundanzmodell für Dual-Ingest
