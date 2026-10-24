"""Roundtable hand-off adapter: put_file / get_file / post_message. A local versioned store always keeps a copy (the demo
works offline); when ROUNDTABLE_API_KEY is set, every call is mirrored to the Roundtable workspace (roundtable.bot).
Wire format read from the official TypeScript SDK (@roundtable/sdk 0.1.1, dist/client.js): POST {url}/api/tools/<tool>,
`Authorization: Bearer <agent key>`, JSON body; write tools carry a request_id. Files go to the agent's own folder under
receipts/ (write_file / read_file); messages go to the agent's journal (`record`, kind=journal).
enabled() is True only after a remote call actually succeeded in this process, never because a key is present."""
import json
import os
import time
import uuid
from pathlib import Path

from integrations import env  # noqa: F401  (loads .env / Streamlit Secrets into os.environ)

STORE = Path(__file__).resolve().parent.parent / "demo_cache" / "roundtable"
STATE = {"remote_ok": False, "last_error": None, "calls": 0}


FOLDER = "receipts"
_versions = {}  # file name -> latest remote version id seen in this process


class Client:
    """Minimal port of the SDK's call(): POST /api/tools/<tool> with the agent key; one retry on 429/502/503/504."""

    def __init__(self, key, url=None, timeout=10):
        self.key = key
        self.url = (url or os.environ.get("ROUNDTABLE_URL") or "https://roundtable.bot").rstrip("/")
        self.timeout = timeout

    def call(self, tool, args, write=False):
        import requests
        body = dict(args, request_id=str(uuid.uuid4())) if write else args
        for attempt in range(2):
            r = requests.post(f"{self.url}/api/tools/{tool}", json=body, timeout=self.timeout,
                              headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
            if r.status_code in (429, 502, 503, 504) and attempt == 0:
                time.sleep(1)
                continue
            if r.status_code == 404 and tool == "read_file":
                return None  # file not there yet; not a failure
            r.raise_for_status()
            return r.json()

    def put_file(self, name, text, note):
        out = self.call("write_file", {"path": f"{FOLDER}/{name}", "content": text,
                                       "message": note or f"Receipts: save {name}"}, write=True)
        _versions[name] = _version_id((out or {}).get("version"))
        return _versions[name]

    def get_file(self, name, version=None):  # latest only; local version numbers are not Roundtable version ids
        out = self.call("read_file", {"path": f"{FOLDER}/{name}"})
        if not out:
            return None, None
        _versions[name] = _version_id(out.get("version"))
        return out.get("content"), _versions[name]

    def post_message(self, text):
        self.call("record", {"kind": "journal", "title": "Receipts run", "summary": text[:2000]}, write=True)


def _version_id(v):
    return v.get("id") if isinstance(v, dict) else v


def _client():
    """Remote client when ROUNDTABLE_API_KEY is set (env, .env or Streamlit Secrets), else None (local stub)."""
    key = os.environ.get("ROUNDTABLE_API_KEY")
    return Client(key) if key else None


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
    _local_message(f"put {name} v{v}{' (remote %s)' % rv if rv is not None else ''} {note}".strip())
    return v


def get_file(name, version=None):
    r = _remote("get_file", name, None) if version is None else None
    d = STORE / name
    vs = sorted(d.glob("v*.json"), key=lambda p: int(p.stem[1:]))
    if r is not None and r[0] is not None:  # remote copy wins (it may come from another machine's extraction run)
        try:
            return json.loads(r[0]), (int(vs[-1].stem[1:]) if vs else 1)
        except ValueError:
            pass
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
