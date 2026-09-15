"""ML orchestration: training jobs + the per-minute inference tick.

Training and scoring are CPU-bound sklearn calls, so they run via
asyncio.to_thread — request handlers never block on them.
"""

import asyncio
import logging
import uuid

import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from vigil.core.config import get_settings
from vigil.db.models import AlertSource, MLModel, Observer, ObserverStatus, Severity
from vigil.db.session import get_sessionmaker
from vigil.ml import model as ml_model
from vigil.ml.eval import run_eval
from vigil.rules.lifecycle import find_active_alert, fire_alert, resolve_alert
from vigil.ws.bus import get_redis

log = logging.getLogger(__name__)

MIN_TRAIN_MINUTES = 24 * 60  # < 24 h of data → fall back to the global model
INFER_HISTORY_MINUTES = 40  # enough for 30-min rolling features


async def _load_1m(db: AsyncSession, observer_id: uuid.UUID | None, hours: int) -> pd.DataFrame:
    where = "AND observer_id = :oid" if observer_id else ""
    rows = await db.execute(
        text(f"""
            SELECT bucket AS ts, cpu_avg AS cpu_pct, mem_avg AS mem_pct, disk_avg AS disk_pct,
                   net_rx_avg AS net_rx_bps, net_tx_avg AS net_tx_bps, load1_avg AS load1
            FROM metrics_1m
            WHERE bucket > now() - make_interval(hours => :hours) {where}
            ORDER BY bucket
        """),
        {"hours": hours} | ({"oid": str(observer_id)} if observer_id else {}),
    )
    return pd.DataFrame(rows.mappings().all())


async def train_and_store(observer_id: uuid.UUID | None, window_hours: int = 168) -> MLModel | None:
    """Train a model for one observer (or the global model when None)."""
    async with get_sessionmaker()() as db:
        df = await _load_1m(db, observer_id, window_hours)
        if len(df) < 60:
            log.info("skipping training for %s: only %d minutes of data", observer_id, len(df))
            return None
        model = await asyncio.to_thread(ml_model.train_model, df)
        artifact_path = ml_model.save_model(model, observer_id)
        # Eval on the labelled synthetic set — precision/recall stored with the model
        report = await asyncio.to_thread(run_eval)
        row = MLModel(
            observer_id=observer_id,
            algo="isolation_forest",
            window_hours=window_hours,
            artifact_path=artifact_path,
            metrics=report,
        )
        db.add(row)
        await db.commit()
        log.info("trained model %s for observer %s", row.id, observer_id or "global")
        return row


async def latest_model(db: AsyncSession, observer_id: uuid.UUID | None) -> MLModel | None:
    q = (
        select(MLModel)
        .where(MLModel.observer_id == observer_id if observer_id else MLModel.observer_id.is_(None))
        .order_by(MLModel.trained_at.desc())
        .limit(1)
    )
    return (await db.execute(q)).scalar_one_or_none()


async def nightly_retrain() -> None:
    """Global model always; per-observer models once they have ≥ 24 h of data."""
    await train_and_store(None)
    async with get_sessionmaker()() as db:
        observers = list((await db.execute(select(Observer))).scalars())
        for obs in observers:
            df = await _load_1m(db, obs.id, hours=25)
            if len(df) >= MIN_TRAIN_MINUTES:
                await train_and_store(obs.id)


_model_cache: dict[str, tuple[str, object]] = {}


async def _pipeline_for(db: AsyncSession, observer_id: uuid.UUID):
    row = await latest_model(db, observer_id) or await latest_model(db, None)
    if row is None:
        return None
    cached = _model_cache.get(str(observer_id))
    if cached and cached[0] == row.artifact_path:
        return cached[1]
    try:
        pipeline = await asyncio.to_thread(ml_model.load_model, row.artifact_path)
    except FileNotFoundError:
        return None
    _model_cache[str(observer_id)] = (row.artifact_path, pipeline)
    return pipeline


async def inference_tick() -> None:
    """Score the newest 1-minute aggregate for every online observer.

    Fires only after CONSECUTIVE_ANOMALOUS_MINUTES minutes below the model's
    calibrated threshold in a row; resolves after N normal minutes in a row.
    """
    s = get_settings()
    redis = get_redis()
    async with get_sessionmaker()() as db:
        observers = list(
            (
                await db.execute(select(Observer).where(Observer.status == ObserverStatus.online))
            ).scalars()
        )
        for obs in observers:
            model = await _pipeline_for(db, obs.id)
            if model is None:
                continue
            df = await _load_1m(db, obs.id, hours=1)
            if len(df) < 5:
                continue
            df = df.tail(INFER_HISTORY_MINUTES)
            scores = await asyncio.to_thread(ml_model.score, model, df)
            latest_score = float(scores[-1])
            anom_key = f"anomaly_streak:{obs.id}"
            normal_key = f"anomaly_normal_streak:{obs.id}"
            if latest_score < model.threshold:
                await redis.delete(normal_key)
                streak = await redis.incr(anom_key)
                if streak >= ml_model.CONSECUTIVE_ANOMALOUS_MINUTES:
                    await fire_alert(
                        db,
                        obs.id,
                        AlertSource.anomaly,
                        Severity.warning,
                        f"anomaly detected on {obs.name}: score {latest_score:.3f} below "
                        f"baseline threshold {model.threshold:.3f} for {streak} min",
                        anomaly_score=latest_score,
                    )
            else:
                await redis.delete(anom_key)
                streak = await redis.incr(normal_key)
                if streak >= s.ml_resolve_after_normal_minutes:
                    active = await find_active_alert(db, obs.id, source=AlertSource.anomaly)
                    if active is not None:
                        await resolve_alert(db, active, reason="anomaly_score_recovered")
        await db.commit()
