"""Runbook indexing + retrieval (pgvector).

Markdown runbooks in runbooks/ are chunked by ## headings (~1200 chars max),
embedded, and stored in runbook_chunks. Reindexed at startup when the folder
content or the active embedder changes.
"""

import logging
import re
from pathlib import Path

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from vigil.core.config import get_settings
from vigil.db.models import RunbookChunk
from vigil.triage.embeddings import get_embedder

log = logging.getLogger(__name__)

MAX_CHUNK_CHARS = 1200


def chunk_markdown(content: str) -> list[str]:
    """Split on ## headings, then hard-wrap oversized sections."""
    sections = re.split(r"(?m)^(?=## )", content)
    chunks: list[str] = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        while len(section) > MAX_CHUNK_CHARS:
            cut = section.rfind("\n", 0, MAX_CHUNK_CHARS)
            cut = cut if cut > 200 else MAX_CHUNK_CHARS
            chunks.append(section[:cut].strip())
            section = section[cut:].strip()
        if section:
            chunks.append(section)
    return chunks


async def index_runbooks(db: AsyncSession, force: bool = False) -> int:
    runbook_dir = Path(get_settings().runbooks_dir)
    if not runbook_dir.is_dir():
        log.warning("runbooks dir %s missing — triage retrieval will be empty", runbook_dir)
        return 0
    embedder = get_embedder()
    existing = (
        await db.execute(select(RunbookChunk.embedder).distinct())
    ).scalars().all()
    count = (await db.execute(select(text("count(*)")).select_from(RunbookChunk))).scalar()
    if not force and count and existing == [embedder.name]:
        return int(count)

    await db.execute(delete(RunbookChunk))
    total = 0
    for path in sorted(runbook_dir.glob("*.md")):
        chunks = chunk_markdown(path.read_text(encoding="utf-8"))
        vectors = await embedder.embed(chunks)
        for i, (chunk, vec) in enumerate(zip(chunks, vectors, strict=True)):
            db.add(
                RunbookChunk(
                    runbook=path.stem, chunk_index=i, content=chunk,
                    embedding=vec, embedder=embedder.name,
                )
            )
        total += len(chunks)
    await db.commit()
    log.info("indexed %d runbook chunks with %s", total, embedder.name)
    return total


async def retrieve_chunks(db: AsyncSession, query: str, k: int = 3) -> list[RunbookChunk]:
    embedder = get_embedder()
    qvec = (await embedder.embed([query]))[0]
    rows = await db.execute(
        select(RunbookChunk)
        .order_by(RunbookChunk.embedding.cosine_distance(qvec))
        .limit(k)
    )
    return list(rows.scalars())
