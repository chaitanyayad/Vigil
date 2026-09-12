import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vigil.core.auth import require_admin
from vigil.db.session import get_db

router = APIRouter(prefix="/v1/metrics", tags=["metrics"], dependencies=[Depends(require_admin)])


@router.get("")
async def query_metrics(
    observer_id: uuid.UUID,
    frm: datetime | None = Query(None, alias="from"),
    to: datetime | None = None,
    step: int = Query(60, ge=60, le=86400, description="bucket size in seconds"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Read from the metrics_1m continuous aggregate (real-time aggregation:
    recent raw rows are unioned in automatically), re-bucketed to `step`."""
    to = to or datetime.now(UTC)
    frm = frm or to - timedelta(hours=1)
    rows = await db.execute(
        text("""
            SELECT time_bucket(make_interval(secs => :step), bucket) AS ts,
                   avg(cpu_avg)  AS cpu_pct,  max(cpu_max)  AS cpu_max,
                   avg(mem_avg)  AS mem_pct,  max(mem_max)  AS mem_max,
                   avg(disk_avg) AS disk_pct,
                   avg(net_rx_avg) AS net_rx_bps, avg(net_tx_avg) AS net_tx_bps,
                   avg(load1_avg) AS load1, sum(sample_count) AS samples
            FROM metrics_1m
            WHERE observer_id = :oid AND bucket >= :frm AND bucket < :to
            GROUP BY 1 ORDER BY 1
        """),
        {"step": step, "oid": str(observer_id), "frm": frm, "to": to},
    )
    points = [
        {
            "ts": r.ts.isoformat(),
            "cpu_pct": _f(r.cpu_pct), "cpu_max": _f(r.cpu_max),
            "mem_pct": _f(r.mem_pct), "mem_max": _f(r.mem_max),
            "disk_pct": _f(r.disk_pct),
            "net_rx_bps": _f(r.net_rx_bps), "net_tx_bps": _f(r.net_tx_bps),
            "load1": _f(r.load1), "samples": int(r.samples or 0),
        }
        for r in rows
    ]
    return {"observer_id": str(observer_id), "step": step, "points": points}


def _f(v) -> float | None:
    return None if v is None else round(float(v), 3)
