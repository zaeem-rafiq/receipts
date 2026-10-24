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


MAX_TOKENS = 2000  # the gateway's Claude models think before they answer and the thinking counts against max_tokens:
# with 400 the app's prompts came back as finish_reason=length with 0-7 visible characters (laptop probe, Oct 24 1:42 PM)


def chat(messages, max_tokens=MAX_TOKENS, json_mode=False, run=None, purpose="chat"):
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
    choice = r.choices[0]
    text = _content_text(choice.message)
    finish = getattr(choice, "finish_reason", None)
    if finish == "length" and len(text.strip()) < 40:
        # the budget went to thinking; one retry with a larger budget before the caller falls back to the template
        r = client.chat.completions.create(**{**kwargs, "max_tokens": max(max_tokens * 3, 4000)})
        choice = r.choices[0]
        text = _content_text(choice.message)
        finish = getattr(choice, "finish_reason", None)
        latency_ms = int(1000 * (time.time() - t0))
        usage = getattr(r, "usage", None)
    usage = usage.model_dump() if usage else None
    prism.record_llm(messages, text, MODEL, latency_ms, usage=usage, run=run, purpose=purpose, json_mode=used_json_mode, finish_reason=finish)
    return text, {"model": MODEL, "usage": usage, "json_mode": used_json_mode, "latency_ms": latency_ms, "finish_reason": finish}


def _content_text(message):
    """The gateway may return content as a string, a list of parts, or None (text in another field). Never raises."""
    c = getattr(message, "content", None)
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = []
        for part in c:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                parts.append(part.get("text") or "")
            else:
                parts.append(getattr(part, "text", "") or "")
        return "".join(parts)
    for alt in ("text", "reasoning_content", "refusal"):
        v = getattr(message, alt, None)
        if isinstance(v, str) and v:
            return v
    return ""
