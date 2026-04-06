#!/usr/bin/env python3
from __future__ import annotations

import argparse
import http.client
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, request
from urllib.parse import urlparse
from uuid import uuid4

DEFAULT_BASE_URL = "http://localhost:8080"
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_CHUNK_SIZE = 262144
DEFAULT_INTERVAL_MS = 250.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Einfacher Dummy-Client fuer Session-Erstellung und Relay-Ingest.",
    )
    parser.add_argument(
        "file",
        help="Datei, die an den zugewiesenen Relay gesendet wird",
    )
    return parser.parse_args()


def generate_client_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"dummy-client-{timestamp}-{uuid4().hex[:8]}"


def create_session(client_id: str) -> dict:
    payload = json.dumps(
        {
            "client_id": client_id,
            "stream_profile": "480p",
            "transport": "udp",
        }
    ).encode("utf-8")

    req = request.Request(
        f"{DEFAULT_BASE_URL}/sessions",
        method="POST",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )

    try:
        with request.urlopen(req, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8")
            return json.loads(body)
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        message = body or exc.reason
        raise RuntimeError(f"HTTP {exc.code} for {req.full_url}: {message}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Request failed for {req.full_url}: {exc.reason}") from exc


def ingest_payload(
    *,
    relay_public_endpoint: str,
    session_id: str,
    payload: bytes,
) -> dict:
    parsed = urlparse(f"http://{relay_public_endpoint}")
    connection = http.client.HTTPConnection(
        parsed.hostname,
        parsed.port,
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )

    try:
        connection.request(
            "POST",
            f"/internal/v1/media/ingest/{session_id}",
            body=payload,
            headers={
                "Content-Type": "application/octet-stream",
                "Accept": "application/json",
            },
        )
        response = connection.getresponse()
        body = response.read().decode("utf-8")
    finally:
        connection.close()

    if response.status < 200 or response.status >= 300:
        message = body or response.reason
        raise RuntimeError(
            f"HTTP {response.status} for http://{relay_public_endpoint}/internal/v1/media/ingest/{session_id}: {message}"
        )

    return json.loads(body)


def print_assignment(assignment: dict) -> None:
    print("Session zugewiesen:")
    print(f"  session_id: {assignment['session_id']}")
    print(f"  client_id: {assignment['client_id']}")
    print(f"  status: {assignment['status']}")
    print(f"  ttl_seconds: {assignment['ttl_seconds']}")
    print(f"  relay_id: {assignment.get('relay_id') or '-'}")
    print(f"  relay_public_endpoint: {assignment.get('relay_public_endpoint') or '-'}")
    print(f"  worker_id: {assignment.get('worker_id') or '-'}")


def stream_file(file_path: Path, relay_public_endpoint: str, session_id: str) -> None:
    if not file_path.is_file():
        raise RuntimeError(f"Datei nicht gefunden: {file_path}")

    sleep_seconds = DEFAULT_INTERVAL_MS / 1000.0
    total_chunks = 0
    total_bytes = 0

    print(
        f"\nSende Datei an Relay: {file_path} "
        f"({file_path.stat().st_size} Bytes, chunk_size={DEFAULT_CHUNK_SIZE}, interval_ms={DEFAULT_INTERVAL_MS:g})"
    )

    with file_path.open("rb") as handle:
        while True:
            chunk = handle.read(DEFAULT_CHUNK_SIZE)
            if not chunk:
                break

            ingest_payload(
                relay_public_endpoint=relay_public_endpoint,
                session_id=session_id,
                payload=chunk,
            )
            total_chunks += 1
            total_bytes += len(chunk)

            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

    print(
        f"\nDateistream abgeschlossen: {total_bytes} Bytes in {total_chunks} Chunks"
    )


def main() -> int:
    args = parse_args()
    file_path = Path(args.file)

    try:
        assignment = create_session(generate_client_id())
        print_assignment(assignment)

        relay_public_endpoint = assignment.get("relay_public_endpoint")
        if not relay_public_endpoint:
            raise RuntimeError("Kein relay_public_endpoint in der Session-Antwort vorhanden.")

        stream_file(
            file_path=file_path,
            relay_public_endpoint=relay_public_endpoint,
            session_id=assignment["session_id"],
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nDateistream manuell beendet.")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
