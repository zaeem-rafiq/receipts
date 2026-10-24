"""Nicrron gateway probe: one short prompt, three request shapes, prints what came back (no key is ever printed).

    python scripts/nicrron_probe.py          # one plain prompt, three request shapes
    python scripts/nicrron_probe.py --app    # the app's own summary prompt and the challenge v1 prompt, plus the last challenge trace

Use when the app's summary comes back empty or truncated: the output shows finish_reason, usage, the content length and
the raw response shape for (a) the app's call (max_tokens=400), (b) max_completion_tokens=800, (c) no token limit."""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from integrations import env  # noqa: E402,F401
from integrations import nicrron  # noqa: E402

PROMPT = ("Write exactly three short sentences about why a VC checks a startup's customer logos against its revenue export. "
          "Plain prose, no numbers.")


def _show(label, client, messages, **extra):
    t0 = time.time()
    try:
        r = client.chat.completions.create(model=nicrron.MODEL, messages=messages, temperature=0, **extra)
    except Exception as e:
        print(f"\n== {label}: ERROR {type(e).__name__}: {str(e)[:300]}")
        return
    ms = int(1000 * (time.time() - t0))
    ch = r.choices[0] if r.choices else None
    text = nicrron._content_text(ch.message) if ch else ""
    print(f"\n== {label}: {ms} ms, finish_reason={getattr(ch, 'finish_reason', None)!r}, chars={len(text)}, "
          f"usage={r.usage.model_dump() if getattr(r, 'usage', None) else None}")
    print("   text:", repr(text[:300]))
    raw = r.model_dump()
    for ch_ in raw.get("choices", []):
        msg = ch_.get("message") or {}
        print("   message keys:", sorted(msg.keys()), "| content type:", type(msg.get("content")).__name__)
        extra_keys = {k: (str(v)[:200]) for k, v in msg.items() if k not in ("content", "role") and v}
        if extra_keys:
            print("   other message fields:", json.dumps(extra_keys)[:600])
        other = {k: str(v)[:200] for k, v in ch_.items() if k not in ("message", "index", "finish_reason", "logprobs") and v}
        if other:
            print("   other choice fields:", json.dumps(other)[:400])
    print("   top-level keys:", sorted(raw.keys()))
    for k in ("moderation", "provider", "model", "service_tier"):
        if raw.get(k) is not None:
            print(f"   {k}:", json.dumps(raw.get(k), default=str)[:600])


def _last_challenge_trace():
    """What the last challenge run recorded locally: tokens out vs characters out per model call."""
    traces = sorted(Path("demo_cache/traces").glob("prism-challenge-*.json"), key=lambda p: p.stat().st_mtime)
    if not traces:
        return
    d = json.loads(traces[-1].read_text())
    print(f"last challenge session {d.get('session_id')}: {len(d.get('llm_calls', []))} model calls")
    for c in d.get("llm_calls", []):
        print(f"   {c.get('purpose'):<14} tokens_in={c.get('tokens_in')} tokens_out={c.get('tokens_out')} chars_out={c.get('chars_out')} "
              f"latency_ms={c.get('latency_ms')} finish={c.get('finish_reason')}")


def main(argv=None):
    app_prompts = "--app" in (argv or sys.argv[1:])
    if not nicrron.enabled():
        print("NICRRON_API_KEY is not set in this shell (never paste it in chat).")
        return 2
    from openai import OpenAI
    client = OpenAI(base_url=nicrron.BASE_URL, api_key=os.environ["NICRRON_API_KEY"], timeout=30, max_retries=0)
    if app_prompts:
        _last_challenge_trace()
        os.environ.setdefault("AKTA_OFFLINE", "1")
        from datetime import date
        from engine import findings
        from llm import summarize
        F = findings.run(run_date=date.today())
        v2 = summarize.PROMPT + json.dumps(F["display"])
        _show("app summary prompt (v2), max_tokens=400", client, [{"role": "user", "content": v2}], max_tokens=400)
        _show("app summary prompt (v2), no limit", client, [{"role": "user", "content": v2}])
        _show("app summary prompt (v2) with a system line", client,
              [{"role": "system", "content": "You are a diligence analyst. Answer in plain text."}, {"role": "user", "content": v2}], max_tokens=400)
        import importlib.util
        spec = importlib.util.spec_from_file_location("prism_challenge", Path(__file__).with_name("prism_challenge.py"))
        pc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pc)
        v1 = pc.V1_PROMPT + json.dumps(pc.v1_input(F))
        _show("challenge v1 prompt, max_tokens=400", client, [{"role": "user", "content": v1}], max_tokens=400)
        return 0
    for label, extra in [("plain prompt: max_tokens=400", dict(max_tokens=400)),
                         ("plain prompt: max_completion_tokens=800", dict(max_completion_tokens=800)),
                         ("plain prompt: no token limit", {})]:
        _show(label, client, [{"role": "user", "content": PROMPT}], **extra)
    return 0


if __name__ == "__main__":
    sys.exit(main())
