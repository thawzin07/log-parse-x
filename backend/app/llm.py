from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx


PROMPT_DIR = Path(__file__).with_name("prompts")


class LLMUnavailable(RuntimeError):
    pass


def load_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


async def infer_schema(sample: str, detected_format: str | None = None) -> tuple[str, dict[str, Any]]:
    provider = os.getenv("LLM_PROVIDER", "ollama").lower()
    if provider in {"", "disabled", "none"}:
        raise LLMUnavailable("LLM provider is disabled.")

    prompt = load_prompt("infer_schema.md").format(
        detected_format=detected_format or "unknown",
        sample=sample[:12_000],
    )
    if provider == "ollama":
        return provider, await _ollama(prompt)
    if provider == "openai":
        return provider, await _openai(prompt)
    if provider == "gemini":
        return provider, await _gemini(prompt)
    raise LLMUnavailable(f"Unsupported LLM provider: {provider}")


async def _ollama(prompt: str) -> dict[str, Any]:
    url = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            f"{url}/api/chat",
            json={
                "model": model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": "Return strict JSON only."},
                    {"role": "user", "content": prompt},
                ],
                "format": "json",
            },
        )
        response.raise_for_status()
    content = response.json().get("message", {}).get("content", "{}")
    return _parse_json(content)


async def _openai(prompt: str) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise LLMUnavailable("OPENAI_API_KEY is not configured.")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": "Return strict JSON only."},
                    {"role": "user", "content": prompt},
                ],
            },
        )
        response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return _parse_json(content)


async def _gemini(prompt: str) -> dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise LLMUnavailable("GEMINI_API_KEY is not configured.")
    model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            url,
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json"},
            },
        )
        response.raise_for_status()
    content = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    return _parse_json(content)


def _parse_json(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMUnavailable(f"LLM returned invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LLMUnavailable("LLM returned JSON, but not an object.")
    return parsed
