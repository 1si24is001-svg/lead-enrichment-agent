"""
app/extract/llm.py
==================
Provider-agnostic LLM client adapter.

Design
------
One interface (LLMClient Protocol), two concrete implementations:

    OpenAIClient  — uses response_format json_schema for guaranteed JSON.
    GeminiClient  — uses responseSchema from google-genai SDK.

Selected by LLM_PROVIDER env var; overridable with --provider CLI flag.
Temperature is always 0 (extraction, not generation).

One LLM call is made per domain — not per page.  All cleaned pages are
concatenated into one user message separated by ### SOURCE: <url> headers.
This is a deliberate architectural decision documented in docs/DECISIONS.md.

Validation loop
---------------
Parse LLM output into CompanyRecord sub-models.  On ValidationError, retry
once with the validation error appended to the user message.  Max 2 attempts.
On second failure: return None, log an ErrorRecord, and let the fallback
regex extractor take over.

Pricing
-------
Per-1M-token prices live in config.py::TOKEN_PRICES so cost logging works
for any provider and is easy to update.
"""

from __future__ import annotations

import json
import logging
from typing import Protocol, runtime_checkable

from app.config import Settings
from app.crawler.cache import LLMCache
from app.extract.prompts import SYSTEM_PROMPT, EXTRACTION_SCHEMA, PROMPT_VERSION, build_user_message
from app.models import LLMResponse, ErrorRecord, RunStats

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol (the interface every provider must implement)
# ---------------------------------------------------------------------------

@runtime_checkable
class LLMClient(Protocol):
    """Provider-agnostic LLM completion interface."""

    def complete_json(self, system: str, user: str, schema: dict) -> LLMResponse:
        """Make a structured JSON completion call.

        Parameters
        ----------
        system:
            System prompt text.
        user:
            User message text (the concatenated page content).
        schema:
            JSON Schema dict that the response must conform to.

        Returns
        -------
        LLMResponse
            Parsed data dict plus token counts and raw response.
        """
        ...


# ---------------------------------------------------------------------------
# OpenAI implementation
# ---------------------------------------------------------------------------

class OpenAIClient:
    """LLMClient backed by the OpenAI chat completions API.

    Uses ``response_format={"type": "json_schema", ...}`` for guaranteed JSON.
    Falls back to json_object mode if the model does not support json_schema.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = None  # lazy-initialised to avoid import cost

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.settings.openai_api_key)
        return self._client

    def complete_json(self, system: str, user: str, schema: dict) -> LLMResponse:
        client = self._get_client()
        model = self.settings.openai_model

        # Try structured JSON schema output first
        try:
            resp = client.chat.completions.create(
                model=model,
                temperature=0,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "company_extraction",
                        "strict": True,
                        "schema": schema,
                    },
                },
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        except Exception:
            # Fall back to json_object mode for older models
            resp = client.chat.completions.create(
                model=model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )

        raw = resp.choices[0].message.content or ""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}

        return LLMResponse(
            data=data,
            prompt_tokens=resp.usage.prompt_tokens if resp.usage else 0,
            completion_tokens=resp.usage.completion_tokens if resp.usage else 0,
            model=model,
            raw=raw,
        )


# ---------------------------------------------------------------------------
# Gemini implementation
# ---------------------------------------------------------------------------

class GeminiClient:
    """LLMClient backed by the Google Generative AI (Gemini) API."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = None  # lazy-initialised

    def _get_client(self):
        if self._client is None:
            try:
                from google import genai
                self._client = ("genai", genai.Client(api_key=self.settings.gemini_api_key))
            except ImportError:
                import google.generativeai as genai_old
                genai_old.configure(api_key=self.settings.gemini_api_key)
                self._client = (
                    "old",
                    genai_old.GenerativeModel(
                        model_name=self.settings.gemini_model,
                        generation_config={
                            "temperature": 0,
                            "response_mime_type": "application/json",
                        },
                    ),
                )
        return self._client

    def complete_json(self, system: str, user: str, schema: dict) -> LLMResponse:
        client_type, client_obj = self._get_client()
        prompt_tokens = 0
        completion_tokens = 0

        if client_type == "genai":
            from google.genai import types
            config = types.GenerateContentConfig(
                system_instruction=system,
                temperature=0,
                response_mime_type="application/json",
            )
            response = client_obj.models.generate_content(
                model=self.settings.gemini_model,
                contents=user,
                config=config,
            )
            raw = response.text or ""
            try:
                usage = response.usage_metadata
                prompt_tokens = usage.prompt_token_count or 0
                completion_tokens = usage.candidates_token_count or 0
            except Exception:
                pass
        else:
            combined = f"{system}\n\n{user}"
            response = client_obj.generate_content(combined)
            raw = response.text or ""
            try:
                usage = response.usage_metadata
                prompt_tokens = usage.prompt_token_count or 0
                completion_tokens = usage.candidates_token_count or 0
            except Exception:
                pass

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}

        return LLMResponse(
            data=data,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model=self.settings.gemini_model,
            raw=raw,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_llm_client(settings: Settings) -> "LLMClient":
    """Return the appropriate LLMClient for the configured provider."""
    if settings.llm_provider == "openai":
        return OpenAIClient(settings)
    elif settings.llm_provider == "gemini":
        return GeminiClient(settings)
    else:
        raise ValueError(
            f"Unknown LLM provider: {settings.llm_provider!r}. Choose 'openai' or 'gemini'."
        )


# ---------------------------------------------------------------------------
# Domain-level extraction call (called from pipeline.py)
# ---------------------------------------------------------------------------

def call_llm(
    domain: str,
    cleaned_pages: dict[str, str],
    settings: Settings,
    *,
    replay: bool,
    no_cache: bool,
    stats: RunStats,
    errors: list[ErrorRecord],
) -> dict | None:
    """Build the prompt from all cleaned pages and call the LLM once.

    Applies the validation retry loop.  Returns a parsed dict (to be
    assembled into CompanyRecord sub-models by pipeline.py), or None if
    both attempts fail.
    """
    if not cleaned_pages:
        errors.append(ErrorRecord(
            stage="llm",
            url=None,
            error_type="NoPagesAvailable",
            message="No cleaned page content available for LLM extraction.",
            recoverable=False,
        ))
        return None

    llm_cache = LLMCache(settings.cache_dir)
    user_message = build_user_message(cleaned_pages)
    cache_key_prompt = f"{PROMPT_VERSION}|{user_message}"

    # Check LLM cache
    if not no_cache:
        cached = (
            llm_cache.require(settings.llm_provider, settings.active_model(), cache_key_prompt)
            if replay
            else llm_cache.get(settings.llm_provider, settings.active_model(), cache_key_prompt)
        )
        if cached:
            logger.info("[llm] %s: serving LLM response from cache", domain)
            stats.cache_hits += 1
            stats.prompt_tokens += cached.get("prompt_tokens", 0)
            stats.completion_tokens += cached.get("completion_tokens", 0)
            stats.estimated_cost_usd += settings.estimate_cost(
                cached.get("prompt_tokens", 0),
                cached.get("completion_tokens", 0),
            )
            return cached.get("data")

    if replay:
        # replay + no cache hit → error already raised by require(), but handle gracefully
        errors.append(ErrorRecord(
            stage="llm",
            url=None,
            error_type="CacheMiss",
            message=f"--replay mode: no cached LLM response for {domain}",
            recoverable=False,
        ))
        return None

    client = get_llm_client(settings)
    last_user_message = user_message

    for attempt in range(settings.llm_max_attempts):
        try:
            logger.info("[llm] %s: calling %s (attempt %d)", domain, settings.active_model(), attempt + 1)
            response = client.complete_json(
                system=SYSTEM_PROMPT,
                user=last_user_message,
                schema=EXTRACTION_SCHEMA,
            )

            # Accumulate tokens
            stats.prompt_tokens += response.prompt_tokens
            stats.completion_tokens += response.completion_tokens
            stats.estimated_cost_usd += settings.estimate_cost(
                response.prompt_tokens, response.completion_tokens
            )

            # Basic validation: must be a dict
            if not isinstance(response.data, dict):
                raise ValueError(f"LLM returned non-dict: {type(response.data)}")

            # Cache the successful response
            cache_payload = {
                "data": response.data,
                "prompt_tokens": response.prompt_tokens,
                "completion_tokens": response.completion_tokens,
                "model": response.model,
            }
            llm_cache.put(settings.llm_provider, settings.active_model(), cache_key_prompt, cache_payload)

            logger.info(
                "[llm] %s: extraction complete (%d prompt + %d completion tokens)",
                domain, response.prompt_tokens, response.completion_tokens,
            )
            return response.data

        except Exception as exc:  # noqa: BLE001
            error_type = type(exc).__name__
            logger.warning("[llm] %s attempt %d failed: %s: %s", domain, attempt + 1, error_type, exc)

            if attempt + 1 < settings.llm_max_attempts:
                # Append validation error and retry
                last_user_message = (
                    f"{user_message}\n\n"
                    f"### VALIDATION ERROR FROM PREVIOUS ATTEMPT\n"
                    f"Your previous response failed validation with this error:\n{exc}\n"
                    f"Please correct the JSON and return a valid response."
                )
            else:
                errors.append(ErrorRecord(
                    stage="llm",
                    url=None,
                    error_type=error_type,
                    message=f"LLM extraction failed after {settings.llm_max_attempts} attempts: {exc}",
                    recoverable=True,
                ))

    return None
