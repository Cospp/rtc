import asyncio
import json
from urllib import error, request

from session_control.app.core.config import settings


class RelayBindError(Exception):
    pass


class RelayClient:
    async def bind_session(
        self,
        relay_internal_endpoint: str,
        session_id: str,
        worker_id: str,
    ) -> dict:
        url = f"http://{relay_internal_endpoint}/internal/v1/sessions/bind"
        payload = json.dumps(
            {
                "session_id": session_id,
                "worker_id": worker_id,
            }
        ).encode("utf-8")

        req = request.Request(
            url,
            method="POST",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

        def _send() -> dict:
            try:
                with request.urlopen(req, timeout=settings.relay_bind_timeout_seconds) as response:
                    body = response.read().decode("utf-8")
                    return json.loads(body)
            except error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="ignore")
                try:
                    payload = json.loads(body)
                    message = payload.get("error", exc.reason)
                except json.JSONDecodeError:
                    message = body or exc.reason
                raise RelayBindError(f"Relay bind failed: {message}") from exc
            except Exception as exc:
                raise RelayBindError(f"Relay bind failed: {exc}") from exc

        return await asyncio.to_thread(_send)
