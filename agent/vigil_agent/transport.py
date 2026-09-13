"""HTTP transport with exponential backoff and an on-disk ring buffer.

If the orchestrator is unreachable, samples land in a local ring buffer
(last 1000) and are flushed in batches on reconnect — nothing is lost across
short outages, and the buffer survives agent restarts.
"""

import json
import logging
import random
import time
from collections import deque
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)

RING_SIZE = 1000
MAX_BATCH = 100


class RingBuffer:
    def __init__(self, path: Path, size: int = RING_SIZE) -> None:
        self.path = path
        self.size = size
        self._buf: deque[dict[str, Any]] = deque(maxlen=size)
        self._load()

    def _load(self) -> None:
        try:
            if self.path.exists():
                self._buf.extend(json.loads(self.path.read_text())[-self.size:])
        except (json.JSONDecodeError, OSError):
            log.warning("could not load buffer file %s — starting empty", self.path)

    def _persist(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(list(self._buf)))
        except OSError:
            log.warning("could not persist buffer to %s", self.path)

    def push(self, samples: list[dict[str, Any]]) -> None:
        self._buf.extend(samples)
        self._persist()

    def drain(self, n: int = MAX_BATCH) -> list[dict[str, Any]]:
        out = [self._buf.popleft() for _ in range(min(n, len(self._buf)))]
        self._persist()
        return out

    def requeue_front(self, samples: list[dict[str, Any]]) -> None:
        for s in reversed(samples):
            self._buf.appendleft(s)
        self._persist()

    def __len__(self) -> int:
        return len(self._buf)


class Transport:
    def __init__(self, base_url: str, api_key: str, buffer_path: Path) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.buffer = RingBuffer(buffer_path)
        self._failures = 0
        self._client = httpx.Client(timeout=10.0)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def backoff_seconds(self) -> float:
        if self._failures == 0:
            return 0.0
        return min(60.0, (2 ** min(self._failures, 6)) + random.uniform(0, 1))

    def send_metrics(self, samples: list[dict[str, Any]]) -> bool:
        """Buffer the new samples, then try to flush everything buffered."""
        self.buffer.push(samples)
        return self.flush()

    def flush(self) -> bool:
        while len(self.buffer):
            batch = self.buffer.drain(MAX_BATCH)
            try:
                resp = self._client.post(
                    f"{self.base_url}/v1/ingest/metrics",
                    json={"samples": batch},
                    headers=self._headers(),
                )
                resp.raise_for_status()
                self._failures = 0
            except httpx.HTTPError as e:
                self.buffer.requeue_front(batch)
                self._failures += 1
                log.warning(
                    "metrics send failed (%s); %d samples buffered, backoff %.1fs",
                    e, len(self.buffer), self.backoff_seconds(),
                )
                return False
        return True

    def send_heartbeat(self) -> bool:
        try:
            resp = self._client.post(
                f"{self.base_url}/v1/ingest/heartbeat", headers=self._headers()
            )
            resp.raise_for_status()
            return True
        except httpx.HTTPError as e:
            log.warning("heartbeat failed: %s", e)
            return False

    def close(self) -> None:
        self._client.close()


def wait_with_backoff(transport: Transport) -> None:
    delay = transport.backoff_seconds()
    if delay:
        time.sleep(delay)
