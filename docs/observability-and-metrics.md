# Observability and Metrics

## Zweck

Dieses Dokument beschreibt das Zielmodell für Observability im aktuellen Systempfad:

```text
Client
  -> session-control
  -> relay
  -> worker
```

Im Fokus stehen:

- Metriken für Last, Stabilität und Kapazitätsplanung
- Metriken als Grundlage für Skalierungsentscheidungen
- Fehler- und Zustandsbeobachtung
- Logging für Analyse und Incident Response
- ein Azure-nahes Betriebsmodell

Nicht betrachtet wird in diesem Dokument die Weiterverarbeitung hinter dem `worker` in nachgelagerte Backends.

## Zielbild

Die Observability-Schicht besteht aus drei Ebenen:

- **Metriken** für Last, Trends, Alerts und Skalierung
- **Logs** für Fehleranalyse, Abstürze und Ablaufrekonstruktion
- **optional Traces** für End-to-End-Debugging über mehrere Services

Für einen belastbaren ersten Betriebsstand sind Metriken und strukturierte Logs zwingend erforderlich. Tracing ist sinnvoll, aber nachrangig gegenüber den Basisbausteinen.

## Grundprinzip

Jeder eigene Service exponiert einen `/metrics`-Endpoint im Prometheus-Format:

- `session-control`
- `relay`
- `worker`

Prometheus scrapt diese Endpoints in festen Intervallen.

Zusätzlich werden Kubernetes- und Infrastrukturmetriken gesammelt, die nicht aus dem Servicecode selbst kommen:

- Pod-CPU
- Pod-Memory
- Pod-Restarts
- Node-CPU und Node-Memory
- DaemonSet- und Deployment-Zustand
- Netzwerk- und Clusterzustand

Die Trennung ist grundlegend:

- **App-Metriken** kommen aus dem Service selbst
- **Kubernetes- und Container-Metriken** kommen aus Kubernetes und der Cloud-Plattform

## Zielarchitektur in Azure

Für einen Azure-nahen Betrieb besteht die Zielarchitektur aus folgenden Komponenten:

- **Azure Monitor managed service for Prometheus** für Prometheus-Metriken
- **Azure Managed Grafana** für Dashboards
- **Azure Monitor Alerts** für Alarmierung
- **Container Insights / Log Analytics** für Container- und Kubernetes-Logs
- **AKS-Kubernetes-Metriken** für Cluster, Pods, Nodes und Node Pools

Der Datenfluss ist:

1. `session-control`, `relay` und `worker` exponieren `/metrics`.
2. Managed Prometheus in AKS scrapt diese Metriken.
3. Kubernetes- und Container-Metriken werden zusätzlich aus AKS gesammelt.
4. Grafana visualisiert die Daten.
5. Alerts werden aus Prometheus- oder Azure-Monitor-Regeln ausgelöst.
6. Logs werden zentral in Azure Monitor Logs / Log Analytics erfasst.

## Beobachtungsziele

Die Observability-Schicht muss mindestens folgende Fragen zuverlässig beantworten:

- Wie viele aktive Sessions laufen aktuell?
- Welche Komponente ist der Engpass?
- Wann wird zusätzliche Kapazität benötigt?
- Ist ein Relay oder Worker überlastet oder fehlerhaft?
- Kann `session-control` Sessions zuverlässig erzeugen und binden?
- Funktioniert Draining korrekt?
- Sind neue `warm`-Relays vorhanden, bevor alte Relays gedraint werden?

## Metrik-Kategorien

### Traffic und Last

Diese Metriken zeigen, wie viel Arbeit im System ankommt:

- Requests pro Sekunde auf `session-control`
- Session-Erstellungen pro Zeitfenster
- Bind-Anfragen an `relay`
- Ingest-Rate am `relay`
- Weiterleitungs- und Verarbeitungsrate am `worker`
- aktive Sessions pro Komponente

### Kapazität

Diese Metriken zeigen die Auslastung gegenüber bekannten Grenzen:

- `current_sessions` im Verhältnis zu `max_sessions` pro Relay
- aktive Sessions pro Worker
- CPU- und Memory-Auslastung pro Pod
- CPU- und Memory-Auslastung pro Node
- Anzahl verfügbarer `warm`-Relays und `warm`-Workers

### Qualität und Fehler

Diese Metriken zeigen die technische Qualität des Systems:

- Fehlerquoten pro Endpoint
- Bind-Fehler
- Redis-Fehler
- Timeouts
- Ingest-Fehler
- Weiterleitungsfehler vom Relay zum Worker
- Cleanup-Fehler

### Rollout- und Betriebszustand

Diese Metriken zeigen den Zustand von Rollouts, Draining und Clusterbetrieb:

- Anzahl `warm`, `full` und `draining` Relays
- Anzahl drainender Relays mit `current_sessions > 0`
- Anzahl drainender Relays mit `current_sessions == 0`
- Anzahl Pods im CrashLoop
- Node-NotReady-Ereignisse
- nicht erfüllte DaemonSet- oder Deployment-Replikate

## Metriken pro Service

### `session-control`

#### Rolle

`session-control` bildet die Control Plane für Session-Erstellung, Scheduling und Bind-Orchestrierung. Ein Ausfall oder eine Überlastung dieser Komponente verhindert den Aufbau neuer Sessions, auch wenn Relays und Workers selbst gesund sind.

#### Kernmetriken

- `http_requests_total`
  Zweck: Gesamtzahl eingehender Requests, idealerweise mit Labels wie `endpoint`, `method`, `status_code`

- `http_request_duration_seconds`
  Zweck: Latenz pro Endpoint, insbesondere für `POST /sessions`

- `session_create_requests_total`
  Zweck: Anzahl Session-Erstellungsversuche

- `session_create_success_total`
  Zweck: erfolgreich erzeugte Sessions

- `session_create_fail_total`
  Zweck: fehlgeschlagene Session-Erstellungen
  Labels: `reason=no_warm_relay|no_warm_worker|redis_error|relay_bind_failed|timeout`

- `assignment_duration_seconds`
  Zweck: Dauer der Relay-/Worker-Zuweisung

- `relay_bind_duration_seconds`
  Zweck: Dauer des internen Bind-Calls zum Relay

- `relay_bind_fail_total`
  Zweck: Bind-Fehler zum Relay

- `redis_operation_duration_seconds`
  Zweck: Redis-Latenz
  Labels: `operation=get|set|eval|expire`

- `redis_operation_fail_total`
  Zweck: Redis-Fehler

- `available_relays`
  Zweck: sichtbare Zahl verfügbarer `warm`-Relays

- `available_workers`
  Zweck: sichtbare Zahl verfügbarer `warm`-Workers

- `session_control_inflight_requests`
  Zweck: aktuelle Last am Service

#### Relevante Auswertungen

- hohe Request-Rate bei steigender Latenz
- steigende Fehlerquote bei Session-Erstellung
- `available_relays == 0`
- `available_workers == 0`
- steigende Redis-Latenz oder Redis-Fehlerrate

#### Skalierungssignale

Die Skalierung erfolgt pod-basiert. Geeignete Signale sind:

- CPU-Auslastung pro Pod
- Request-Rate
- P95-/P99-Latenz auf `POST /sessions`
- Inflight Requests

### `relay`

#### Rolle

Der Relay ist die öffentliche Medienkante und der wesentliche Kapazitätsanker für Sessions.

#### Kernmetriken

- `relay_active_sessions`
  Zweck: aktuell aktive Sessions auf diesem Relay

- `relay_max_sessions`
  Zweck: konfigurierte Kapazität

- `relay_capacity_ratio`
  Zweck: Verhältnis `active_sessions / max_sessions`

- `relay_bind_requests_total`
  Zweck: Anzahl Bind-Anfragen

- `relay_bind_success_total`
  Zweck: erfolgreiche Binds

- `relay_bind_fail_total`
  Zweck: fehlgeschlagene Binds
  Labels: `reason=capacity|invalid_session|worker_error|draining`

- `relay_ingest_requests_total`
  Zweck: Anzahl Ingest-Requests

- `relay_ingest_bytes_total`
  Zweck: empfangene Bytes

- `relay_ingest_fail_total`
  Zweck: Ingest-Fehler
  Labels: `reason=unknown_session|worker_upstream|internal_error`

- `relay_forward_duration_seconds`
  Zweck: Dauer der Weiterleitung zum Worker

- `relay_forward_fail_total`
  Zweck: Fehler bei der Weiterleitung zum Worker

- `relay_session_ttl_refresh_total`
  Zweck: erfolgreiche Session-TTL-Refreshes

- `relay_session_ttl_refresh_fail_total`
  Zweck: fehlgeschlagene TTL-Refreshes

- `relay_status_info`
  Zweck: Zustand des Relay
  Labels: `status=starting|warm|full|draining`

- `relay_draining`
  Zweck: Drain-Status als Gauge `0/1`

- `relay_cleanup_total`
  Zweck: Anzahl bereinigter Sessions

- `relay_cleanup_fail_total`
  Zweck: Cleanup-Fehler

- `relay_heartbeat_fail_total`
  Zweck: Fehler beim Persistieren des Relay-Status

#### Relevante Auswertungen

- wenige oder keine `warm`-Relays
- Relays mit hoher `relay_capacity_ratio`
- hohe Ingest-Fehlerrate
- hohe Upstream-Fehlerrate zum Worker
- `draining`-Relays, die ungewöhnlich lange nicht leer werden

#### Skalierungssignale

Relay-Skalierung erfolgt im Zielmodell nicht über zusätzliche Pods auf bestehenden Nodes, sondern über zusätzliche Media-Nodes. Relevante Signale sind:

- durchschnittliche `relay_capacity_ratio`
- Anzahl Relays über 70 bis 80 Prozent Auslastung
- Anzahl `warm`-Relays unter Mindestwert
- hohe Ingest- oder Verbindungsdichte pro Relay

### `worker`

#### Rolle

Workers bilden die interne Verarbeitungsinstanz hinter dem Relay. Fehler oder Überlastung in diesem Bereich beeinträchtigen die Sessionverarbeitung direkt.

#### Kernmetriken

- `worker_active_sessions`
  Zweck: aktuell aktive Sessions

- `worker_bind_requests_total`
  Zweck: Bind-Anfragen vom Relay

- `worker_bind_success_total`
  Zweck: erfolgreiche Binds

- `worker_bind_fail_total`
  Zweck: fehlgeschlagene Binds

- `worker_ingest_requests_total`
  Zweck: verarbeitete Ingest-Anfragen

- `worker_ingest_bytes_total`
  Zweck: verarbeitete Bytes

- `worker_ingest_duration_seconds`
  Zweck: Verarbeitungsdauer pro Ingest

- `worker_ingest_fail_total`
  Zweck: Verarbeitungsfehler

- `worker_cleanup_total`
  Zweck: bereinigte Sessions

- `worker_cleanup_fail_total`
  Zweck: Cleanup-Fehler

- `worker_status_info`
  Zweck: Worker-Zustand
  Labels: `status=warm|reserved|active|dead`

- `worker_heartbeat_fail_total`
  Zweck: Fehler beim Schreiben des Worker-Zustands

- `worker_assigned_session_stale_total`
  Zweck: erkannte stale Zustände oder Inkonsistenzen

#### Relevante Auswertungen

- steigende Worker-Fehlerrate
- steigende Worker-Bind-Fehlerrate
- wenige `warm`-Workers
- hohe CPU-Last einzelner Worker-Pods
- steigende Verarbeitungsdauer pro Ingest

#### Skalierungssignale

Worker-Skalierung erfolgt pod-basiert. Geeignete Signale sind:

- CPU-Auslastung
- `worker_active_sessions`
- Verarbeitungsdauer
- Anzahl `warm`-Workers unter Mindestwert

## Kubernetes- und Infrastrukturmetriken

Diese Metriken stammen nicht primär aus den Services selbst, sondern aus AKS, Kubernetes und Azure.

### Kubernetes-Ebene

- Pod-CPU und Pod-Memory
- Pod-Restarts
- OOMKills
- Pod-Ready / Pod-NotReady
- Deployment unavailable replicas
- DaemonSet unavailable number scheduled
- Node Ready / NotReady
- Node CPU / Memory / Disk Pressure
- Netzwerkverkehr pro Pod und Node

### Azure-Ebene

Für AKS in Azure sind zusätzlich folgende Infrastruktur-Signale relevant:

- Zustand und Größe der Node Pools
- VM Scale Set-Instanzen für Worker- und Media-Node-Pools
- fehlgeschlagene Scale-Out- oder Provisioning-Vorgänge
- Node-Provisioning-Dauer
- öffentliche IP-Zuweisung für Media-Nodes
- Netzwerkbandbreite und Paketverluste auf Node-Ebene
- Ingress- und Load-Balancer-Metriken vor `session-control`
- Log-Ingestion-Gesundheit

Besonders relevant für dieses Architekturmodell sind:

- rechtzeitige Bereitstellung neuer Media-Nodes
- korrekte öffentliche Erreichbarkeit neuer Media-Nodes
- ausreichende freie Media-Node-Kapazität vor Beginn eines Draining-Vorgangs

## Skalierungsstrategie

### `session-control`

- pod-basiert skalieren
- Trigger: CPU, Request-Rate, P95-Latenz, Inflight Requests

### `worker`

- pod-basiert skalieren
- Trigger: CPU, aktive Sessions, Verarbeitungsdauer, Anzahl warmer Workers

### `relay`

- node-basiert skalieren
- Trigger: Relay-Auslastung, Anzahl `warm`-Relays, Anzahl stark ausgelasteter Relays

Die grundlegende Trennung lautet:

- `session-control` und `worker` skalieren als Workloads
- `relay` skaliert über zusätzliche Media-Nodes

## Alerts

Für einen ersten produktionsnahen Stand sind folgende Alarme sinnvoll:

### Kritisch

- `available_relays == 0`
- `available_workers == 0`
- Session-Erstellungsfehlerquote über Schwellwert
- Redis nicht erreichbar
- Relay-Bind-Fehlerquote stark erhöht
- Worker-Ingest-Fehlerquote stark erhöht
- `draining`-Relay bleibt zu lange mit Sessions belegt
- Node Pool kann nicht hochskalieren

### Warnung

- Relay-Auslastung dauerhaft über 70 Prozent
- wenig `warm`-Relays verfügbar
- wenig `warm`-Workers verfügbar
- erhöhte Latenz auf `POST /sessions`
- steigende Pod-Restarts
- einzelne Nodes laufen in Ressourcenengpässe

## Logging

Neben Metriken sind zentrale Logs erforderlich.

### Ziel

Metriken zeigen das Vorhandensein eines Problems. Logs liefern die Ursache und den konkreten Ablauf.

### Logging-Regeln

Die Services schreiben strukturierte Logs mit mindestens folgenden Feldern:

- `timestamp`
- `level`
- `service`
- `session_id`
- `relay_id`
- `worker_id`
- `request_id` oder `trace_id`
- `event_type`
- `error_code`
- `message`

### Typische Log-Ereignisse

Für `session-control`:

- Session-Erstellung gestartet
- Session-Erstellung erfolgreich
- Assignment fehlgeschlagen
- Relay-Bind fehlgeschlagen
- Redis-Fehler

Für `relay`:

- Relay startet
- Relay wird `warm`
- Relay wird `draining`
- Session wird gebunden
- Ingest auf unbekannte Session
- Weiterleitung zum Worker fehlgeschlagen
- Session-Cleanup

Für `worker`:

- Worker startet
- Worker wird `warm`
- Worker-Bind erfolgreich / fehlgeschlagen
- Ingest-Verarbeitung fehlgeschlagen
- Cleanup

### Logging in Azure

Für einen Azure-nahen Betrieb werden Logs zentral in Azure Monitor Logs / Log Analytics gesammelt.

Ziele:

- clusterweite Suche
- Korrelation zwischen Services
- Alerts auf Log-Mustern
- nachvollziehbare Incident-Analyse

## Tracing

Tracing ist nicht zwingend für den ersten Ausbauschritt, erhöht aber die Analysefähigkeit deutlich.

Sinnvoll sind:

- ein gemeinsamer `trace_id` oder `request_id`
- Weitergabe dieser IDs von `session-control` an `relay` und `worker`
- später OpenTelemetry als Standardisierungsschicht

Damit lassen sich einzelne Abläufe wie `POST /sessions` oder fehlerhafte Bind-Pfade serviceübergreifend nachvollziehen.

## Empfohlene Implementierungsreihenfolge

### Phase 1

- `/metrics` in allen drei Services
- Basis-Dashboards
- zentrale Logs
- kritische Alerts

### Phase 2

- Skalierungssignale und Schwellenwerte verfeinern
- Relay-Auslastung sauber in Node-Skalierung übersetzen
- Rollout- und Draining-Metriken ergänzen

### Phase 3

- Tracing
- SLOs und Error Budgets
- langfristige Kapazitätsmodelle

## Minimum für einen belastbaren ersten Stand

Mindestens erforderlich sind:

- `session-control`: Request-Rate, Latenz, Session-Erfolge, Session-Fehler, Redis-Fehler
- `relay`: aktive Sessions, Auslastung, Bind-Fehler, Ingest-Fehler, Drain-Status
- `worker`: aktive Sessions, CPU, Verarbeitungsdauer, Ingest-Fehler
- Kubernetes: Pod-CPU, Memory, Restarts, Node-Status
- Azure: Node-Pool- und Scale-Out-Zustand, Ingress-Metriken für `session-control`, zentrale Log-Sammlung

## Zusammenfassung

Die grundlegenden Designentscheidungen lauten:

- alle eigenen Services exponieren fachliche Metriken selbst
- Kubernetes und Azure liefern die Infrastrukturmetriken
- `session-control` und `worker` werden pod-basiert beobachtet und skaliert
- `relay` wird als Media-Node-Kapazität beobachtet und über zusätzliche Nodes skaliert
- Logs ergänzen die Metriken um die Fehlerursache

Damit bleibt die Observability-Schicht exakt auf die bestehende Architektur ausgerichtet und folgt nicht einem generischen Web-Backend-Modell.

## Verwandte Dokumente

- [architecture.md](architecture.md)
- [runtime-lifecycle.md](runtime-lifecycle.md)
- [relay-scaling-and-draining.md](relay-scaling-and-draining.md)
- [../README.md](../README.md)
