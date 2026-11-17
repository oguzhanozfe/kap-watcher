"""Minimal JSON-mode chat client over OpenAI-compatible endpoints.

Provider (KAP_LLM_PROVIDER, or picked from whichever key is set):
  gemini   GEMINI_API_KEY    default model gemma-4-31b-it (free-tier quota is per model)
  deepseek DEEPSEEK_API_KEY  default model deepseek-chat
  ollama   no key            default model qwen3.5:9b at OLLAMA_HOST
  openai   KAP_LLM_BASE_URL + KAP_LLM_API_KEY (any compatible endpoint)
KAP_LLM_MODEL overrides the model.
Responses are cached on disk by request hash (KAP_CACHE_DIR, default .kap-cache;
KAP_CACHE_DIR=off disables), so reruns cost no quota.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
import urllib.error
import urllib.request

PROVIDERS = {
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY", "gemma-4-31b-it"),
    "deepseek": ("https://api.deepseek.com", "DEEPSEEK_API_KEY", "deepseek-chat"),
    "ollama": (None, None, "qwen3.5:9b"),
    "openai": (None, "KAP_LLM_API_KEY", "gpt-4o-mini"),
}
USAGE = {"calls": 0, "cache_hits": 0, "prompt_tokens": 0, "completion_tokens": 0}
THOUGHT = re.compile(r"<thought>.*?</thought>", re.S)  # Gemma via Gemini API inlines its reasoning


class LLMError(RuntimeError):
    pass


def provider() -> str:
    p = os.environ.get("KAP_LLM_PROVIDER")
    if p:
        if p not in PROVIDERS:
            raise LLMError(f"unknown KAP_LLM_PROVIDER {p!r}; use one of {sorted(PROVIDERS)}")
        return p
    for name in ("gemini", "deepseek"):
        if os.environ.get(PROVIDERS[name][1]):
            return name
    return "openai" if os.environ.get("KAP_LLM_BASE_URL") else "ollama"


def model_name() -> str:
    return os.environ.get("KAP_LLM_MODEL") or PROVIDERS[provider()][2]


def _base_url(p: str) -> str:
    if p == "ollama":
        return os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/") + "/v1"
    return (os.environ.get("KAP_LLM_BASE_URL") or PROVIDERS[p][0] or "").rstrip("/")


def chat_json(system: str, user: str, *, timeout: float = 180, retries: int = 4) -> dict:
    p = provider()
    key_env = PROVIDERS[p][1]
    key = os.environ.get(key_env, "") if key_env else ""
    body = {"model": model_name(), "temperature": 0, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if p == "ollama":
        body["reasoning_effort"] = "none"  # qwen3.x: skip thinking, answer directly
    cache_dir = os.environ.get("KAP_CACHE_DIR", ".kap-cache")
    cache = None
    if cache_dir != "off":
        digest = hashlib.sha256(json.dumps([p, body], sort_keys=True).encode()).hexdigest()
        cache = Path(cache_dir) / f"{digest}.json"
        if cache.exists():
            USAGE["cache_hits"] += 1
            return json.loads(cache.read_text("utf-8"))
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {key}"} if key else {})}
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(_base_url(p) + "/chat/completions", json.dumps(body).encode(), headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                resp = json.load(r)
            usage = resp.get("usage") or {}
            USAGE["calls"] += 1
            USAGE["prompt_tokens"] += usage.get("prompt_tokens", 0)
            USAGE["completion_tokens"] += usage.get("completion_tokens", 0)
            content = THOUGHT.sub("", resp["choices"][0]["message"]["content"]).strip()
            if content.startswith("```"):
                content = content.strip("`").removeprefix("json").strip()
            result = json.loads(content)
            if cache:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(result, ensure_ascii=False), "utf-8")
            return result
        except urllib.error.HTTPError as e:  # per-minute 429 / 5xx: back off; daily quota or 4xx: stop
            detail = e.read().decode("utf-8", "replace")
            last = f"HTTP {e.code}" + (" daily quota exhausted" if "PerDay" in detail else "")
            if (e.code != 429 and e.code < 500) or "PerDay" in detail:
                break
        except Exception as e:  # timeout, network, bad JSON
            last = type(e).__name__ + ": " + str(e)[:200]
        time.sleep(min(60, 5 * 2 ** attempt))
    raise LLMError(f"{p}/{model_name()}: {last}")


def model_digest() -> str | None:
    """Ollama model digest, so a results file names the exact weights."""
    if provider() != "ollama":
        return None
    try:
        with urllib.request.urlopen(_base_url("ollama").removesuffix("/v1") + "/api/tags", timeout=10) as r:
            tags = json.load(r)["models"]
    except Exception:
        return None
    return next((m["digest"] for m in tags if m["name"] == model_name()), None)
