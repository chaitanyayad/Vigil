"""Incident triage: context building + LLM call + persistence.

Guardrails: 20s timeout and token cap live in the provider; one triage per
alert per cooldown window; graceful no-op when the provider is disabled.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from vigil.core.config import get_settings
from vigil.db.models import (
    Alert,
    AlertEventType,
    AlertState,
    Observer,
    TriageResult,
)
from vigil.ledger.hashing import record_alert_event
from vigil.triage.provider import LLMProvider, TriageError, get_provider
from vigil.triage.runbooks import retrieve_chunks
from vigil.ws import bus

log = logging.getLogger(__name__)

PROMPT_TEMPLATE = """You are the on-call triage assistant for an infrastructure monitoring system.
Given the alert, recent metrics, other active alerts on the host, and candidate runbook excerpts,
produce a root-cause hypothesis and pick the single most relevant runbook.

## Alert
{alert_block}

## Last 30 minutes of metrics for this host (1-minute averages, oldest first)
{metrics_block}

## Other active alerts on this host
{other_alerts_block}

## Candidate runbook excerpts
{runbooks_block}

Respond with JSON: hypothesis (1-3 sentences, name the most likely root cause),
confidence (0.0-1.0), suggested_runbook (exactly one runbook name from the excerpts,
e.g. "memory-leak"), next_steps (2-5 short imperative actions).
"""


class TriageSkipped(Exception):
    pass


async def _metrics_block(db: AsyncSession, observer_id: uuid.UUID) -> str:
    rows = await db.execute(
        text("""
            SELECT bucket, cpu_avg, mem_avg, disk_avg, net_rx_avg, net_tx_avg, load1_avg
            FROM metrics_1m
            WHERE observer_id = :oid AND bucket > now() - interval '30 minutes'
            ORDER BY bucket
        """),
        {"oid": str(observer_id)},
    )
    lines = ["time | cpu% | mem% | disk% | net_rx_bps | net_tx_bps | load1"]
    for r in rows:
        lines.append(
            f"{r.bucket:%H:%M} | "
            + " | ".join("-" if v is None else f"{float(v):.1f}" for v in
                         (r.cpu_avg, r.mem_avg, r.disk_avg, r.net_rx_avg, r.net_tx_avg, r.load1_avg))
        )
    return "\n".join(lines) if len(lines) > 1 else "(no metrics in window)"


async def run_triage(
    db: AsyncSession,
    alert_id: uuid.UUID,
    provider: LLMProvider | None = None,
    force: bool = False,
) -> TriageResult:
    """Raises TriageSkipped (disabled / cooldown / resolved) or TriageError."""
    s = get_settings()
    provider = provider or get_provider()
    if not provider.enabled:
        raise TriageSkipped("triage disabled: no LLM API key configured")

    alert = await db.get(Alert, alert_id)
    if alert is None:
        raise TriageSkipped(f"alert {alert_id} not found")
    if alert.state == AlertState.resolved and not force:
        raise TriageSkipped("alert already resolved")

    cooldown = datetime.now(UTC) - timedelta(minutes=s.triage_cooldown_minutes)
    recent = (
        await db.execute(
            select(TriageResult)
            .where(TriageResult.alert_id == alert_id, TriageResult.created_at > cooldown)
            .limit(1)
        )
    ).scalar_one_or_none()
    if recent is not None and not force:
        raise TriageSkipped(f"triaged less than {s.triage_cooldown_minutes} min ago")

    observer = await db.get(Observer, alert.observer_id)
    other_alerts = list(
        (
            await db.execute(
                select(Alert).where(
                    Alert.observer_id == alert.observer_id,
                    Alert.id != alert.id,
                    Alert.state != AlertState.resolved,
                )
            )
        ).scalars()
    )
    query = f"{alert.summary} severity={alert.severity.value} source={alert.source.value}"
    chunks = await retrieve_chunks(db, query, k=3)

    prompt = PROMPT_TEMPLATE.format(
        alert_block=(
            f"host: {observer.name if observer else alert.observer_id}\n"
            f"source: {alert.source.value}  severity: {alert.severity.value}\n"
            f"fired_at: {alert.fired_at}\nsummary: {alert.summary}\n"
            f"anomaly_score: {alert.anomaly_score}"
        ),
        metrics_block=await _metrics_block(db, alert.observer_id),
        other_alerts_block=(
            "\n".join(f"- [{a.severity.value}] {a.summary}" for a in other_alerts) or "(none)"
        ),
        runbooks_block=(
            "\n\n".join(f"### runbook: {c.runbook}\n{c.content}" for c in chunks)
            or "(no runbooks indexed)"
        ),
    )

    output, raw = await provider.triage(prompt)

    result = TriageResult(
        alert_id=alert.id,
        model=provider.name,
        hypothesis=output.hypothesis,
        suggested_runbook=output.suggested_runbook,
        confidence=output.confidence,
        raw_response={"output": output.model_dump(), "response": _slim(raw)},
    )
    db.add(result)
    await record_alert_event(
        db,
        alert.id,
        AlertEventType.triaged,
        {
            "model": provider.name,
            "hypothesis": output.hypothesis,
            "suggested_runbook": output.suggested_runbook,
            "confidence": output.confidence,
        },
    )
    await db.commit()
    await bus.publish(
        bus.CH_ALERTS, "alert_triaged",
        {"alert_id": str(alert.id), "hypothesis": output.hypothesis,
         "suggested_runbook": output.suggested_runbook, "confidence": output.confidence},
    )
    return result


def _slim(raw: dict) -> dict:
    """Keep usage/model metadata, drop bulky content from the stored raw response."""
    return {k: v for k, v in raw.items() if k in ("usageMetadata", "modelVersion", "responseId")}


async def auto_triage_tick() -> None:
    """Periodic worker: triage critical firing alerts that have no result yet."""
    from vigil.db.session import get_sessionmaker

    provider = get_provider()
    if not provider.enabled:
        return
    async with get_sessionmaker()() as db:
        rows = await db.execute(
            text("""
                SELECT a.id FROM alerts a
                LEFT JOIN triage_results t ON t.alert_id = a.id
                WHERE a.severity = 'critical' AND a.state = 'firing' AND t.id IS NULL
                LIMIT 5
            """)
        )
        for (alert_id,) in rows:
            try:
                await run_triage(db, alert_id, provider=provider)
            except TriageSkipped:
                pass
            except TriageError:
                log.exception("auto-triage failed for %s", alert_id)
