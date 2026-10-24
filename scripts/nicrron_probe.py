"""Nicrron gateway probe: one short prompt, three request shapes, prints what came back (no key is ever printed).

    python scripts/nicrron_probe.py

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


def main():
    if not nicrron.enabled():
        print("NICRRON_API_KEY is not set in this shell (never paste it in chat).")
        return 2
    from openai import OpenAI
    client = OpenAI(base_url=nicrron.BASE_URL, api_key=os.environ["NICRRON_API_KEY"], timeout=30, max_retries=0)
    variants = [("app call: max_tokens=400", dict(max_tokens=400)),
                ("max_completion_tokens=800", dict(max_completion_tokens=800)),
                ("no token limit", {})]
    for label, extra in variants:
        t0 = time.time()
        try:
            r = client.chat.completions.create(model=nicrron.MODEL, messages=[{"role": "user", "content": PROMPT}], temperature=0, **extra)
        except Exception as e:
            print(f"\n== {label}: ERROR {type(e).__name__}: {str(e)[:300]}")
            continue
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
        print("   top-level keys:", sorted(raw.keys()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
