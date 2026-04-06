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


async def _load_dashboard_state() -> dict:
    redis_client = await get_redis()

    redis_info = await redis_client.info("stats")
    redis_clients = await redis_client.info("clients")
    redis_memory = await redis_client.info("memory")
    redis_server = await redis_client.info("server")
    redis_keyspace = await redis_client.info("keyspace")
    db0_keyspace = redis_keyspace.get("db0", {})

    if isinstance(db0_keyspace, str):
        db0_keyspace_summary = db0_keyspace
    else:
        db0_keyspace_summary = {
            "keys": db0_keyspace.get("keys", 0),
            "expires": db0_keyspace.get("expires", 0),
            "avg_ttl": db0_keyspace.get("avg_ttl", 0),
        }

    relay_keys = sorted(await redis_client.keys("relay:*"))
    relay_media_keys = sorted(await redis_client.keys("session-media-relay:*"))
    worker_keys = sorted(await redis_client.keys("worker:*"))
    worker_media_keys = sorted(await redis_client.keys("session-media-worker:*"))
    session_keys = sorted(await redis_client.keys("session:*"))

    relay_records: list[dict] = []
    for relay_key in relay_keys:
        relay_raw = await redis_client.get(relay_key)
        if relay_raw is None:
            continue

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
                "ttl_seconds": await redis_client.ttl(relay_key),
            }
        )

    worker_records: list[dict] = []
    for worker_key in worker_keys:
        worker_raw = await redis_client.get(worker_key)
        if worker_raw is None:
            continue

        worker = WorkerRecord.model_validate_json(worker_raw)
        worker_records.append(
            {
                "worker_id": worker.worker_id,
                "status": worker.status.value,
                "endpoint": worker.endpoint,
                "last_heartbeat": worker.last_heartbeat,
                "assigned_session_id": worker.assigned_session_id,
                "ttl_seconds": await redis_client.ttl(worker_key),
            }
        )

    relay_media_stats: dict[str, dict] = {}
    for relay_media_key in relay_media_keys:
        media_raw = await redis_client.get(relay_media_key)
        media = _safe_json_loads(media_raw)
        session_id = media.get("session_id")
        if session_id:
            relay_media_stats[session_id] = media

    worker_media_stats: dict[str, dict] = {}
    for worker_media_key in worker_media_keys:
        media_raw = await redis_client.get(worker_media_key)
        media = _safe_json_loads(media_raw)
        session_id = media.get("session_id")
        if session_id:
            worker_media_stats[session_id] = media

    session_records: list[dict] = []
    for session_key in session_keys:
        session_raw = await redis_client.get(session_key)
        if session_raw is None:
            continue

        session = json.loads(session_raw)
        session["ttl_seconds"] = await redis_client.ttl(session_key)
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
            "version": redis_server.get("redis_version", "-"),
            "uptime_seconds": redis_server.get("uptime_in_seconds", 0),
            "connected_clients": redis_clients.get("connected_clients", 0),
            "used_memory_human": redis_memory.get("used_memory_human", "-"),
            "peak_memory_human": redis_memory.get("used_memory_peak_human", "-"),
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
      --bg: #f3efe5;
      --panel: #fffaf1;
      --line: #d7cdb8;
      --text: #1d2a2d;
      --muted: #6f7b7d;
      --warm: #c7e7cf;
      --reserved: #f4d2a3;
      --other: #d7dce8;
      --sessions: #d8e9f1;
      --accent: #17494d;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      font-family: "Segoe UI", Tahoma, sans-serif;
      background:
        radial-gradient(circle at top left, #fff7e8 0, transparent 28%),
        linear-gradient(135deg, #ece5d7 0%, #f7f3ea 45%, #ebe4d3 100%);
      color: var(--text);
      overflow: hidden;
    }

    .page {
      height: 100vh;
      padding: 12px;
      display: grid;
      grid-template-rows: 82px 1fr;
      gap: 12px;
    }

    .hero {
      display: grid;
      grid-template-columns: 1.3fr repeat(5, 1fr);
      gap: 10px;
    }

    .panel {
      background: rgba(255, 250, 241, 0.9);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 10px 12px;
      box-shadow: 0 12px 30px rgba(34, 34, 34, 0.08);
      min-height: 0;
    }

    .hero-main {
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      background:
        linear-gradient(135deg, rgba(23, 73, 77, 0.95), rgba(39, 95, 89, 0.92));
      color: #f7f3ea;
    }

    .eyebrow {
      font-size: 12px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      opacity: 0.7;
    }

    .title {
      margin: 6px 0 0;
      font-size: 24px;
      font-weight: 700;
    }

    .subtitle {
      margin: 6px 0 0;
      font-size: 12px;
      color: rgba(247, 243, 234, 0.82);
    }

    .stat-label {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
    }

    .stat-value {
      margin-top: 6px;
      font-size: 26px;
      font-weight: 700;
    }

    .layout {
      min-height: 0;
      display: grid;
      grid-template-columns: 1fr 1fr 1fr 1.15fr;
      gap: 12px;
    }

    .column-title {
      margin: 0 0 6px;
      font-size: 14px;
      font-weight: 700;
    }

    .column-subtitle {
      margin: 0 0 8px;
      font-size: 11px;
      color: var(--muted);
    }

    .list {
      height: calc(100% - 36px);
      overflow: auto;
      display: flex;
      flex-direction: column;
      gap: 6px;
      padding-right: 4px;
    }

    .list::-webkit-scrollbar {
      width: 8px;
    }

    .list::-webkit-scrollbar-thumb {
      background: rgba(29, 42, 45, 0.18);
      border-radius: 999px;
    }

    .card {
      border-radius: 14px;
      padding: 8px 10px;
      border: 1px solid rgba(29, 42, 45, 0.08);
    }

    .warm-card {
      background: var(--warm);
    }

    .reserved-card {
      background: var(--reserved);
    }

    .other-card {
      background: var(--other);
    }

    .session-card {
      background: var(--sessions);
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
      padding: 1px 7px;
      border-radius: 999px;
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      background: rgba(255, 255, 255, 0.52);
    }

    .card-meta {
      margin-top: 6px;
      display: grid;
      gap: 2px;
      font-size: 11px;
      color: #304244;
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
      background: rgba(255, 255, 255, 0.35);
      padding: 10px;
    }

    @media (max-width: 1280px) {
      .hero {
        grid-template-columns: repeat(3, 1fr);
        grid-auto-rows: 1fr;
      }

      .hero-main {
        grid-column: 1 / -1;
      }

      .layout {
        grid-template-columns: 1fr 1fr;
        grid-template-rows: 1fr 1fr;
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
          <h1 class="title">Worker State Dashboard</h1>
          <p class="subtitle">Live view for warm and reserved workers, plus active session ownership.</p>
        </div>
        <div class="subtitle">Last update: <span id="updated-at">-</span></div>
      </article>
      <article class="panel">
        <div class="stat-label">Workers</div>
        <div id="worker-total" class="stat-value">0</div>
      </article>
      <article class="panel">
        <div class="stat-label">Warm</div>
        <div id="warm-total" class="stat-value">0</div>
      </article>
      <article class="panel">
        <div class="stat-label">Reserved</div>
        <div id="reserved-total" class="stat-value">0</div>
      </article>
      <article class="panel">
        <div class="stat-label">Other</div>
        <div id="other-total" class="stat-value">0</div>
      </article>
      <article class="panel">
        <div class="stat-label">Sessions</div>
        <div id="session-total" class="stat-value">0</div>
      </article>
    </section>

    <section class="layout">
      <article class="panel">
        <h2 class="column-title">Warm Workers</h2>
        <p class="column-subtitle">Immediately available workers.</p>
        <div id="warm-workers" class="list"></div>
      </article>

      <article class="panel">
        <h2 class="column-title">Reserved Workers</h2>
        <p class="column-subtitle">Workers currently holding a session.</p>
        <div id="reserved-workers" class="list"></div>
      </article>

      <article class="panel">
        <h2 class="column-title">Other Workers</h2>
        <p class="column-subtitle">Starting, active, dead, or unexpected states.</p>
        <div id="other-workers" class="list"></div>
      </article>

      <article class="panel">
        <h2 class="column-title">Sessions</h2>
        <p class="column-subtitle">Current session ownership and TTL.</p>
        <div id="sessions" class="list"></div>
      </article>
    </section>
  </div>

  <script>
    function renderWorkers(workers, variant) {
      if (!workers.length) {
        return '<div class="empty">No workers in this state.</div>';
      }

      return workers.map((worker) => `
        <article class="card ${variant}">
          <div class="card-head">
            <div class="card-title">${worker.worker_id}</div>
            <div class="badge">${worker.status}</div>
          </div>
          <div class="card-meta">
            <div>Session: ${worker.assigned_session_id || '-'}</div>
            <div>TTL: ${worker.ttl_seconds}s</div>
            <div>Endpoint: ${worker.endpoint}</div>
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
            <div class="card-title">${session.session_id}</div>
            <div class="badge">${session.status}</div>
          </div>
          <div class="card-meta">
            <div>Client: ${session.client_id}</div>
            <div>Worker: ${session.worker_id || '-'}</div>
            <div>TTL: ${session.ttl_seconds}s</div>
          </div>
        </article>
      `).join('');
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
      try {
        const response = await fetch('/dashboard/state', { cache: 'no-store' });
        const state = await response.json();

        setIfChanged('updated-at', state.updated_at);
        setIfChanged('worker-total', state.summary.worker_total);
        setIfChanged('warm-total', state.summary.warm_total);
        setIfChanged('reserved-total', state.summary.reserved_total);
        setIfChanged('other-total', state.summary.other_total);
        setIfChanged('session-total', state.summary.session_total);

        setHtmlIfChanged('warm-workers', renderWorkers(state.warm_workers, 'warm-card'));
        setHtmlIfChanged('reserved-workers', renderWorkers(state.reserved_workers, 'reserved-card'));
        setHtmlIfChanged('other-workers', renderWorkers(state.other_workers, 'other-card'));
        setHtmlIfChanged('sessions', renderSessions(state.sessions));
      } catch (error) {
        setIfChanged('updated-at', 'refresh failed');
      }
    }

    refreshDashboard();
    setInterval(refreshDashboard, 1200);
  </script>
</body>
</html>
"""


@router.get("/dashboard/state")
async def dashboard_state() -> dict:
    return await _load_dashboard_state()
