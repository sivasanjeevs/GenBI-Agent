"""
llm.py – Unified LLM wrapper with disk caching.

Supports:
  - Google Gemini (default, free tier)
  - OpenAI
  - Anthropic
  - Ollama (local)

All calls go through `call_llm(prompt)` which returns a string.
Responses are cached to disk keyed by SHA-256 of the prompt so
repeated learning runs don't waste quota.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings


# ─── Cache Helpers ────────────────────────────────────────────────────────────

def _cache_key(prompt: str, model: str) -> str:
    h = hashlib.sha256(f"{model}::{prompt}".encode()).hexdigest()
    return h


def _cache_path(key: str) -> Path:
    settings.llm_cache_dir.mkdir(parents=True, exist_ok=True)
    return settings.llm_cache_dir / f"{key}.json"


def _load_cache(key: str) -> str | None:
    if not settings.llm_cache_enabled:
        return None
    p = _cache_path(key)
    if p.exists():
        data = json.loads(p.read_text())
        logger.debug(f"LLM cache hit: {key[:12]}…")
        return data["response"]
    return None


def _save_cache(key: str, response: str) -> None:
    if not settings.llm_cache_enabled:
        return
    _cache_path(key).write_text(
        json.dumps({"response": response, "ts": time.time()}, ensure_ascii=False)
    )


# ─── Provider Implementations ─────────────────────────────────────────────────

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _call_gemini(prompt: str) -> str:
    import google.generativeai as genai  # type: ignore

    genai.configure(api_key=settings.gemini_api_key)
    model = genai.GenerativeModel(
        model_name=settings.llm_model,
        generation_config=genai.GenerationConfig(
            max_output_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
        ),
    )
    response = model.generate_content(prompt)
    return response.text


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _call_openai(prompt: str) -> str:
    from openai import OpenAI  # type: ignore

    client = OpenAI(api_key=settings.openai_api_key)
    resp = client.chat.completions.create(
        model=settings.llm_model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=settings.llm_max_tokens,
        temperature=settings.llm_temperature,
    )
    return resp.choices[0].message.content or ""


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _call_anthropic(prompt: str) -> str:
    import anthropic  # type: ignore

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    msg = client.messages.create(
        model=settings.llm_model,
        max_tokens=settings.llm_max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text  # type: ignore[index]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _call_ollama(prompt: str) -> str:
    import httpx  # type: ignore

    resp = httpx.post(
        f"{settings.ollama_base_url}/api/generate",
        json={
            "model": settings.llm_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": settings.llm_temperature,
                "num_predict": settings.llm_max_tokens,
            },
        },
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.json()["response"]


_PROVIDERS: dict[str, Any] = {
    "gemini": _call_gemini,
    "openai": _call_openai,
    "anthropic": _call_anthropic,
    "ollama": _call_ollama,
}


# ─── Public Interface ─────────────────────────────────────────────────────────

def call_llm(prompt: str, *, bypass_cache: bool = False) -> str:
    """
    Call the configured LLM with `prompt`.

    Args:
        prompt: Full prompt string.
        bypass_cache: If True, skip cache lookup (still writes result).

    Returns:
        LLM response as a string.
    """
    key = _cache_key(prompt, settings.llm_model)

    if not bypass_cache:
        cached = _load_cache(key)
        if cached is not None:
            return cached

    provider_fn = _PROVIDERS.get(settings.llm_provider)
    if provider_fn is None:
        raise ValueError(
            f"Unknown LLM provider '{settings.llm_provider}'. "
            f"Choose from: {list(_PROVIDERS.keys())}"
        )

    logger.info(
        f"LLM call | provider={settings.llm_provider} | model={settings.llm_model} "
        f"| prompt_len={len(prompt)}"
    )
    start = time.perf_counter()
    response = provider_fn(prompt)
    elapsed = (time.perf_counter() - start) * 1000
    logger.info(f"LLM response | len={len(response)} | elapsed={elapsed:.0f}ms")

    _save_cache(key, response)
    return response


def extract_json(response: str) -> Any:
    """
    Extract the first JSON object or array from an LLM response string.
    The LLM often wraps JSON in markdown code fences.
    """
    import re

    # Strip ```json ... ``` fences
    fenced = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", response)
    if fenced:
        text = fenced.group(1)
    else:
        text = response.strip()

    return json.loads(text)
