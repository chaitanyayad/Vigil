"""LLM providers for incident triage.

Default is Google Gemini (free tier via AI Studio — https://aistudio.google.com/apikey),
called over plain REST with httpx so there's no SDK dependency. A NullProvider
keeps the feature gracefully disabled when no key is configured, and an
OllamaProvider stub marks where a local model would slot in.
"""

import json
import logging
from typing import Protocol

import httpx
from pydantic import BaseModel, Field, ValidationError

from vigil.core.config import get_settings

log = logging.getLogger(__name__)

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

TRIAGE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "hypothesis": {"type": "string"},
        "confidence": {"type": "number"},
        "suggested_runbook": {"type": "string"},
        "next_steps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["hypothesis", "confidence", "suggested_runbook", "next_steps"],
}


class TriageOutput(BaseModel):
    hypothesis: str
    confidence: float = Field(ge=0.0, le=1.0)
    suggested_runbook: str
    next_steps: list[str] = Field(default_factory=list)


class TriageError(Exception):
    pass


class LLMProvider(Protocol):
    name: str
    enabled: bool

    async def triage(self, prompt: str) -> tuple[TriageOutput, dict]:
        """Returns (validated output, raw response). Raises TriageError."""
        ...


class GeminiProvider:
    def __init__(self, api_key: str, model: str | None = None) -> None:
        s = get_settings()
        self.api_key = api_key
        self.model = model or s.gemini_model
        self.name = f"gemini/{self.model}"
        self.enabled = bool(api_key)
        self._timeout = s.triage_timeout_seconds
        self._max_tokens = s.triage_max_output_tokens

    async def triage(self, prompt: str) -> tuple[TriageOutput, dict]:
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": TRIAGE_JSON_SCHEMA,
                "maxOutputTokens": self._max_tokens,
                "temperature": 0.2,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{GEMINI_BASE}/models/{self.model}:generateContent",
                    headers={"x-goog-api-key": self.api_key},
                    json=body,
                )
        except httpx.HTTPError as e:
            raise TriageError(f"Gemini request failed: {e}") from e
        if resp.status_code != 200:
            raise TriageError(f"Gemini HTTP {resp.status_code}: {resp.text[:500]}")
        raw = resp.json()
        try:
            text = raw["candidates"][0]["content"]["parts"][0]["text"]
            output = TriageOutput.model_validate(json.loads(text))
        except (KeyError, IndexError, json.JSONDecodeError, ValidationError) as e:
            raise TriageError(f"Unparseable Gemini response: {e}") from e
        return output, raw


class NullProvider:
    """Used when GEMINI_API_KEY is unset — triage is disabled, not broken."""

    name = "null"
    enabled = False

    async def triage(self, prompt: str) -> tuple[TriageOutput, dict]:
        raise TriageError("LLM triage disabled: no GEMINI_API_KEY configured")


class OllamaProvider:
    """Stub for a local model (future work): point at an Ollama server and
    implement triage() with /api/chat + format=json."""

    name = "ollama"
    enabled = False

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3.1") -> None:
        raise NotImplementedError("OllamaProvider is a stub for v1")


def get_provider() -> LLMProvider:
    s = get_settings()
    if s.gemini_api_key:
        return GeminiProvider(s.gemini_api_key)
    return NullProvider()
