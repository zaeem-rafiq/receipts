"""Roundtable hand-off adapter: put_file / get_file / post_message. The real SDK is UNVERIFIED (quick-start not read), so this
ships a local versioned store with the same interface; swap the three functions for SDK calls once the package name is known."""
import json
import time
from pathlib import Path

STORE = Path(__file__).resolve().parent.parent / "demo_cache" / "roundtable"


def enabled():
    return False  # flips to True only when a real SDK client is wired in


def put_file(name, obj, note=""):
    d = STORE / name
    d.mkdir(parents=True, exist_ok=True)
    v = len(list(d.glob("v*.json"))) + 1
    (d / f"v{v}.json").write_text(json.dumps(obj, indent=1, default=str))
    post_message(f"put {name} v{v} {note}".strip())
    return v


def get_file(name, version=None):
    d = STORE / name
    vs = sorted(d.glob("v*.json"), key=lambda p: int(p.stem[1:]))
    if not vs:
        return None, 0
    p = vs[-1] if version is None else d / f"v{version}.json"
    return json.loads(p.read_text()), int(p.stem[1:])


def post_message(text):
    STORE.mkdir(parents=True, exist_ok=True)
    with open(STORE / "messages.log", "a") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {text}\n")
