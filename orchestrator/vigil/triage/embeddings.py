"""Embeddings for runbook retrieval.

GeminiEmbedder uses the free-tier embedding endpoint; LocalHashEmbedder is a
deterministic character-n-gram hashing embedder used when no API key is set,
so retrieval (and its tests) work fully offline. Both produce L2-normalised
768-dim vectors; docs and queries must always use the same embedder — the
chunk rows record which one indexed them.
"""

import hashlib
import math

import httpx

from vigil.core.config import get_settings
from vigil.triage.provider import GEMINI_BASE

DIM = 768


def _l2(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class LocalHashEmbedder:
    name = "local-hash-v1"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        vec = [0.0] * DIM
        tokens = text.lower().split()
        grams = tokens + [" ".join(p) for p in zip(tokens, tokens[1:], strict=False)]
        for gram in grams:
            digest = hashlib.md5(gram.encode()).digest()
            idx = int.from_bytes(digest[:4], "big") % DIM
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign
        return _l2(vec)


class GeminiEmbedder:
    def __init__(self, api_key: str, model: str | None = None) -> None:
        self.api_key = api_key
        self.model = model or get_settings().gemini_embed_model
        self.name = f"gemini/{self.model}"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            for text in texts:
                resp = await client.post(
                    f"{GEMINI_BASE}/models/{self.model}:embedContent",
                    headers={"x-goog-api-key": self.api_key},
                    json={
                        "content": {"parts": [{"text": text[:8000]}]},
                        "outputDimensionality": DIM,
                    },
                )
                resp.raise_for_status()
                # Truncated-dim Gemini embeddings are not pre-normalised
                out.append(_l2(resp.json()["embedding"]["values"]))
        return out


def get_embedder():
    s = get_settings()
    if s.gemini_api_key:
        return GeminiEmbedder(s.gemini_api_key)
    return LocalHashEmbedder()
