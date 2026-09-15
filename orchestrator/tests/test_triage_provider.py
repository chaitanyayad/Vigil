"""Triage provider tests with recorded/mocked Gemini responses — no network."""

import json

import httpx
import pytest
import respx  # type: ignore[import-not-found]

pytest.importorskip("respx", reason="respx not installed")

from vigil.triage.provider import (  # noqa: E402
    GEMINI_BASE,
    GeminiProvider,
    NullProvider,
    TriageError,
)

RECORDED_OK = {
    "candidates": [
        {
            "content": {
                "parts": [
                    {
                        "text": json.dumps(
                            {
                                "hypothesis": "A process on the host is leaking memory; RSS has "
                                "ramped linearly for 40 minutes.",
                                "confidence": 0.82,
                                "suggested_runbook": "memory-leak",
                                "next_steps": [
                                    "Identify the process with ps aux --sort=-%mem",
                                    "Schedule a rolling restart before projected OOM",
                                ],
                            }
                        )
                    }
                ]
            }
        }
    ],
    "usageMetadata": {"promptTokenCount": 900, "candidatesTokenCount": 120},
    "modelVersion": "gemini-2.5-flash",
}


@respx.mock
async def test_gemini_parses_recorded_response():
    provider = GeminiProvider(api_key="test-key", model="gemini-2.5-flash")
    respx.post(f"{GEMINI_BASE}/models/gemini-2.5-flash:generateContent").mock(
        return_value=httpx.Response(200, json=RECORDED_OK)
    )
    output, raw = await provider.triage("memory ramping on host-1")
    assert output.suggested_runbook == "memory-leak"
    assert output.confidence > 0.7
    assert "leaking memory" in output.hypothesis
    assert raw["usageMetadata"]["promptTokenCount"] == 900


@respx.mock
async def test_gemini_http_error_raises_triage_error():
    provider = GeminiProvider(api_key="bad-key")
    respx.post(url__startswith=GEMINI_BASE).mock(
        return_value=httpx.Response(429, json={"error": {"message": "quota exceeded"}})
    )
    with pytest.raises(TriageError, match="429"):
        await provider.triage("x")


@respx.mock
async def test_gemini_malformed_json_raises():
    provider = GeminiProvider(api_key="k")
    respx.post(url__startswith=GEMINI_BASE).mock(
        return_value=httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}
        )
    )
    with pytest.raises(TriageError, match="Unparseable"):
        await provider.triage("x")


@respx.mock
async def test_gemini_out_of_range_confidence_rejected():
    bad = json.loads(json.dumps(RECORDED_OK))
    bad["candidates"][0]["content"]["parts"][0]["text"] = json.dumps(
        {"hypothesis": "h", "confidence": 1.7, "suggested_runbook": "x", "next_steps": []}
    )
    provider = GeminiProvider(api_key="k")
    respx.post(url__startswith=GEMINI_BASE).mock(return_value=httpx.Response(200, json=bad))
    with pytest.raises(TriageError):
        await provider.triage("x")


async def test_null_provider_disabled():
    p = NullProvider()
    assert not p.enabled
    with pytest.raises(TriageError, match="disabled"):
        await p.triage("x")
