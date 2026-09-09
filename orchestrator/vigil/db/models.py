import enum
import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ObserverStatus(enum.StrEnum):
    online = "online"
    offline = "offline"
    unknown = "unknown"


class RuleOp(enum.StrEnum):
    gt = "gt"
    lt = "lt"
    gte = "gte"
    lte = "lte"


class Severity(enum.StrEnum):
    info = "info"
    warning = "warning"
    critical = "critical"


class AlertSource(enum.StrEnum):
    rule = "rule"
    anomaly = "anomaly"
    watchdog = "watchdog"  # synthetic observer_down alerts


class AlertState(enum.StrEnum):
    firing = "firing"
    acknowledged = "acknowledged"
    resolved = "resolved"


class AlertEventType(enum.StrEnum):
    fired = "fired"
    acked = "acked"
    resolved = "resolved"
    triaged = "triaged"
    escalated = "escalated"


class BatchStatus(enum.StrEnum):
    pending = "pending"
    anchored = "anchored"
    failed = "failed"


def _enum(e: type[enum.Enum], name: str):
    from sqlalchemy import Enum

    return Enum(e, name=name, values_callable=lambda x: [i.value for i in x])


class Observer(Base):
    __tablename__ = "observers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, unique=True)
    api_key_hash: Mapped[str] = mapped_column(Text)
    labels: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[ObserverStatus] = mapped_column(
        _enum(ObserverStatus, "observer_status"), default=ObserverStatus.unknown
    )


class Metric(Base):
    """TimescaleDB hypertable (converted in the initial migration)."""

    __tablename__ = "metrics"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    observer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    cpu_pct: Mapped[float | None] = mapped_column(Float)
    mem_pct: Mapped[float | None] = mapped_column(Float)
    disk_pct: Mapped[float | None] = mapped_column(Float)
    net_rx_bps: Mapped[int | None] = mapped_column(BigInteger)
    net_tx_bps: Mapped[int | None] = mapped_column(BigInteger)
    load1: Mapped[float | None] = mapped_column(Float)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, unique=True)
    metric: Mapped[str] = mapped_column(Text)
    op: Mapped[RuleOp] = mapped_column(_enum(RuleOp, "rule_op"))
    threshold: Mapped[float] = mapped_column(Float)
    for_seconds: Mapped[int] = mapped_column(Integer, default=0)
    severity: Mapped[Severity] = mapped_column(_enum(Severity, "severity"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    observer_selector: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        # Sentinel parity: one active alert per observer+rule
        Index(
            "uq_active_rule_alert",
            "observer_id",
            "rule_id",
            unique=True,
            postgresql_where=text("state != 'resolved' AND rule_id IS NOT NULL"),
        ),
        # One active anomaly alert per observer
        Index(
            "uq_active_anomaly_alert",
            "observer_id",
            unique=True,
            postgresql_where=text("source = 'anomaly' AND state != 'resolved'"),
        ),
        # One active observer_down alert per observer
        Index(
            "uq_active_watchdog_alert",
            "observer_id",
            unique=True,
            postgresql_where=text("source = 'watchdog' AND state != 'resolved'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    observer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("observers.id", ondelete="CASCADE")
    )
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alert_rules.id", ondelete="SET NULL")
    )
    source: Mapped[AlertSource] = mapped_column(_enum(AlertSource, "alert_source"))
    severity: Mapped[Severity] = mapped_column(_enum(Severity, "severity"))
    state: Mapped[AlertState] = mapped_column(
        _enum(AlertState, "alert_state"), default=AlertState.firing
    )
    fired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[str] = mapped_column(Text, default="")
    anomaly_score: Mapped[float | None] = mapped_column(Float)


class AlertEvent(Base):
    """Append-only lifecycle log — the thing the ledger protects."""

    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    alert_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alerts.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[AlertEventType] = mapped_column(_enum(AlertEventType, "alert_event_type"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    event_hash: Mapped[bytes] = mapped_column(LargeBinary(32))
    prev_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    batch_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ledger_batches.id", ondelete="SET NULL"), index=True
    )


class LedgerBatch(Base):
    __tablename__ = "ledger_batches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    merkle_root: Mapped[bytes] = mapped_column(LargeBinary(32))
    first_event_id: Mapped[int] = mapped_column(BigInteger)
    last_event_id: Mapped[int] = mapped_column(BigInteger)
    tx_hash: Mapped[str | None] = mapped_column(Text)
    chain_id: Mapped[int] = mapped_column(Integer)
    chain_batch_id: Mapped[int | None] = mapped_column(BigInteger)
    block_number: Mapped[int | None] = mapped_column(BigInteger)
    anchored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[BatchStatus] = mapped_column(
        _enum(BatchStatus, "batch_status"), default=BatchStatus.pending
    )


class TriageResult(Base):
    __tablename__ = "triage_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alerts.id", ondelete="CASCADE"), index=True
    )
    model: Mapped[str] = mapped_column(Text)
    hypothesis: Mapped[str] = mapped_column(Text)
    suggested_runbook: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class MLModel(Base):
    __tablename__ = "ml_models"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    observer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("observers.id", ondelete="CASCADE")
    )
    algo: Mapped[str] = mapped_column(Text, default="isolation_forest")
    trained_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    window_hours: Mapped[int] = mapped_column(Integer, default=168)
    artifact_path: Mapped[str] = mapped_column(Text)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class RunbookChunk(Base):
    """Chunked + embedded runbooks for triage retrieval (pgvector)."""

    __tablename__ = "runbook_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    runbook: Mapped[str] = mapped_column(Text, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(768))
    embedder: Mapped[str] = mapped_column(Text, default="local")
