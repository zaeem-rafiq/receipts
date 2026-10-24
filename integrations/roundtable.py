"""Roundtable hand-off adapter: put_file / get_file / post_message. A local versioned store always keeps a copy (the demo
works offline); when ROUNDTABLE_API_KEY is set and a remote client is wired, every call is mirrored to Roundtable too.
The real SDK is UNVERIFIED (quick-start not read yet): `_client()` returns None until it is, so the badge stays "local stub".
enabled() is True only after a remote call actually succeeded in this process, never because a key is present."""
import json
import os
import time
from pathlib import Path

from integrations import env  # noqa: F401  (loads .env / Streamlit Secrets into os.environ)

STORE = Path(__file__).resolve().parent.parent / "demo_cache" / "roundtable"
STATE = {"remote_ok": False, "last_error": None, "calls": 0}


def _client():
    """Return a remote client with put_file(name, text, note) -> version, get_file(name, version) -> (text, version),
    post_message(text). None until the real SDK is wired (UNVERIFIED) or when ROUNDTABLE_API_KEY is absent."""
    if not os.environ.get("ROUNDTABLE_API_KEY"):
        return None
    return None  # wire the real SDK here once the quick-start is read


def _remote(method, *args):
    c = _client()
    if c is None:
        return None
    try:
        out = getattr(c, method)(*args)
        STATE["remote_ok"], STATE["last_error"] = True, None
        STATE["calls"] += 1
        return out
    except Exception as e:  # remote trouble never breaks the demo; the badge just stays honest
        STATE["remote_ok"], STATE["last_error"] = False, f"{type(e).__name__}: {e}"[:200]
        return None


def enabled():
    return STATE["remote_ok"]


def status():
    """Short label for the badge."""
    if STATE["remote_ok"]:
        return "Roundtable workspace"
    if STATE["last_error"]:
        return "remote failed, local stub"
    return "local stub"


def put_file(name, obj, note=""):
    text = json.dumps(obj, indent=1, default=str)
    d = STORE / name
    d.mkdir(parents=True, exist_ok=True)
    v = len(list(d.glob("v*.json"))) + 1
    (d / f"v{v}.json").write_text(text)
    rv = _remote("put_file", name, text, note)
    _local_message(f"put {name} v{v}{' (remote v%s)' % rv if rv is not None else ''} {note}".strip())
    return rv if isinstance(rv, int) else v


def get_file(name, version=None):
    r = _remote("get_file", name, version)
    if r is not None and r[0] is not None:
        return json.loads(r[0]), int(r[1])
    d = STORE / name
    vs = sorted(d.glob("v*.json"), key=lambda p: int(p.stem[1:]))
    if not vs:
        return None, 0
    p = vs[-1] if version is None else d / f"v{version}.json"
    return json.loads(p.read_text()), int(p.stem[1:])


def post_message(text):
    _remote("post_message", text)
    _local_message(text)


def _local_message(text):
    STORE.mkdir(parents=True, exist_ok=True)
    with open(STORE / "messages.log", "a") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {text}\n")
