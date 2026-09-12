"""Alert lifecycle: fire / ack / resolve. Single write path shared by the rules
engine, heartbeat watchdog, anomaly detector, and the REST API — every state
change lands one row in the alert_events hash chain and one bus message."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from vigil.db.models import Alert, AlertEventType, AlertSource, AlertState, Severity
from vigil.ledger.hashing import record_alert_event
from vigil.ws import bus


def _alert_dict(a: Alert) -> dict:
    return {
        "id": str(a.id),
        "observer_id": str(a.observer_id),
        "rule_id": str(a.rule_id) if a.rule_id else None,
        "source": a.source.value if isinstance(a.source, AlertSource) else a.source,
        "severity": a.severity.value if isinstance(a.severity, Severity) else a.severity,
        "state": a.state.value if isinstance(a.state, AlertState) else a.state,
        "summary": a.summary,
        "anomaly_score": a.anomaly_score,
        "fired_at": a.fired_at.isoformat() if a.fired_at else None,
    }


async def fire_alert(
    db: AsyncSession,
    observer_id: uuid.UUID,
    source: AlertSource,
    severity: Severity,
    summary: str,
    rule_id: uuid.UUID | None = None,
    anomaly_score: float | None = None,
) -> tuple[Alert, bool]:
    """Fire (or refresh) an alert. Dedupe rides on the partial unique indexes:
    an existing active alert gets its summary/score updated, no new row and no
    new lifecycle event. Returns (alert, newly_fired)."""
    values = dict(
        id=uuid.uuid4(),
        observer_id=observer_id,
        rule_id=rule_id,
        source=source,
        severity=severity,
        state=AlertState.firing,
        summary=summary,
        anomaly_score=anomaly_score,
        fired_at=datetime.now(UTC),
    )
    stmt = pg_insert(Alert).values(**values)
    if source == AlertSource.rule and rule_id is not None:
        stmt = stmt.on_conflict_do_update(
            index_elements=["observer_id", "rule_id"],
            index_where=text("state != 'resolved' AND rule_id IS NOT NULL"),
            set_=dict(summary=summary),
        )
    else:
        where = (
            "source = 'anomaly' AND state != 'resolved'"
            if source == AlertSource.anomaly
            else "source = 'watchdog' AND state != 'resolved'"
        )
        set_: dict[str, object] = dict(summary=summary)
        if anomaly_score is not None:
            set_["anomaly_score"] = anomaly_score
        stmt = stmt.on_conflict_do_update(
            index_elements=["observer_id"], index_where=text(where), set_=set_
        )
    # xmax = 0 ⇔ the row was inserted (not updated) in this statement
    result = await db.execute(stmt.returning(Alert.id, text("(xmax = 0) AS inserted")))
    row = result.one()
    alert = (await db.execute(select(Alert).where(Alert.id == row[0]))).scalar_one()
    newly_fired = bool(row[1])
    if newly_fired:
        await record_alert_event(
            db,
            alert.id,
            AlertEventType.fired,
            {
                "source": source.value,
                "severity": severity.value,
                "summary": summary,
                "rule_id": str(rule_id) if rule_id else None,
                "anomaly_score": anomaly_score,
                "observer_id": str(observer_id),
            },
        )
        await bus.publish(bus.CH_ALERTS, "alert_fired", _alert_dict(alert))
    return alert, newly_fired


async def ack_alert(db: AsyncSession, alert: Alert, who: str = "admin") -> Alert:
    if alert.state != AlertState.firing:
        return alert
    alert.state = AlertState.acknowledged
    alert.acked_at = datetime.now(UTC)
    await record_alert_event(db, alert.id, AlertEventType.acked, {"by": who})
    await bus.publish(bus.CH_ALERTS, "alert_acked", _alert_dict(alert))
    return alert


async def resolve_alert(db: AsyncSession, alert: Alert, reason: str = "condition_cleared") -> Alert:
    if alert.state == AlertState.resolved:
        return alert
    alert.state = AlertState.resolved
    alert.resolved_at = datetime.now(UTC)
    await record_alert_event(db, alert.id, AlertEventType.resolved, {"reason": reason})
    await bus.publish(bus.CH_ALERTS, "alert_resolved", _alert_dict(alert))
    return alert


async def find_active_alert(
    db: AsyncSession,
    observer_id: uuid.UUID,
    rule_id: uuid.UUID | None = None,
    source: AlertSource | None = None,
) -> Alert | None:
    q = select(Alert).where(Alert.observer_id == observer_id, Alert.state != AlertState.resolved)
    if rule_id is not None:
        q = q.where(Alert.rule_id == rule_id)
    if source is not None:
        q = q.where(Alert.source == source)
    return (await db.execute(q.limit(1))).scalar_one_or_none()
