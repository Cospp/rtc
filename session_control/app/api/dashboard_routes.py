import json
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from shared.models.relay import RelayRecord
from shared.models.worker import WorkerRecord
from session_control.app.redis.redis_client import get_redis

router = APIRouter(tags=["dashboard"])


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_json_loads(raw: str | None) -> dict:
    if raw is None:
        return {}
    return json.loads(raw)


async def _scan_keys(redis_client, pattern: str) -> list[str]:
    keys = [key async for key in redis_client.scan_iter(match=pattern)]
    keys.sort()
    return keys


async def _mget_map(redis_client, keys: list[str]) -> dict[str, str]:
    if not keys:
        return {}

    values = await redis_client.mget(keys)
    return {
        key: value
        for key, value in zip(keys, values, strict=False)
        if value is not None
    }


async def _ttl_map(redis_client, keys: list[str]) -> dict[str, int]:
    if not keys:
        return {}

    pipeline = redis_client.pipeline()
    for key in keys:
        pipeline.ttl(key)
    ttl_values = await pipeline.execute()
    return {
        key: int(ttl)
        for key, ttl in zip(keys, ttl_values, strict=False)
    }


async def _load_dashboard_state() -> dict:
    redis_client = await get_redis()

    redis_info = await redis_client.info()
    db0_keyspace = redis_info.get("db0", {})

    if isinstance(db0_keyspace, str):
        db0_keyspace_summary = db0_keyspace
    else:
        db0_keyspace_summary = {
            "keys": db0_keyspace.get("keys", 0),
            "expires": db0_keyspace.get("expires", 0),
            "avg_ttl": db0_keyspace.get("avg_ttl", 0),
        }

    relay_keys = await _scan_keys(redis_client, "relay:*")
    relay_media_keys = await _scan_keys(redis_client, "session-media-relay:*")
    worker_keys = await _scan_keys(redis_client, "worker:*")
    worker_media_keys = await _scan_keys(redis_client, "session-media-worker:*")
    session_keys = await _scan_keys(redis_client, "session:*")

    relay_payloads = await _mget_map(redis_client, relay_keys)
    relay_ttls = await _ttl_map(redis_client, list(relay_payloads))
    worker_payloads = await _mget_map(redis_client, worker_keys)
    worker_ttls = await _ttl_map(redis_client, list(worker_payloads))
    relay_media_payloads = await _mget_map(redis_client, relay_media_keys)
    worker_media_payloads = await _mget_map(redis_client, worker_media_keys)
    session_payloads = await _mget_map(redis_client, session_keys)
    session_ttls = await _ttl_map(redis_client, list(session_payloads))

    relay_records: list[dict] = []
    for relay_key, relay_raw in relay_payloads.items():
        relay = RelayRecord.model_validate_json(relay_raw)
        relay_records.append(
            {
                "relay_id": relay.relay_id,
                "status": relay.status.value,
                "public_endpoint": relay.public_endpoint,
                "internal_endpoint": relay.internal_endpoint,
                "last_heartbeat": relay.last_heartbeat,
                "current_sessions": relay.current_sessions,
                "max_sessions": relay.max_sessions,
                "ttl_seconds": relay_ttls.get(relay_key, -2),
            }
        )

    worker_records: list[dict] = []
    for worker_key, worker_raw in worker_payloads.items():
        worker = WorkerRecord.model_validate_json(worker_raw)
        worker_records.append(
            {
                "worker_id": worker.worker_id,
                "status": worker.status.value,
                "endpoint": worker.endpoint,
                "last_heartbeat": worker.last_heartbeat,
                "assigned_session_id": worker.assigned_session_id,
                "ttl_seconds": worker_ttls.get(worker_key, -2),
            }
        )

    relay_media_stats: dict[str, dict] = {}
    for media_raw in relay_media_payloads.values():
        media = _safe_json_loads(media_raw)
        session_id = media.get("session_id")
        if session_id:
            relay_media_stats[session_id] = media

    worker_media_stats: dict[str, dict] = {}
    for media_raw in worker_media_payloads.values():
        media = _safe_json_loads(media_raw)
        session_id = media.get("session_id")
        if session_id:
            worker_media_stats[session_id] = media

    session_records: list[dict] = []
    for session_key, session_raw in session_payloads.items():
        session = json.loads(session_raw)
        session["ttl_seconds"] = session_ttls.get(session_key, -2)
        relay_media = relay_media_stats.get(session["session_id"], {})
        worker_media = worker_media_stats.get(session["session_id"], {})
        session["relay_media"] = relay_media
        session["worker_media"] = worker_media
        session["relay_bytes"] = int(relay_media.get("total_bytes", 0) or 0)
        session["relay_packets"] = int(relay_media.get("total_packets", 0) or 0)
        session["worker_bytes"] = int(worker_media.get("total_bytes", 0) or 0)
        session["worker_packets"] = int(worker_media.get("total_packets", 0) or 0)
        session_records.append(session)

    sessions_by_relay: dict[str, list[dict]] = {}
    sessions_by_worker: dict[str, dict] = {}
    for session in session_records:
        relay_id = session.get("relay_id")
        worker_id = session.get("worker_id")

        if relay_id:
            sessions_by_relay.setdefault(relay_id, []).append(session)

        if worker_id:
            sessions_by_worker[worker_id] = session

    for relay in relay_records:
        relay_sessions = sorted(
            sessions_by_relay.get(relay["relay_id"], []),
            key=lambda item: item["session_id"],
        )
        relay["sessions"] = [
            {
                "session_id": session["session_id"],
                "worker_id": session.get("worker_id") or "-",
                "client_id": session.get("client_id") or "-",
                "status": session.get("status") or "-",
                "relay_bytes": session.get("relay_bytes", 0),
                "worker_bytes": session.get("worker_bytes", 0),
            }
            for session in relay_sessions
        ]

    for worker in worker_records:
        session = sessions_by_worker.get(worker["worker_id"])
        worker["relay_id"] = session.get("relay_id") if session else None
        worker["media_bytes"] = session.get("worker_bytes", 0) if session else 0
        worker["media_packets"] = session.get("worker_packets", 0) if session else 0
        worker["relay_received_bytes"] = session.get("relay_bytes", 0) if session else 0
        worker["relay_received_packets"] = (
            session.get("relay_packets", 0) if session else 0
        )

    relay_records.sort(key=lambda relay: relay["relay_id"])
    worker_records.sort(key=lambda worker: worker["worker_id"])
    session_records.sort(key=lambda session: session["session_id"])

    warm_relays = [relay for relay in relay_records if relay["status"] == "warm"]
    full_relays = [relay for relay in relay_records if relay["status"] == "full"]
    other_relays = [
        relay for relay in relay_records if relay["status"] not in {"warm", "full"}
    ]

    warm_workers = [worker for worker in worker_records if worker["status"] == "warm"]
    reserved_workers = [
        worker for worker in worker_records if worker["status"] == "reserved"
    ]
    busy_workers = [
        worker for worker in worker_records if worker["status"] in {"reserved", "active"}
    ]
    dead_workers = [worker for worker in worker_records if worker["status"] == "dead"]
    drift_workers = [
        worker
        for worker in worker_records
        if worker["status"] not in {"warm", "reserved", "active", "dead"}
    ]
    other_workers = [
        worker
        for worker in worker_records
        if worker["status"] not in {"warm", "reserved"}
    ]
    live_workers = [worker for worker in worker_records if worker["status"] != "dead"]

    relay_capacity_total = sum(relay["max_sessions"] for relay in relay_records)
    relay_capacity_used = sum(relay["current_sessions"] for relay in relay_records)
    relay_media_total_bytes = sum(
        int(session.get("relay_bytes", 0) or 0) for session in session_records
    )
    worker_media_total_bytes = sum(
        int(session.get("worker_bytes", 0) or 0) for session in session_records
    )

    return {
        "updated_at": _utc_now_iso(),
        "summary": {
            "relay_total": len(relay_records),
            "relay_warm_total": len(warm_relays),
            "relay_full_total": len(full_relays),
            "relay_other_total": len(other_relays),
            "relay_capacity_total": relay_capacity_total,
            "relay_capacity_used": relay_capacity_used,
            "worker_record_total": len(worker_records),
            "worker_live_total": len(live_workers),
            "worker_total": len(worker_records),
            "warm_total": len(warm_workers),
            "reserved_total": len(reserved_workers),
            "busy_total": len(busy_workers),
            "dead_total": len(dead_workers),
            "drift_total": len(drift_workers),
            "other_total": len(other_workers),
            "session_total": len(session_records),
            "relay_media_total_bytes": relay_media_total_bytes,
            "worker_media_total_bytes": worker_media_total_bytes,
        },
        "redis": {
            "status": "ok",
            "version": redis_info.get("redis_version", "-"),
            "uptime_seconds": redis_info.get("uptime_in_seconds", 0),
            "connected_clients": redis_info.get("connected_clients", 0),
            "used_memory_human": redis_info.get("used_memory_human", "-"),
            "peak_memory_human": redis_info.get("used_memory_peak_human", "-"),
            "db0": db0_keyspace_summary,
            "expired_keys": redis_info.get("expired_keys", 0),
            "evicted_keys": redis_info.get("evicted_keys", 0),
            "keyspace_hits": redis_info.get("keyspace_hits", 0),
            "keyspace_misses": redis_info.get("keyspace_misses", 0),
        },
        "relays": relay_records,
        "warm_relays": warm_relays,
        "full_relays": full_relays,
        "other_relays": other_relays,
        "warm_workers": warm_workers,
        "reserved_workers": reserved_workers,
        "busy_workers": busy_workers,
        "dead_workers": dead_workers,
        "drift_workers": drift_workers,
        "other_workers": other_workers,
        "sessions": session_records,
    }


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard() -> str:
    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>RTC Dashboard</title>
  <style>
    :root {
      --bg: #07111f;
      --bg-accent: #0f2238;
      --panel: rgba(10, 24, 42, 0.88);
      --line: rgba(126, 167, 214, 0.16);
      --text: #eaf3ff;
      --muted: #8ba6c7;
      --accent: #6cd3ff;
      --teal: #2bd2b3;
      --yellow: #f5d66d;
      --orange: #ff9f5a;
      --red: #ff6b7a;
      --blue: #7ab8ff;
      --violet: #9b8cff;
      --shadow: 0 18px 44px rgba(0, 0, 0, 0.34);
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      font-family: "Segoe UI", Tahoma, sans-serif;
      background:
        radial-gradient(circle at top right, rgba(108, 211, 255, 0.16), transparent 24%),
        radial-gradient(circle at bottom left, rgba(43, 210, 179, 0.12), transparent 28%),
        linear-gradient(160deg, #040b16 0%, #07111f 36%, #0a1930 100%);
      color: var(--text);
      overflow: hidden;
    }

    .page {
      height: 100vh;
      padding: 14px;
      display: grid;
      grid-template-rows: auto 1fr;
      gap: 12px;
    }

    .hero {
      display: grid;
      grid-template-columns: minmax(220px, 1.05fr) repeat(8, minmax(84px, 0.92fr));
      grid-auto-rows: minmax(74px, auto);
      gap: 8px;
    }

    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 10px 12px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(10px);
      min-height: 0;
    }

    .hero-main {
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      background: linear-gradient(145deg, rgba(14, 34, 58, 0.98), rgba(8, 20, 36, 0.96));
      border-color: rgba(108, 211, 255, 0.18);
    }

    .eyebrow {
      font-size: 11px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--accent);
      opacity: 0.9;
    }

    .title {
      margin: 2px 0 0;
      font-size: 20px;
      font-weight: 700;
    }

    .subtitle {
      margin: 4px 0 0;
      font-size: 11px;
      color: var(--muted);
    }

    .stat-label {
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: 0.11em;
      color: var(--muted);
      line-height: 1.25;
    }

    .stat-value {
      margin-top: 6px;
      font-size: clamp(18px, 1.35vw, 24px);
      font-weight: 700;
      line-height: 1;
      word-break: break-word;
    }

    .stat-detail {
      margin-top: 6px;
      font-size: 9px;
      color: var(--muted);
    }

    .layout {
      min-height: 0;
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      grid-template-rows: repeat(2, minmax(0, 1fr));
      grid-auto-rows: minmax(0, 1fr);
      gap: 12px;
    }

    .column-title {
      margin: 0 0 6px;
      font-size: 15px;
      font-weight: 700;
    }

    .column-subtitle {
      margin: 0 0 10px;
      font-size: 11px;
      color: var(--muted);
    }

    .list {
      height: calc(100% - 44px);
      overflow: auto;
      display: flex;
      flex-direction: column;
      gap: 8px;
      padding-right: 4px;
    }

    .list::-webkit-scrollbar {
      width: 7px;
    }

    .list::-webkit-scrollbar-thumb {
      background: rgba(122, 184, 255, 0.24);
      border-radius: 999px;
    }

    .card {
      border-radius: 14px;
      padding: 10px 11px;
      border: 1px solid rgba(255, 255, 255, 0.05);
      background: rgba(255, 255, 255, 0.03);
    }

    .warm-card {
      background: linear-gradient(135deg, rgba(43, 210, 179, 0.18), rgba(43, 210, 179, 0.08));
    }

    .busy-card {
      background: linear-gradient(135deg, rgba(122, 184, 255, 0.18), rgba(122, 184, 255, 0.08));
    }

    .danger-card {
      background: linear-gradient(135deg, rgba(255, 107, 122, 0.18), rgba(255, 107, 122, 0.08));
    }

    .session-card {
      background: linear-gradient(135deg, rgba(155, 140, 255, 0.18), rgba(155, 140, 255, 0.08));
    }

    .redis-card {
      background: linear-gradient(135deg, rgba(108, 211, 255, 0.16), rgba(43, 210, 179, 0.08));
    }

    .relay-healthy {
      background: linear-gradient(135deg, rgba(43, 210, 179, 0.18), rgba(43, 210, 179, 0.08));
    }

    .relay-warning {
      background: linear-gradient(135deg, rgba(245, 214, 109, 0.2), rgba(245, 214, 109, 0.08));
    }

    .relay-hot {
      background: linear-gradient(135deg, rgba(255, 159, 90, 0.22), rgba(255, 159, 90, 0.09));
    }

    .relay-full {
      background: linear-gradient(135deg, rgba(255, 107, 122, 0.22), rgba(255, 107, 122, 0.09));
    }

    .card-head {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 12px;
    }

    .card-title {
      font-weight: 700;
      font-size: 13px;
    }

    .badge {
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      background: rgba(255, 255, 255, 0.08);
      color: var(--text);
    }

    .card-meta {
      margin-top: 6px;
      display: grid;
      gap: 3px;
      font-size: 11px;
      color: #c5d8ef;
    }

    .relay-card details {
      margin-top: 8px;
    }

    .relay-card summary {
      cursor: pointer;
      font-size: 11px;
      font-weight: 700;
      color: var(--accent);
      list-style: none;
    }

    .relay-card summary::-webkit-details-marker {
      display: none;
    }

    .relay-card summary::before {
      content: '+ ';
    }

    .relay-card details[open] summary::before {
      content: '- ';
    }

    .relay-session-list {
      margin-top: 8px;
      display: grid;
      gap: 6px;
    }

    .relay-session {
      border-radius: 10px;
      padding: 7px 8px;
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.06);
      font-size: 11px;
      color: #d8e8fb;
    }

    .metric-grid {
      display: grid;
      gap: 8px;
    }

    .metric-bar {
      display: grid;
      gap: 6px;
    }

    .metric-bar-head {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      font-size: 11px;
      color: var(--muted);
    }

    .metric-bar-track {
      height: 9px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.06);
      overflow: hidden;
      border: 1px solid rgba(255, 255, 255, 0.04);
    }

    .metric-bar-fill {
      height: 100%;
      border-radius: 999px;
      background: linear-gradient(90deg, var(--accent), var(--teal));
    }

    .metric-bar-fill.warn {
      background: linear-gradient(90deg, var(--yellow), var(--orange));
    }

    .metric-bar-fill.danger {
      background: linear-gradient(90deg, var(--orange), var(--red));
    }

    .empty {
      display: grid;
      place-items: center;
      height: 100%;
      min-height: 96px;
      text-align: center;
      color: var(--muted);
      border: 1px dashed var(--line);
      border-radius: 14px;
      background: rgba(255, 255, 255, 0.03);
      padding: 10px;
    }

    @media (max-width: 1280px) {
      .hero {
        grid-template-columns: repeat(4, minmax(0, 1fr));
        grid-auto-rows: minmax(76px, auto);
      }

      .hero-main {
        grid-column: 1 / -1;
      }

      .layout {
        grid-template-columns: 1fr 1fr;
        grid-template-rows: repeat(3, minmax(0, 1fr));
      }
    }

    @media (max-width: 860px) {
      .page {
        grid-template-rows: auto 1fr;
      }

      .hero {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .layout {
        grid-template-columns: 1fr;
        grid-template-rows: none;
        grid-auto-rows: minmax(220px, auto);
      }

      .stat-value {
        font-size: 22px;
      }
    }
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <article class="panel hero-main">
        <div>
          <div class="eyebrow">RTC Control Plane</div>
          <h1 class="title">Relay Fleet Console</h1>
        </div>
        <div class="subtitle">Last update: <span id="updated-at">-</span></div>
      </article>
      <article class="panel">
        <div class="stat-label">Relay Capacity</div>
        <div id="relay-total" class="stat-value">0</div>
        <div id="relay-capacity-detail" class="stat-detail">0 / 0 sessions in use</div>
      </article>
      <article class="panel">
        <div class="stat-label">Relay Warm</div>
        <div id="relay-warm-total" class="stat-value">0</div>
      </article>
      <article class="panel">
        <div class="stat-label">Relay Full</div>
        <div id="relay-full-total" class="stat-value">0</div>
      </article>
      <article class="panel">
        <div class="stat-label">Workers Live</div>
        <div id="worker-total" class="stat-value">0</div>
        <div id="worker-record-detail" class="stat-detail">0 records tracked</div>
      </article>
      <article class="panel">
        <div class="stat-label">Workers Warm</div>
        <div id="warm-total" class="stat-value">0</div>
      </article>
      <article class="panel">
        <div class="stat-label">Workers Busy</div>
        <div id="busy-total" class="stat-value">0</div>
      </article>
      <article class="panel">
        <div class="stat-label">Dead Records</div>
        <div id="dead-total" class="stat-value">0</div>
      </article>
      <article class="panel">
        <div class="stat-label">Sessions</div>
        <div id="session-total" class="stat-value">0</div>
      </article>
    </section>

    <section class="layout">
      <article class="panel">
        <h2 class="column-title">Relay Fleet</h2>
        <p class="column-subtitle">Routing targets with expandable relay to session to worker bindings.</p>
        <div id="relays" class="list"></div>
      </article>

      <article class="panel">
        <h2 class="column-title">Busy Workers</h2>
        <p class="column-subtitle">Workers currently assigned to a relay and session.</p>
        <div id="busy-workers" class="list"></div>
      </article>

      <article class="panel">
        <h2 class="column-title">Warm Workers</h2>
        <p class="column-subtitle">Immediately schedulable workers outside active media flows.</p>
        <div id="warm-workers" class="list"></div>
      </article>

      <article class="panel">
        <h2 class="column-title">Dead Or Drift Workers</h2>
        <p class="column-subtitle">Dead records remain visible until TTL expiry. Drift captures unexpected states.</p>
        <div id="dead-workers" class="list"></div>
      </article>

      <article class="panel">
        <h2 class="column-title">Sessions</h2>
        <p class="column-subtitle">The control-plane truth of client, relay, worker, and TTL ownership.</p>
        <div id="sessions" class="list"></div>
      </article>

      <article class="panel">
        <h2 class="column-title">Redis Pulse</h2>
        <p class="column-subtitle">Coordination-store memory, churn and lookup efficiency at a glance.</p>
        <div id="redis" class="list"></div>
      </article>
    </section>
  </div>

  <script>
    const openRelayIds = new Set();
    let refreshInFlight = false;

    function escapeHtml(value) {
      return String(value)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
    }

    function formatBytes(value) {
      const bytes = Number(value || 0);
      if (!Number.isFinite(bytes) || bytes <= 0) {
        return '0 B';
      }

      const units = ['B', 'KB', 'MB', 'GB'];
      let size = bytes;
      let unitIndex = 0;
      while (size >= 1024 && unitIndex < units.length - 1) {
        size /= 1024;
        unitIndex += 1;
      }

      const decimals = size >= 10 || unitIndex === 0 ? 0 : 1;
      return `${size.toFixed(decimals)} ${units[unitIndex]}`;
    }

    function syncOpenRelayIds() {
      document.querySelectorAll('[data-relay-details]').forEach((element) => {
        const relayId = element.getAttribute('data-relay-details');
        if (!relayId) {
          return;
        }

        if (element.open) {
          openRelayIds.add(relayId);
        } else {
          openRelayIds.delete(relayId);
        }
      });
    }

    function relayCapacityVariant(relay) {
      const current = Number(relay.current_sessions || 0);
      const max = Number(relay.max_sessions || 0);

      if (relay.status !== 'warm' || (max > 0 && current >= max)) {
        return 'relay-full';
      }

      if (current >= 8) {
        return 'relay-hot';
      }

      if (current >= 5) {
        return 'relay-warning';
      }

      return 'relay-healthy';
    }

    function renderRelays(relays) {
      if (!relays.length) {
        return '<div class="empty">No relay records available.</div>';
      }

      return relays.map((relay) => `
        <article class="card relay-card ${relayCapacityVariant(relay)}">
          <div class="card-head">
            <div class="card-title">${escapeHtml(relay.relay_id)}</div>
            <div class="badge">${escapeHtml(relay.status)}</div>
          </div>
          <div class="card-meta">
            <div>Sessions: ${escapeHtml(relay.current_sessions)} / ${escapeHtml(relay.max_sessions)}</div>
            <div>TTL: ${escapeHtml(relay.ttl_seconds)}s</div>
            <div>Public: ${escapeHtml(relay.public_endpoint || '-')}</div>
            <div>Internal: ${escapeHtml(relay.internal_endpoint)}</div>
          </div>
          <details data-relay-details="${escapeHtml(relay.relay_id)}" ${openRelayIds.has(relay.relay_id) ? 'open' : ''}>
            <summary>Assigned sessions and workers</summary>
            <div class="relay-session-list">
              ${relay.sessions.length ? relay.sessions.map((session) => `
                <div class="relay-session">
                  <div>Session: ${escapeHtml(session.session_id)}</div>
                  <div>Worker: ${escapeHtml(session.worker_id)}</div>
                  <div>Client: ${escapeHtml(session.client_id)}</div>
                  <div>Status: ${escapeHtml(session.status)}</div>
                  <div>Relay recv: ${escapeHtml(formatBytes(session.relay_bytes))}</div>
                  <div>Worker recv: ${escapeHtml(formatBytes(session.worker_bytes))}</div>
                </div>
              `).join('') : '<div class="empty">No active session bindings.</div>'}
            </div>
          </details>
        </article>
      `).join('');
    }

    function renderWorkers(workers, variantClass) {
      if (!workers.length) {
        return '<div class="empty">No workers in this state.</div>';
      }

      return workers.map((worker) => `
        <article class="card ${variantClass}">
          <div class="card-head">
            <div class="card-title">${escapeHtml(worker.worker_id)}</div>
            <div class="badge">${escapeHtml(worker.status)}</div>
          </div>
          <div class="card-meta">
            <div>Session: ${escapeHtml(worker.assigned_session_id || '-')}</div>
            <div>Relay: ${escapeHtml(worker.relay_id || '-')}</div>
            <div>Worker recv: ${escapeHtml(formatBytes(worker.media_bytes))} in ${escapeHtml(worker.media_packets || 0)} packets</div>
            <div>Relay recv: ${escapeHtml(formatBytes(worker.relay_received_bytes))} in ${escapeHtml(worker.relay_received_packets || 0)} packets</div>
            <div>TTL: ${escapeHtml(worker.ttl_seconds)}s</div>
            <div>Endpoint: ${escapeHtml(worker.endpoint)}</div>
          </div>
        </article>
      `).join('');
    }

    function renderDeadWorkers(deadWorkers, driftWorkers) {
      const workers = [...deadWorkers, ...driftWorkers];

      if (!workers.length) {
        return '<div class="empty">No dead or drift worker records.</div>';
      }

      return workers.map((worker) => `
        <article class="card danger-card">
          <div class="card-head">
            <div class="card-title">${escapeHtml(worker.worker_id)}</div>
            <div class="badge">${escapeHtml(worker.status)}</div>
          </div>
          <div class="card-meta">
            <div>Session: ${escapeHtml(worker.assigned_session_id || '-')}</div>
            <div>TTL until cleanup: ${escapeHtml(worker.ttl_seconds)}s</div>
            <div>Endpoint: ${escapeHtml(worker.endpoint)}</div>
          </div>
        </article>
      `).join('');
    }

    function renderSessions(sessions) {
      if (!sessions.length) {
        return '<div class="empty">No active session records.</div>';
      }

      return sessions.map((session) => `
        <article class="card session-card">
          <div class="card-head">
            <div class="card-title">${escapeHtml(session.session_id)}</div>
            <div class="badge">${escapeHtml(session.status)}</div>
          </div>
          <div class="card-meta">
            <div>Client: ${escapeHtml(session.client_id)}</div>
            <div>Relay: ${escapeHtml(session.relay_id || '-')}</div>
            <div>Worker: ${escapeHtml(session.worker_id || '-')}</div>
            <div>Relay recv: ${escapeHtml(formatBytes(session.relay_bytes))} in ${escapeHtml(session.relay_packets || 0)} packets</div>
            <div>Worker recv: ${escapeHtml(formatBytes(session.worker_bytes))} in ${escapeHtml(session.worker_packets || 0)} packets</div>
            <div>TTL: ${escapeHtml(session.ttl_seconds)}s</div>
          </div>
        </article>
      `).join('');
    }

    function renderRedis(redis) {
      const totalLookups = Number(redis.keyspace_hits || 0) + Number(redis.keyspace_misses || 0);
      const hitPercent = totalLookups > 0
        ? Math.round((Number(redis.keyspace_hits || 0) / totalLookups) * 100)
        : 0;
      const hitRate = totalLookups > 0 ? `${hitPercent}%` : '-';
      const db0 = redis.db0 || {};
      const keyspaceText = typeof db0 === 'string'
        ? db0
        : `keys=${db0.keys || 0}, expires=${db0.expires || 0}, avg_ttl=${db0.avg_ttl || 0}`;
      const usedMemory = parseFloat(String(redis.used_memory_human).replace(/[^\\d.]/g, '')) || 0;
      const peakMemory = parseFloat(String(redis.peak_memory_human).replace(/[^\\d.]/g, '')) || 0;
      const memoryPercent = peakMemory > 0 ? Math.min(100, Math.round((usedMemory / peakMemory) * 100)) : 0;
      const expiredKeys = Number(redis.expired_keys || 0);
      const expiredFill = Math.min(100, expiredKeys === 0 ? 4 : expiredKeys);
      const hitClass = hitPercent >= 95 ? '' : (hitPercent >= 80 ? 'warn' : 'danger');
      const memoryClass = memoryPercent >= 85 ? 'danger' : (memoryPercent >= 65 ? 'warn' : '');

      return `
        <article class="card redis-card">
          <div class="card-head">
            <div class="card-title">Redis ${escapeHtml(redis.version)}</div>
            <div class="badge">${escapeHtml(redis.status)}</div>
          </div>
          <div class="metric-grid">
            <div class="metric-bar">
              <div class="metric-bar-head">
                <span>Memory pressure</span>
                <span>${escapeHtml(redis.used_memory_human)} / ${escapeHtml(redis.peak_memory_human)}</span>
              </div>
              <div class="metric-bar-track">
                <div class="metric-bar-fill ${memoryClass}" style="width: ${memoryPercent}%"></div>
              </div>
            </div>
            <div class="metric-bar">
              <div class="metric-bar-head">
                <span>Keyspace hit rate</span>
                <span>${escapeHtml(hitRate)}</span>
              </div>
              <div class="metric-bar-track">
                <div class="metric-bar-fill ${hitClass}" style="width: ${hitPercent}%"></div>
              </div>
            </div>
            <div class="metric-bar">
              <div class="metric-bar-head">
                <span>Expiry churn</span>
                <span>${escapeHtml(redis.expired_keys)} expired</span>
              </div>
              <div class="metric-bar-track">
                <div class="metric-bar-fill warn" style="width: ${expiredFill}%"></div>
              </div>
            </div>
          </div>
          <div class="card-meta">
            <div>Clients: ${escapeHtml(redis.connected_clients)}</div>
            <div>Keyspace: ${escapeHtml(keyspaceText)}</div>
            <div>Evicted keys: ${escapeHtml(redis.evicted_keys)}</div>
            <div>Uptime: ${escapeHtml(redis.uptime_seconds)}s</div>
          </div>
        </article>
      `;
    }

    function setIfChanged(elementId, value) {
      const element = document.getElementById(elementId);
      if (element.textContent !== String(value)) {
        element.textContent = value;
      }
    }

    function setHtmlIfChanged(elementId, html) {
      const element = document.getElementById(elementId);
      if (element.innerHTML !== html) {
        element.innerHTML = html;
      }
    }

    async function refreshDashboard() {
      if (refreshInFlight) {
        return;
      }

      refreshInFlight = true;
      try {
        syncOpenRelayIds();

        const response = await fetch('/dashboard/state', { cache: 'no-store' });
        if (!response.ok) {
          throw new Error(`dashboard state failed: ${response.status}`);
        }
        const state = await response.json();
        const relayCapacityDetail = `${state.summary.relay_capacity_used} / ${state.summary.relay_capacity_total} sessions in use`;
        const workerRecordDetail = `${state.summary.worker_record_total} records tracked | worker recv ${formatBytes(state.summary.worker_media_total_bytes)}`;

        setIfChanged('updated-at', state.updated_at);
        setIfChanged('relay-total', state.summary.relay_total);
        setIfChanged('relay-capacity-detail', relayCapacityDetail);
        setIfChanged('relay-warm-total', state.summary.relay_warm_total);
        setIfChanged('relay-full-total', state.summary.relay_full_total);
        setIfChanged('worker-total', state.summary.worker_live_total);
        setIfChanged('worker-record-detail', workerRecordDetail);
        setIfChanged('warm-total', state.summary.warm_total);
        setIfChanged('busy-total', state.summary.busy_total);
        setIfChanged('dead-total', state.summary.dead_total);
        setIfChanged('session-total', state.summary.session_total);

        setHtmlIfChanged('relays', renderRelays(state.relays));
        setHtmlIfChanged('busy-workers', renderWorkers(state.busy_workers, 'busy-card'));
        setHtmlIfChanged('warm-workers', renderWorkers(state.warm_workers, 'warm-card'));
        setHtmlIfChanged('dead-workers', renderDeadWorkers(state.dead_workers, state.drift_workers));
        setHtmlIfChanged('sessions', renderSessions(state.sessions));
        setHtmlIfChanged('redis', renderRedis(state.redis));

        document.querySelectorAll('[data-relay-details]').forEach((element) => {
          element.ontoggle = syncOpenRelayIds;
        });
      } catch (error) {
        setIfChanged('updated-at', 'refresh failed');
      } finally {
        refreshInFlight = false;
      }
    }

    refreshDashboard();
    setInterval(refreshDashboard, 3000);
  </script>
</body>
</html>
"""


@router.get("/dashboard/state")
async def dashboard_state() -> dict:
    return await _load_dashboard_state()
