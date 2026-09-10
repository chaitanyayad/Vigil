import uuid
from datetime import UTC, datetime, timedelta

from vigil.ledger.hashing import canonical_event_bytes, compute_event_hash


def test_canonical_bytes_deterministic():
    alert_id = uuid.uuid4()
    ts = datetime.now(UTC)
    a = canonical_event_bytes(alert_id, "fired", {"b": 2, "a": 1}, ts)
    b = canonical_event_bytes(alert_id, "fired", {"a": 1, "b": 2}, ts)
    assert a == b  # key order must not matter


def test_hash_changes_with_any_field():
    alert_id = uuid.uuid4()
    ts = datetime.now(UTC)
    base = compute_event_hash(alert_id, "fired", {"x": 1}, ts, None)
    assert compute_event_hash(alert_id, "acked", {"x": 1}, ts, None) != base
    assert compute_event_hash(alert_id, "fired", {"x": 2}, ts, None) != base
    assert compute_event_hash(alert_id, "fired", {"x": 1}, ts + timedelta(microseconds=1), None) != base
    assert compute_event_hash(uuid.uuid4(), "fired", {"x": 1}, ts, None) != base


def test_hash_chains_on_prev():
    alert_id = uuid.uuid4()
    ts = datetime.now(UTC)
    h1 = compute_event_hash(alert_id, "fired", {}, ts, None)
    h2a = compute_event_hash(alert_id, "resolved", {}, ts, h1)
    h2b = compute_event_hash(alert_id, "resolved", {}, ts, b"\x01" * 32)
    assert h2a != h2b


def test_hash_is_32_bytes():
    assert len(compute_event_hash(uuid.uuid4(), "fired", {}, datetime.now(UTC), None)) == 32


def test_timezone_normalisation():
    """Same instant in different tz representations must hash identically."""
    from datetime import timezone

    alert_id = uuid.uuid4()
    ts_utc = datetime(2026, 9, 17, 12, 0, 0, tzinfo=UTC)
    ts_ist = ts_utc.astimezone(timezone(timedelta(hours=5, minutes=30)))
    assert compute_event_hash(alert_id, "fired", {}, ts_utc, None) == compute_event_hash(
        alert_id, "fired", {}, ts_ist, None
    )
