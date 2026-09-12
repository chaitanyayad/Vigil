"""Static threshold rules engine (Sentinel parity).

`for_seconds` semantics: a rule fires only when the condition has held
continuously for at least that long. We track the first breaching sample
timestamp per (rule, observer) in Redis; any non-breaching sample clears it.
Samples are processed in timestamp order.
"""

import operator
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vigil.db.models import AlertRule, AlertSource, Observer, RuleOp
from vigil.rules.lifecycle import find_active_alert, fire_alert, resolve_alert
from vigil.ws.bus import get_redis

_OPS = {RuleOp.gt: operator.gt, RuleOp.lt: operator.lt, RuleOp.gte: operator.ge, RuleOp.lte: operator.le}

_STATE_TTL = 24 * 3600  # stale breach state expires on its own


def selector_matches(selector: dict[str, Any] | None, labels: dict[str, Any] | None) -> bool:
    """null selector = all observers; otherwise every selector k/v must match."""
    if not selector:
        return True
    labels = labels or {}
    return all(labels.get(k) == v for k, v in selector.items())


def condition_breached(rule: AlertRule, value: float | None) -> bool:
    if value is None:
        return False
    return _OPS[rule.op](value, rule.threshold)


def _state_key(rule_id: uuid.UUID, observer_id: uuid.UUID) -> str:
    return f"rule_state:{rule_id}:{observer_id}"


async def load_enabled_rules(db: AsyncSession) -> list[AlertRule]:
    return list(
        (await db.execute(select(AlertRule).where(AlertRule.enabled == True))).scalars()  # noqa: E712
    )


async def evaluate_samples(
    db: AsyncSession,
    observer: Observer,
    samples: list[dict[str, Any]],
    rules: list[AlertRule] | None = None,
) -> None:
    """Run every matching enabled rule over an ordered batch of samples."""
    if rules is None:
        rules = await load_enabled_rules(db)
    rules = [r for r in rules if selector_matches(r.observer_selector, observer.labels)]
    if not rules:
        return
    redis = get_redis()
    samples = sorted(samples, key=lambda s: s["ts"])

    for rule in rules:
        key = _state_key(rule.id, observer.id)
        for sample in samples:
            value = sample.get(rule.metric)
            ts: datetime = sample["ts"]
            if condition_breached(rule, value):
                first = await redis.get(key)
                if first is None:
                    await redis.set(key, ts.isoformat(), ex=_STATE_TTL)
                    first_ts = ts
                else:
                    first_ts = datetime.fromisoformat(str(first))
                held = (ts - first_ts).total_seconds()
                if held >= rule.for_seconds:
                    await fire_alert(
                        db,
                        observer.id,
                        AlertSource.rule,
                        rule.severity,
                        f"{rule.name}: {rule.metric}={value:.1f} {rule.op.value} "
                        f"{rule.threshold} for {int(held)}s on {observer.name}",
                        rule_id=rule.id,
                    )
            else:
                await redis.delete(key)
                active = await find_active_alert(db, observer.id, rule_id=rule.id)
                if active is not None:
                    await resolve_alert(db, active, reason="condition_cleared")
