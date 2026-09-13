"""psutil sampling. Network counters are cumulative, so rates are derived from
the delta between consecutive samples."""

import os
import time
from datetime import UTC, datetime
from typing import Any

import psutil


class Collector:
    def __init__(self) -> None:
        self._last_net: tuple[float, int, int] | None = None
        psutil.cpu_percent(interval=None)  # prime the internal counter

    def sample(self) -> dict[str, Any]:
        now = time.monotonic()
        net = psutil.net_io_counters()
        rx_bps = tx_bps = None
        if self._last_net is not None:
            dt = now - self._last_net[0]
            if dt > 0:
                rx_bps = max(0, int((net.bytes_recv - self._last_net[1]) * 8 / dt))
                tx_bps = max(0, int((net.bytes_sent - self._last_net[2]) * 8 / dt))
        self._last_net = (now, net.bytes_recv, net.bytes_sent)

        try:
            load1 = os.getloadavg()[0]
        except (OSError, AttributeError):  # Windows has no loadavg
            load1 = None

        disk = psutil.disk_usage("/")
        return {
            "ts": datetime.now(UTC).isoformat(),
            "cpu_pct": psutil.cpu_percent(interval=None),
            "mem_pct": psutil.virtual_memory().percent,
            "disk_pct": disk.percent,
            "net_rx_bps": rx_bps,
            "net_tx_bps": tx_bps,
            "load1": load1,
        }
