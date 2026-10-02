"""One OpenAI-compatible client for any provider (DeepSeek by default).

Settings (GitHub repo secrets/variables):
  LLM_BASE_URL     https://api.deepseek.com
  LLM_API_KEY      provider key (secret)
  LLM_MODEL_FAST   deepseek-chat      classify + extract + matching
  LLM_MODEL_BRIEF  deepseek-chat      daily brief
Model settings may be a comma-separated list; each is tried in order (useful for busy free models).

OpenRouter free models (testing):
  LLM_BASE_URL=https://openrouter.ai/api/v1
  LLM_MODEL_FAST=qwen/qwen3.8-27b:free,google/gemma-4-31b-it:free,nvidia/nemotron-3-super-120b-a12b:free

Optional fallback: GitHub Models via the workflow's GITHUB_TOKEN, enabled with LLM_FALLBACK=github.
Off by default: on 2026-10-02 every models.github.ai endpoint answered a bare "OK" instead of a completion.
"""
from __future__ import annotations

import json
import re
import time

from openai import OpenAI

from .common import env, log

GITHUB_MODELS_URL = "https://models.github.ai/inference"


def _providers(kind: str) -> list[tuple[str, OpenAI, str]]:
    providers = []
    key = env("LLM_API_KEY")
    if key:
        models = env("LLM_MODEL_BRIEF" if kind == "brief" else "LLM_MODEL_FAST") or env("LLM_MODEL_FAST") or "deepseek-chat"
        base_url = env("LLM_BASE_URL") or "https://api.deepseek.com"
        headers = {"HTTP-Referer": "https://imariners.com", "X-Title": "iMariners Maritime Security Tracker"} if "openrouter" in base_url else None
        client = OpenAI(api_key=key, base_url=base_url, timeout=180, default_headers=headers)
        for model in [m.strip() for m in models.split(",") if m.strip()]:
            providers.append(("primary", client, model))
    gh_token = env("GITHUB_TOKEN")
    if gh_token and env("LLM_FALLBACK", "off") == "github":
        model = env("GITHUB_MODELS_MODEL", "openai/gpt-4.1-mini")
        providers.append(("github-models", OpenAI(api_key=gh_token, base_url=GITHUB_MODELS_URL, timeout=120), model))
    return providers


def available() -> bool:
    return bool(_providers("fast"))


def free_tier_only() -> bool:
    """True when only GitHub Models is available (small requests, about 150 calls a day)."""
    return not env("LLM_API_KEY") and available()


def _parse_json(text: str) -> dict:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in response")
    return json.loads(text[start : end + 1])


def chat_json(system: str, user: str, kind: str = "fast", max_tokens: int = 4000) -> dict:
    """Ask for a JSON object. Tries each provider, retrying once on bad JSON."""
    errors = []
    for name, client, model in _providers(kind):
        for attempt in range(2):
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                    response_format={"type": "json_object"},
                    temperature=0.1 if kind == "fast" else 0.4,
                    max_tokens=max_tokens,
                )
                return _parse_json(resp.choices[0].message.content or "")
            except Exception as exc:  # network, rate limit, bad JSON
                errors.append(f"{name}/{model}: {exc}")
                log.warning("LLM call failed (%s %s, attempt %d): %s", name, model, attempt + 1, str(exc)[:300])
                if "429" in str(exc) or "rate" in str(exc).lower() or "404" in str(exc):
                    break  # busy or gone: move to the next model instead of spending another request
                time.sleep(3 * (attempt + 1))
    raise RuntimeError("All LLM providers failed: " + " | ".join(errors) if errors else "No LLM provider configured (set LLM_API_KEY)")
