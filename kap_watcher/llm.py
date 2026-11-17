"""Minimal JSON-mode chat client over OpenAI-compatible endpoints.

Provider (KAP_LLM_PROVIDER, or picked from whichever key is set):
  gemini   GEMINI_API_KEY    default model gemini-3.5-flash
  deepseek DEEPSEEK_API_KEY  default model deepseek-chat
  ollama   no key            default model qwen3.5:9b at OLLAMA_HOST
  openai   KAP_LLM_BASE_URL + KAP_LLM_API_KEY (any compatible endpoint)
KAP_LLM_MODEL overrides the model.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

PROVIDERS = {
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY", "gemini-3.5-flash"),
    "deepseek": ("https://api.deepseek.com", "DEEPSEEK_API_KEY", "deepseek-chat"),
    "ollama": (None, None, "qwen3.5:9b"),
    "openai": (None, "KAP_LLM_API_KEY", "gpt-4o-mini"),
}
USAGE = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}


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
            content = resp["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = content.strip("`").removeprefix("json").strip()
            return json.loads(content)
        except urllib.error.HTTPError as e:  # 429/5xx: back off; other 4xx: give up
            last = f"HTTP {e.code}"
            if e.code != 429 and e.code < 500:
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
