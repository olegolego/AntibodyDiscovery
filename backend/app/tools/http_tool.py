"""Shared HTTP client for tool adapters.

Wraps httpx with:
- exponential-backoff retries on connection errors and 5xx responses
- health-check before the first real request (fast fail with clear message)
- uniform error messages distinguishing "server down" from "server error"
"""
import asyncio
import logging
from collections.abc import Callable, Awaitable
from typing import Any

import httpx

log = logging.getLogger(__name__)

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_BASE_DELAY = 2.0   # seconds; doubles each attempt


async def _health_check(client: httpx.AsyncClient, base_url: str, tool_name: str) -> None:
    """Quick /health ping. Raises RuntimeError with an actionable message on failure."""
    try:
        r = await client.get(f"{base_url}/health", timeout=10)
        if r.status_code >= 500:
            raise RuntimeError(
                f"{tool_name} server is up but unhealthy (HTTP {r.status_code}). "
                f"Check the server logs at {base_url}."
            )
    except httpx.ConnectError:
        raise RuntimeError(
            f"{tool_name} server is not reachable at {base_url}. "
            "Start the server and ensure the URL is correct."
        )
    except httpx.TimeoutException:
        raise RuntimeError(
            f"{tool_name} health check timed out at {base_url}. "
            "The server may be overloaded — try again shortly."
        )


async def post_with_retry(
    base_url: str,
    path: str,
    payload: dict[str, Any],
    *,
    tool_name: str,
    timeout: float = 1800,
    on_log: Callable[[str], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    """POST to `base_url/path` with retry logic.

    Performs a health check first so the user gets a clear "server not running"
    message rather than a raw ConnectError traceback.
    """
    async def _log(msg: str) -> None:
        log.info("[%s] %s", tool_name, msg)
        if on_log:
            await on_log(msg)

    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=15)) as client:
        await _health_check(client, base_url, tool_name)

        last_exc: Exception | None = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = await client.post(f"{base_url}{path}", json=payload)

                if resp.status_code in _RETRYABLE_STATUS and attempt < _MAX_RETRIES:
                    delay = _BASE_DELAY * (2 ** (attempt - 1))
                    await _log(
                        f"HTTP {resp.status_code} — retrying in {delay:.0f}s "
                        f"(attempt {attempt}/{_MAX_RETRIES})"
                    )
                    await asyncio.sleep(delay)
                    continue

                if resp.status_code >= 400:
                    # Try to extract a detail message from the response body
                    try:
                        detail = resp.json().get("detail") or resp.text[:300]
                    except Exception:
                        detail = resp.text[:300]
                    raise RuntimeError(
                        f"{tool_name} returned HTTP {resp.status_code}: {detail}"
                    )

                return resp.json()

            except (httpx.ConnectError, httpx.RemoteProtocolError) as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    delay = _BASE_DELAY * (2 ** (attempt - 1))
                    await _log(
                        f"Connection error — retrying in {delay:.0f}s "
                        f"(attempt {attempt}/{_MAX_RETRIES}): {exc}"
                    )
                    await asyncio.sleep(delay)
                else:
                    raise RuntimeError(
                        f"{tool_name} connection failed after {_MAX_RETRIES} attempts. "
                        f"Is the server running at {base_url}? Last error: {exc}"
                    ) from exc

            except httpx.TimeoutException as exc:
                raise RuntimeError(
                    f"{tool_name} request timed out after {timeout}s. "
                    "The job may still be running on the server."
                ) from exc

        # Should be unreachable, but keeps mypy happy
        raise RuntimeError(
            f"{tool_name} failed after {_MAX_RETRIES} retries"
        ) from last_exc
