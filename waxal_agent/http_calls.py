"""One policy for every hosted API called over HTTP (Soynade, ElevenLabs, whatever comes next): not tied to any of them.

    policy = CallPolicy("Soynade API call", SoynadeError, detail=..., limit_hint="...")
    response = policy.run(lambda: http.post(url, ...), url)

What it does, the same for all:
- never two calls closer than `min_interval` seconds;
- a rate limit (429) is waited out as the server says (Retry-After, else growing waits, at most 30 s), `retries` times; if it
  is still there, the call fails and NO call is made for `cooldown` seconds (each further call would be refused too, and
  would only extend the limit);
- a server error (5xx) is retried `server_retries` times, a network error `network_retries` times, never for minutes (the
  person is waiting);
- no credit / quota (402) fails at once and also starts the cooldown; any other 4xx fails at once.
The error raised is `error(message, status=...)` and says which URL and what the service answered.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

import httpx

log = logging.getLogger("waxal.http")

MAX_WAIT = 30.0


def retry_after(response: httpx.Response) -> float:
    try:
        return max(0.0, float(response.headers.get("retry-after", "0")))
    except ValueError:
        return 0.0


class CallPolicy:
    def __init__(self, name: str, error: Callable[..., Exception], *, detail: Callable[[httpx.Response], str],
                 retries: int = 2, server_retries: int = 1, network_retries: int | None = None, backoff: float = 2.0,
                 min_interval: float = 0.0, cooldown: float = 60.0, limit_hint: str = "",
                 quota_statuses: tuple[int, ...] = (402,)) -> None:
        self.name, self.error, self.detail = name, error, detail
        self.retries, self.server_retries = retries, server_retries
        self.network_retries = retries if network_retries is None else network_retries
        self.backoff, self.min_interval, self.cooldown = backoff, min_interval, cooldown
        self.limit_hint, self.quota_statuses = limit_hint, quota_statuses
        self._cooldown_until = 0.0
        self._gate = threading.Lock()
        self._last_call = 0.0

    def _throttle(self) -> None:
        with self._gate:
            wait = self._last_call + self.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

    def _sleep(self, seconds: float, count: int) -> None:
        time.sleep(min(max(seconds, self.backoff * (2 ** (count - 1))), MAX_WAIT))

    def run(self, send: Callable[[], httpx.Response], url: str) -> httpx.Response:
        remaining = self._cooldown_until - time.monotonic()
        if remaining > 0:
            raise self.error(f"{self.name}: the limit was reached, not calling again for {remaining:.0f} s.", status=429)
        failed = f"{self.name} failed ({url}): "
        last, asked = "", 0.0
        limited = server_errors = network_errors = 0
        while True:
            self._throttle()
            started = time.monotonic()
            try:
                response = send()
            except httpx.TransportError as e:
                last = f"network error: {type(e).__name__}: {e}"
                log.warning("%s: %s after %.1f s", url, last, time.monotonic() - started)
                network_errors += 1
                if network_errors > self.network_retries:
                    raise self.error(failed + last) from e
                self._sleep(0, network_errors)
                continue
            status = response.status_code
            log.info("%s -> HTTP %s in %.1f s", url, status, time.monotonic() - started)
            if status == 200:
                return response
            last = f"HTTP {status}: {self.detail(response)}"
            log.warning("%s refused: %s (Retry-After: %s)", url, last[:300], response.headers.get("retry-after", "not given"))
            if status == 429:
                limited += 1
                asked = retry_after(response)
                if limited > self.retries:
                    self._cooldown_until = time.monotonic() + max(asked, self.cooldown)
                    raise self.error(failed + last + "." + (" " + self.limit_hint if self.limit_hint else ""), status=429)
                self._sleep(asked, limited)
            elif status in self.quota_statuses:
                self._cooldown_until = time.monotonic() + self.cooldown
                raise self.error(failed + last, status=status)
            elif status >= 500:
                server_errors += 1
                if server_errors > self.server_retries:
                    raise self.error(failed + last, status=status)
                self._sleep(retry_after(response), server_errors)
            else:
                raise self.error(failed + last, status=status)
