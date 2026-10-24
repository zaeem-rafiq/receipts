"""Nicrron gateway (OpenAI-compatible). Base URL and model per PLAN.md; live path UNTESTED from the sandbox (no key here).
Every completion is reported to PRISM through prism.record_llm (model, messages, output, latency, token counts, session)."""
import os
import time

from integrations import env  # noqa: F401
from integrations import prism

BASE_URL = "https://api.nicrron.ai/v1"
MODEL = os.environ.get("NICRRON_MODEL", "anthropic/claude-haiku-5-5")


def enabled():
    return bool(os.environ.get("NICRRON_API_KEY"))


def chat(messages, max_tokens=400, json_mode=False, run=None, purpose="chat"):
    """Returns (text, meta). Raises if disabled; callers fall back to deterministic text.
    json_mode tries response_format={"type": "json_object"} once (support on the gateway is UNVERIFIED) and retries without it.
    `run` is the prism.Run whose PRISM session this call belongs to (None at build time, e.g. llm/extract.py)."""
    from openai import OpenAI
    client = OpenAI(base_url=BASE_URL, api_key=os.environ["NICRRON_API_KEY"], timeout=20, max_retries=1)
    kwargs = dict(model=MODEL, messages=messages, max_tokens=max_tokens, temperature=0)
    used_json_mode = False
    t0 = time.time()
    if json_mode:
        try:
            r = client.chat.completions.create(**kwargs, response_format={"type": "json_object"})
            used_json_mode = True
        except Exception:
            r = client.chat.completions.create(**kwargs)
    else:
        r = client.chat.completions.create(**kwargs)
    latency_ms = int(1000 * (time.time() - t0))
    usage = getattr(r, "usage", None)
    usage = usage.model_dump() if usage else None
    text = r.choices[0].message.content or ""
    prism.record_llm(messages, text, MODEL, latency_ms, usage=usage, run=run, purpose=purpose, json_mode=used_json_mode)
    return text, {"model": MODEL, "usage": usage, "json_mode": used_json_mode, "latency_ms": latency_ms}
