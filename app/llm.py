"""
llm.py – Resilient Gemini LLM wrapper with structured output and disk cache.

Architecture
────────────
• Uses the *new* ``google-genai`` SDK (``google.genai``), not the legacy
  ``google-generativeai`` package.
• Enforces temperature=0 for deterministic, analytical output.
• response_schema forces JSON output that maps to a caller-supplied
  Pydantic model – no markdown parsing required.
• Disk cache keyed by SHA-256(model_name + prompt + schema_name) avoids
  redundant API calls during iterative development and eval runs.
• tenacity retry with exponential back-off on HTTP 429 / 5xx errors.
• Automatic model fallback: if LLM_MODEL repeatedly exhausts its retries,
  the call is retried once on LLM_MODEL_FAST.
• Single validation-error retry: if the response does not parse against
  the schema, the validation error is appended to the prompt and one more
  attempt is made.

Public API
──────────
    call_llm_structured(prompt, response_model) -> T  (structured path)
    call_llm(prompt)                                  -> str  (plain-text path)
    extract_json(response)                            -> Any  (legacy helper)
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from loguru import logger
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings

if TYPE_CHECKING:
    from pydantic import BaseModel

T = TypeVar("T", bound="BaseModel")


# ─── SDK Import ───────────────────────────────────────────────────────────────

def _get_genai_client():  # type: ignore[return]
    """Lazily import and configure the google-genai client."""
    try:
        from google import genai  # type: ignore[import-untyped]
        from google.genai import types as genai_types  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "google-genai is not installed. "
            "Run: pip install google-genai"
        ) from exc

    if not settings.gemini_api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. "
            "Add it to your .env file or environment."
        )

    client = genai.Client(api_key=settings.gemini_api_key)
    return client, genai_types


# ─── Disk Cache ───────────────────────────────────────────────────────────────

def _cache_key(model: str, prompt: str, schema_name: str) -> str:
    """SHA-256 hash of (model, prompt, schema_name) for cache keying."""
    raw = f"{model}::{schema_name}::{prompt}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_path(key: str) -> Path:
    settings.llm_cache_dir.mkdir(parents=True, exist_ok=True)
    return settings.llm_cache_dir / f"{key}.json"


def _load_cache(key: str) -> str | None:
    """Return cached response text, or None if not present / disabled."""
    if not settings.llm_cache_enabled:
        return None
    p = _cache_path(key)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            logger.debug("LLM cache hit: {}…", key[:12])
            return data["response"]
        except (json.JSONDecodeError, KeyError):
            logger.warning("Corrupt cache file {}; ignoring.", p)
    return None


def _save_cache(key: str, response: str) -> None:
    """Persist response text to disk cache."""
    if not settings.llm_cache_enabled:
        return
    _cache_path(key).write_text(
        json.dumps(
            {"response": response, "ts": time.time()},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


# ─── Retry Logic ──────────────────────────────────────────────────────────────

def _is_retryable(exc: BaseException) -> bool:
    """
    Decide if an exception warrants a retry.

    We retry on:
    • HTTP 429  (quota / rate-limit)
    • HTTP 5xx  (transient server errors)
    """
    msg = str(exc).lower()
    # google-genai raises google.api_core.exceptions or similar;
    # we also capture raw HTTP status strings from the SDK.
    if "429" in msg or "quota" in msg or "resource_exhausted" in msg:
        return True
    if any(code in msg for code in ("500", "502", "503", "504")):
        return True
    return False


def _log_retry(retry_state: RetryCallState) -> None:
    logger.warning(
        "LLM retry #{} after error: {}",
        retry_state.attempt_number,
        retry_state.outcome.exception() if retry_state.outcome else "unknown",
    )


_RETRY_POLICY = dict(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    before_sleep=_log_retry,
    reraise=True,
)


# ─── Core Gemini Caller ───────────────────────────────────────────────────────

@retry(**_RETRY_POLICY)  # type: ignore[arg-type]
def _call_gemini_raw(
    prompt: str,
    model: str,
    response_schema: type | None = None,
) -> str:
    """
    Call the Gemini API with structured or plain-text output.

    Args:
        prompt:          Full prompt string.
        model:           Gemini model identifier (e.g. "gemini-2.0-flash").
        response_schema: Optional Pydantic model class; when provided the API
                         is asked to return JSON conforming to that schema.

    Returns:
        Raw response text (JSON string when response_schema is set).
    """
    client, genai_types = _get_genai_client()

    generation_config_kwargs: dict[str, Any] = {
        "temperature": 0.0,
        "max_output_tokens": settings.llm_max_tokens,
    }
    if response_schema is not None:
        generation_config_kwargs["response_mime_type"] = "application/json"
        generation_config_kwargs["response_schema"] = response_schema

    config = genai_types.GenerateContentConfig(**generation_config_kwargs)

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=config,
    )

    # SDK guarantees .text when response_mime_type is application/json
    return response.text


# ─── Structured Output (primary public API) ───────────────────────────────────

def call_llm_structured(
    prompt: str,
    response_model: type[T],
    *,
    bypass_cache: bool = False,
) -> T:
    """
    Call Gemini with a structured schema and return a validated Pydantic model.

    Resilience strategy:
    1. Retry primary model (LLM_MODEL) up to 4× on 429/5xx with back-off.
    2. If all retries fail, fall back to LLM_MODEL_FAST and retry once.
    3. If the returned JSON fails Pydantic validation, append the error to
       the prompt and make one additional attempt.

    Args:
        prompt:         Full prompt string.
        response_model: Pydantic model class describing expected JSON shape.
        bypass_cache:   Skip cache lookup (result is still written to cache).

    Returns:
        An instance of ``response_model``.

    Raises:
        RuntimeError – if all attempts fail.
        ValueError   – if JSON validation fails on both attempts.
    """
    schema_name = response_model.__name__
    primary_model = settings.llm_model
    fast_model = settings.llm_model_fast

    cache_key = _cache_key(primary_model, prompt, schema_name)

    # ── Cache check ──────────────────────────────────────────────────────────
    if not bypass_cache:
        cached = _load_cache(cache_key)
        if cached is not None:
            return _parse_response(cached, response_model)

    # ── Attempt with primary model ───────────────────────────────────────────
    raw: str | None = None
    model_used = primary_model

    logger.info(
        "LLM structured call | model={} | schema={} | prompt_len={}",
        primary_model,
        schema_name,
        len(prompt),
    )
    start = time.perf_counter()

    try:
        raw = _call_gemini_raw(prompt, model=primary_model, response_schema=response_model)
    except Exception as primary_exc:  # noqa: BLE001
        logger.error(
            "Primary model {} failed after retries: {}",
            primary_model,
            primary_exc,
        )
        # ── Fallback to fast model ───────────────────────────────────────────
        if fast_model and fast_model != primary_model:
            logger.warning("Falling back to fast model: {}", fast_model)
            model_used = fast_model
            try:
                raw = _call_gemini_raw(
                    prompt, model=fast_model, response_schema=response_model
                )
            except Exception as fast_exc:  # noqa: BLE001
                raise RuntimeError(
                    f"Both primary ({primary_model}) and fast ({fast_model}) "
                    f"models failed. Last error: {fast_exc}"
                ) from fast_exc
        else:
            raise RuntimeError(
                f"Primary model {primary_model} failed and no fallback configured. "
                f"Error: {primary_exc}"
            ) from primary_exc

    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "LLM response | model={} | len={} | elapsed={:.0f}ms",
        model_used,
        len(raw or ""),
        elapsed_ms,
    )

    # ── Validation with one-shot repair ─────────────────────────────────────
    try:
        result = _parse_response(raw, response_model)
    except (json.JSONDecodeError, ValueError) as val_err:
        logger.warning(
            "Validation error on first attempt ({}); retrying with error context.",
            val_err,
        )
        repair_prompt = (
            f"{prompt}\n\n"
            f"---\n"
            f"Your previous response failed validation with this error:\n"
            f"{val_err}\n\n"
            f"Please correct your response so it strictly matches the JSON schema "
            f"for `{schema_name}`."
        )
        try:
            raw = _call_gemini_raw(
                repair_prompt, model=model_used, response_schema=response_model
            )
            result = _parse_response(raw, response_model)
        except Exception as repair_exc:  # noqa: BLE001
            raise ValueError(
                f"LLM returned invalid JSON/schema after repair attempt. "
                f"Error: {repair_exc}"
            ) from repair_exc

    _save_cache(cache_key, raw)
    return result


def _parse_response(raw: str, response_model: type[T]) -> T:
    """Parse and validate *raw* JSON text against *response_model*."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM returned non-JSON response: {exc}") from exc
    return response_model.model_validate(data)


# ─── Plain-text Path (backwards-compatible) ───────────────────────────────────

def call_llm(prompt: str, *, bypass_cache: bool = False) -> str:
    """
    Call the configured LLM provider and return a plain-text response.

    Supports the legacy multi-provider dispatch (Gemini / OpenAI / Anthropic /
    Ollama) via settings.llm_provider.  For new code, prefer
    ``call_llm_structured``.

    Args:
        prompt:       Full prompt string.
        bypass_cache: If True, skip cache lookup (still writes result).

    Returns:
        LLM response as a string.
    """
    model = settings.llm_model
    key = _cache_key(model, prompt, "plain")

    if not bypass_cache:
        cached = _load_cache(key)
        if cached is not None:
            return cached

    provider = settings.llm_provider
    logger.info(
        "LLM call | provider={} | model={} | prompt_len={}",
        provider,
        model,
        len(prompt),
    )
    start = time.perf_counter()

    if provider == "gemini":
        response = _call_gemini_raw(prompt, model=model)
    elif provider == "openai":
        response = _call_openai(prompt)
    elif provider == "anthropic":
        response = _call_anthropic(prompt)
    elif provider == "ollama":
        response = _call_ollama(prompt)
    else:
        raise ValueError(
            f"Unknown LLM provider '{provider}'. "
            f"Choose from: gemini, openai, anthropic, ollama"
        )

    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info("LLM response | len={} | elapsed={:.0f}ms", len(response), elapsed_ms)

    _save_cache(key, response)
    return response


# ─── Legacy Provider Shims ────────────────────────────────────────────────────

@retry(**_RETRY_POLICY)  # type: ignore[arg-type]
def _call_openai(prompt: str) -> str:
    from openai import OpenAI  # type: ignore[import-untyped]

    client = OpenAI(api_key=settings.openai_api_key)
    resp = client.chat.completions.create(
        model=settings.llm_model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=settings.llm_max_tokens,
        temperature=0.0,
    )
    return resp.choices[0].message.content or ""


@retry(**_RETRY_POLICY)  # type: ignore[arg-type]
def _call_anthropic(prompt: str) -> str:
    import anthropic  # type: ignore[import-untyped]

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    msg = client.messages.create(
        model=settings.llm_model,
        max_tokens=settings.llm_max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text  # type: ignore[index]


@retry(**_RETRY_POLICY)  # type: ignore[arg-type]
def _call_ollama(prompt: str) -> str:
    import httpx  # type: ignore[import-untyped]

    resp = httpx.post(
        f"{settings.ollama_base_url}/api/generate",
        json={
            "model": settings.llm_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.0,
                "num_predict": settings.llm_max_tokens,
            },
        },
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.json()["response"]


# ─── JSON Extraction Helper (legacy) ─────────────────────────────────────────

def extract_json(response: str) -> Any:
    """
    Extract the first JSON object or array from an LLM response string.

    The LLM often wraps JSON in markdown code fences; this strips them.
    Prefer ``call_llm_structured`` for new code – it guarantees valid JSON
    via ``response_schema`` without needing manual extraction.
    """
    import re

    fenced = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", response)
    text = fenced.group(1) if fenced else response.strip()
    return json.loads(text)
