# Runtime Lifecycle

## Zweck

Dieses Dokument beschreibt das Laufzeitverhalten des Systems:

- was heute bereits implementiert ist
- welche Zustände und TTLs aktuell gelten
- wie Cleanup und Fehlerbehandlung funktionieren
- wie Draining, Rolling Updates und Failover später sauber ergänzt werden sollen

Es ergänzt die Zielarchitektur aus [architecture.md](architecture.md) um das betriebliche Verhalten.

## Aktuell implementierter Runtime-Pfad

### 1. Relay-Startup

Beim Start:

- lädt der Relay seine Konfiguration
- registriert sich in Redis
- setzt Heartbeats auf
- veröffentlicht Kapazität und Verfügbarkeit

Aktuelle Relay-Status:

- `starting`
- `warm`
- `full`

Der Relay bleibt solange `warm`, wie freie Kapazität vorhanden ist. Sobald `current_sessions >= max_sessions` erreicht ist, wird der Status `full`.

### 2. Worker-Startup

Beim Start:

- registriert sich der Worker in Redis
- veröffentlicht `worker_id`, `endpoint`, `status`, `last_heartbeat`
- startet Heartbeats

Aktuelle Worker-Status im Runtime-Pfad:

- `warm`
- `reserved`
- `active`

Der aktuelle Weg ist:

```text
warm -> reserved -> active -> warm
```

### 3. Session-Erstellung

`session-control` nimmt `POST /sessions` an und führt in dieser Reihenfolge aus:

1. atomare Reservierung von Relay und Worker
2. Schreiben des Session-Records mit initialer TTL
3. Bind-Aufruf an den zugewiesenen Relay
4. Persistenz des Session-Status als `connecting`

### 4. Bind zwischen Relay und Worker

Nach erfolgreicher Relay-Bindung:

- markiert der Relay den zugewiesenen Worker als `active`
- bindet die Session auf dem Worker
- speichert die Session im lokalen Relay-Zustand

### 5. Laufender Ingest

Während Ingest ankommt:

- nimmt der Relay Payload für `session_id` an
- leitet sie an den gebundenen Worker weiter
- erhöht eigene ingest-bezogene Zähler
- erneuert die Session-TTL in Intervallen
- schreibt `session-media-relay:{session_id}`

Parallel dazu:

- erhöht der Worker seine sessionbezogenen Paket- und Bytezähler
- schreibt `session-media-worker:{session_id}`

### 6. Session-Ende durch Ingest-Stille

Der aktuelle Ownership-Mechanismus ist:

- `session-control` erzeugt die Session mit einer initialen TTL
- der Relay erneuert diese TTL nur solange, wie für die Session tatsächlich Ingest eingeht
- wenn Ingest endet, hört auch die TTL-Erneuerung auf
- die Session läuft aus

Das ist aktuell bewusst so modelliert. Der Relay besitzt die Session-Liveness, nicht das Dashboard, nicht der Worker und nicht `session-control`.

### 7. Cleanup

Nach Session-Ablauf räumen zwei Stellen auf:

#### Relay-Cleanup

Der Relay prüft in seinem Heartbeat-Loop:

- existiert `session:{session_id}` noch?

Wenn nicht:

- persistiert er letzte Relay-Media-Statistiken
- gibt den Worker wieder frei
- entfernt die Session aus dem lokalen Relay-Zustand

#### Worker-Cleanup

Der Worker prüft in seinem Heartbeat-Loop:

- existiert die dem Worker zugewiesene Session noch?

Wenn nicht:

- persistiert er letzte Worker-Media-Statistiken
- entfernt den internen Sessionzustand
- setzt sich wieder auf `warm`

Diese doppelte Cleanup-Strategie ist absichtlich defensiv.

## Aktuelle Runtime-Invarianten

Folgende Regeln gelten im aktuellen Stand:

- Clients sprechen nicht direkt mit Workers.
- Session-Liveness wird nur durch aktiven Relay-Ingest verlängert.
- Redis bleibt Quelle der Wahrheit für Session-, Relay- und Worker-Zustände.
- Der kritische Reservierungspfad ist atomar in Redis modelliert.
- Ein Worker aus `workers:warm` muss real existieren und tatsächlich `warm` sein.

Die letzte Regel ist wichtig, weil stale Worker im Warm-Set früher falsche Assignment-Fehler ausgelöst haben. Der aktuelle Lua-Pfad zieht deshalb so lange Kandidaten aus `workers:warm`, bis ein gültiger `warm`-Worker gefunden ist oder das Set leer ist.

## Aktuelle TTL- und Heartbeat-Semantik

### Session-TTL

- Standardmäßig kurzlebig
- initial von `session-control` gesetzt
- später vom Relay-Ingest erneuert

### Relay-TTL

- Relay publiziert seinen Zustand mit TTL
- Heartbeats halten den Relay-Record aktuell

### Worker-TTL

- Worker publiziert seinen Zustand mit TTL
- Heartbeats halten den Worker-Record aktuell

### Media-Stat-Keys

- `session-media-relay:{session_id}`
- `session-media-worker:{session_id}`

Diese Keys leben bewusst etwas länger als die reine Session-TTL, damit die letzten ingestbezogenen Zahlen nach dem Session-Ende noch beobachtbar bleiben.

## Aktuelle Fehlerbehandlung

### Kein verfügbarer Relay

`session-control` liefert:

- `503 No warm relays available`

### Kein verfügbarer Worker

`session-control` liefert:

- `503 No warm workers available`

### Stale Worker im Warm-Set

Aktuelle Behandlung:

- der Lua-Assignment-Pfad überspringt fehlende oder nicht mehr warme Worker
- erst wenn kein gültiger Kandidat mehr übrig ist, wird `NO_WARM_WORKER` zurückgegeben

### Relay-Bind schlägt fehl

Aktuelle Behandlung:

- `session-control` löscht den Session-Record wieder
- reservierte Ressourcen werden freigegeben
- der Request schlägt mit einem Bind-Fehler fehl

### Ingest auf unbekannte Session

Aktuelle Behandlung:

- Relay antwortet mit `404`

### Worker-Upstream schlägt beim Ingest fehl

Aktuelle Behandlung:

- Relay antwortet mit `502`

Das ist wichtig, weil ein interner Upstream-Fehler nicht als `404` maskiert werden darf.

## Aktuelles Betriebsmodell für Updates

Im aktuellen implementierten Stand gibt es noch kein echtes `draining`.

Das bedeutet:

- Relays kennen aktuell kein produktives Draining-Verhalten
- Worker kennen aktuell kein produktives Draining-Verhalten
- Rolling Updates können aktive Sessions unterbrechen

Das ist eine bekannte Lücke des Zwischenstands.

## Zielmodell für Draining und Rolling Updates

### Relay-Draining

Das Zielverhalten für einen geplanten Rollout ist:

- Relay setzt sich auf `draining`
- neue Sessions werden ihm nicht mehr zugewiesen
- bestehende Sessions dürfen zu Ende laufen
- danach kann der Relay sauber beendet werden

### Worker-Draining

Das Zielverhalten für Worker ist:

- Worker setzt sich auf `draining`
- neue Sessions werden nicht mehr reserviert
- eine bereits laufende Session läuft kontrolliert aus

### Scheduling-Regel

Sobald `draining` implementiert ist, müssen diese Regeln gelten:

- `draining`-Relays dürfen keine neuen Sessions annehmen
- `draining`-Worker dürfen nicht neu reserviert werden

## Recovery statt Handover

Redis-basierter Zustand ist gut für:

- Erkennung
- Entscheidung
- Aufräumen
- Reassignment

Redis alleine reicht aber nicht für:

- nahtloses Übernehmen einer laufenden RTC-Verbindung
- transparentes Migrieren von ICE-, DTLS- oder SRTP-Kontexten

Das Zielmodell ist deshalb bewusst:

- Recovery statt magischem Live-Handover

### Relay-Ausfall

Wenn ein Relay ausfällt:

- sein Heartbeat läuft aus
- er darf nicht mehr neu schedulbar sein
- bestehende Sessions gelten als kritisch oder fehlgeschlagen

### Worker-Ausfall

Wenn ein Worker ausfällt:

- sein Heartbeat läuft aus
- die Session verliert ihren internen Verarbeitungs-Pfad
- die korrekte Reaktion ist Fehlerbehandlung oder spätere Neuzuordnung, nicht implizites Handover

## Zielmodell für Failover

Der langfristige nächste Laufzeitblock ist Dual-Ingest mit Primary-/Secondary-Pfad.

Zielbild:

- eine Session hat zwei Relays
- eine Session hat zwei Worker
- beide Relays können bereits Ingest sehen
- nur ein Worker verarbeitet aktiv

### Bevorzugte Rollen

- `primary_relay`
- `secondary_relay`
- `primary_worker`
- `secondary_worker`
- `active_relay`
- `active_worker`

### Zielzustände einer Session

- `primary_active`
- `primary_critical`
- `secondary_promoted`
- `failed`

### Zielverhalten

Solange der Primärpfad gesund ist:

- bleibt er aktiver TTL-Owner
- der Primärworker verarbeitet aktiv
- der Sekundärpfad bleibt Hot Standby

Wenn der Primärpfad kritisch wird:

- muss vor Ablauf der Session entschieden werden, ob der Secondary übernehmen kann
- Promotion muss explizit und deterministisch passieren

Wenn kein übernahmefähiger Secondary vorhanden ist:

- wird die Session kontrolliert als Fehlerfall behandelt

## Was aktuell bewusst noch fehlt

Der aktuelle Repository-Stand implementiert noch nicht:

- `draining`
- graceful shutdown für aktive Sessions
- Promotion zwischen Primary und Secondary
- Watchdog-Logik für `failover_threshold`
- Rückpromotion
- RTC-spezifische Reconnect-Semantik

## Operative Beobachtbarkeit

Für den aktuellen Stand sind diese Signale entscheidend:

- Relay-Heartbeat aktuell oder abgelaufen
- Worker-Heartbeat aktuell oder abgelaufen
- Session-TTL wächst während Ingest oder läuft aus
- `relays:available` und `workers:warm` bleiben konsistent
- `session-media-relay:*` und `session-media-worker:*` entwickeln sich plausibel

## Verwandte Dokumente

- [architecture.md](architecture.md)
- [kubernetes.md](kubernetes.md)
- [../README.md](../README.md)
- [relay-scaling-and-draining.md](relay-scaling-and-draining.md)
- [observability-and-metrics.md](observability-and-metrics.md)
