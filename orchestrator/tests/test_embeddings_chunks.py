import math

from vigil.triage.embeddings import DIM, LocalHashEmbedder
from vigil.triage.runbooks import MAX_CHUNK_CHARS, chunk_markdown


async def test_local_embedder_deterministic_and_normalised():
    e = LocalHashEmbedder()
    v1, v2 = await e.embed(["memory leak ramp", "memory leak ramp"])
    assert v1 == v2
    assert len(v1) == DIM
    assert math.isclose(sum(x * x for x in v1), 1.0, rel_tol=1e-6)


async def test_local_embedder_similarity_orders_sensibly():
    e = LocalHashEmbedder()
    query, related, unrelated = await e.embed(
        [
            "memory usage ramping steadily leak",
            "memory leak: slow monotonic memory growth ends in OOM",
            "network saturation rx tx throughput flood",
        ]
    )
    def cos(a, b):
        return sum(x * y for x, y in zip(a, b, strict=True))

    assert cos(query, related) > cos(query, unrelated)


def test_chunk_markdown_splits_on_headings():
    md = "# Title\nintro\n\n## Diagnose\nsteps here\n\n## Mitigate\nfix it"
    chunks = chunk_markdown(md)
    assert len(chunks) == 3
    assert chunks[1].startswith("## Diagnose")


def test_chunk_markdown_respects_max_size():
    md = "## Big\n" + ("word " * 2000)
    chunks = chunk_markdown(md)
    assert all(len(c) <= MAX_CHUNK_CHARS for c in chunks)
    assert len(chunks) > 1


def test_chunk_markdown_empty():
    assert chunk_markdown("") == []
    assert chunk_markdown("\n\n") == []
