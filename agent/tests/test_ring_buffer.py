import json

from vigil_agent.transport import RingBuffer


def _samples(n, start=0):
    return [{"ts": f"t{i}", "cpu_pct": float(i)} for i in range(start, start + n)]


def test_push_and_drain_fifo(tmp_path):
    buf = RingBuffer(tmp_path / "buffer.json", size=10)
    buf.push(_samples(3))
    out = buf.drain(2)
    assert [s["ts"] for s in out] == ["t0", "t1"]
    assert len(buf) == 1


def test_ring_overflow_drops_oldest(tmp_path):
    buf = RingBuffer(tmp_path / "buffer.json", size=5)
    buf.push(_samples(8))
    assert len(buf) == 5
    assert buf.drain(5)[0]["ts"] == "t3"


def test_persistence_across_restart(tmp_path):
    path = tmp_path / "buffer.json"
    RingBuffer(path, size=10).push(_samples(4))
    revived = RingBuffer(path, size=10)
    assert len(revived) == 4
    assert revived.drain(1)[0]["ts"] == "t0"


def test_requeue_front_preserves_order(tmp_path):
    buf = RingBuffer(tmp_path / "buffer.json", size=10)
    buf.push(_samples(5))
    batch = buf.drain(3)
    buf.requeue_front(batch)
    assert [s["ts"] for s in buf.drain(5)] == ["t0", "t1", "t2", "t3", "t4"]


def test_corrupt_buffer_file_starts_empty(tmp_path):
    path = tmp_path / "buffer.json"
    path.write_text("{not json!!")
    buf = RingBuffer(path, size=10)
    assert len(buf) == 0
    buf.push(_samples(1))
    assert json.loads(path.read_text())[0]["ts"] == "t0"
