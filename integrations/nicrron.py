"""Nicrron gateway (OpenAI-compatible). Base URL and model per PLAN.md; live path UNTESTED from the sandbox (no key here)."""
import os

BASE_URL = "https://api.nicrron.ai/v1"
MODEL = os.environ.get("NICRRON_MODEL", "anthropic/claude-haiku-5-5")


def enabled():
    return bool(os.environ.get("NICRRON_API_KEY"))


def chat(messages, max_tokens=400):
    """Returns (text, meta). Raises if disabled; callers fall back to deterministic text."""
    from openai import OpenAI
    client = OpenAI(base_url=BASE_URL, api_key=os.environ["NICRRON_API_KEY"])
    r = client.chat.completions.create(model=MODEL, messages=messages, max_tokens=max_tokens, temperature=0)
    usage = getattr(r, "usage", None)
    return r.choices[0].message.content, {"model": MODEL, "usage": usage.model_dump() if usage else None}
