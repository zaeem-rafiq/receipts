"""PRISM by Block Convey, through the prismtrace SDK (per PRISM's setup brief, Oct 24).

One PRISM *session* per engine run. Inside it: one trace per Nicrron completion (trace_llm, posted from nicrron.chat via
record_llm), one trajectory built from the run's spans (engine, akta/<domain>, summarize, guardrail) and an end_session
marker. Spans are always written locally under demo_cache/traces/<session_id>.json.

`Run.exported` is True only when PRISM answered 2xx to the trajectory POST, so the header badge is green only when
something actually landed. Without PRISMTRACE_API_KEY nothing leaves the process. `_Http` is the SDK-free fallback
(same endpoints, same X-PRISMtrace-Key header) used only when the package cannot be imported.
Live behaviour is UNTESTED from the sandbox (no key here); the export path was exercised against a local fake server."""
import contextlib
import json
import os
import sys
import time
import uuid
from pathlib import Path

from integrations import env  # noqa: F401

LOG = Path(__file__).resolve().parent.parent / "demo_cache" / "traces"
DEFAULT_HOST = "https://api.prism.blockconvey.com"
DEFAULT_PROJECT_ID = "8f2cbb1c-5045-4524-8615-f2aca5edb2ed"  # the Receipts project in PRISM; an id, not a secret
AGENT_ID, AGENT_NAME = "receipts-engine", "Receipts"
TIMEOUT = 6  # seconds per request: a dead host costs one run at most this, never a hang
_client = None


def enabled():
    """A key is configured. Whether anything was accepted is Run.exported."""
    return bool(os.environ.get("PRISMTRACE_API_KEY")) and os.environ.get("PRISM_ENABLED", "1") != "0"


def host():
    return (os.environ.get("PRISMTRACE_HOST") or DEFAULT_HOST).rstrip("/")


def project_id():
    return os.environ.get("PRISMTRACE_PROJECT_ID") or DEFAULT_PROJECT_ID


def reset():
    """Forget the process-wide client (tests, key changes)."""
    global _client
    _client = None


def client():
    """One client per process: the SDK when importable, else plain HTTP; None without a key. Both record every POST's outcome."""
    global _client
    if not enabled():
        return None
    if _client is None:
        key = os.environ["PRISMTRACE_API_KEY"]
        try:
            _client = _sdk_client(key)
        except Exception as e:  # package missing or incompatible: same three calls over requests
            print("PRISM SDK unavailable, using HTTP ingest:", type(e).__name__, file=sys.stderr)
            _client = _Http(key, host(), project_id(), TIMEOUT)
    return _client


def _sdk_client(key):
    from prismtrace import PRISMtrace

    class _Sdk(PRISMtrace):
        """The SDK client plus a record of (path, accepted) for every POST, so a run can say what PRISM actually took."""

        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.results = []

        def _post(self, path, payload):
            r = super()._post(path, payload)
            self.results.append((path, r is not None))
            return r

        def _post_sync(self, path, payload):
            r = super()._post_sync(path, payload)
            self.results.append((path, r is not None))
            return r

    return _Sdk(api_key=key, host=host(), project_id=project_id(), timeout=TIMEOUT)


class _Http:
    """SDK-free fallback: trace_llm / submit_trajectory / end_session over `requests`, synchronous, same payload shapes."""

    def __init__(self, api_key, host, project_id, timeout=TIMEOUT):
        self.api_key, self.host, self.project_id, self.timeout = api_key, host.rstrip("/"), project_id, timeout
        self.results = []

    def _post(self, path, payload):
        import requests
        body, ok = None, False
        try:
            r = requests.post(self.host + path, json=payload, headers={"X-PRISMtrace-Key": self.api_key}, timeout=self.timeout)
            ok = r.status_code in (200, 201)
            if ok:
                try:
                    body = r.json()
                except ValueError:
                    body = {}
            else:
                print(f"PRISM {path} returned {r.status_code}", file=sys.stderr)
        except requests.RequestException as e:
            print(f"PRISM {path} failed: {type(e).__name__}", file=sys.stderr)
        self.results.append((path, ok))
        return body if ok else None

    def trace_llm(self, model, input_messages, output, latency_ms, token_count_input=0, token_count_output=0, trace_id=None,
                  agent_id=None, agent_name=None, session_id=None, metadata=None):
        p = {"project_id": self.project_id, "model": model, "input_messages": input_messages, "output_message": output,
             "latency_ms": latency_ms, "token_count_input": token_count_input, "token_count_output": token_count_output}
        for k, v in (("trace_id", trace_id), ("agent_id", agent_id), ("agent_name", agent_name), ("session_id", session_id), ("metadata", metadata)):
            if v is not None:
                p[k] = v
        self._post("/api/traces", p)

    def submit_trajectory(self, steps, *, agent_name="default-agent", agent_id=None, conversation_id=None, request_id=None,
                          model=None, final_status="success", async_send=False):
        return self._post("/api/trajectories", {
            "project_id": self.project_id, "conversation_id": conversation_id or str(uuid.uuid4()), "request_id": request_id or str(uuid.uuid4()),
            "agent_id": agent_id or agent_name, "agent_name": agent_name, "steps": steps,
            "total_duration_ms": sum(s.get("duration_ms") or 0 for s in steps), "final_status": final_status, "model": model})

    def end_session(self, session_id=None, *, reason=None, agent_id=None, agent_name=None):
        if not session_id:
            raise ValueError("end_session() needs a session id")
        md = {"session_end": True, "session_id": session_id}
        if reason:
            md["session_end_reason"] = reason
        p = {"project_id": self.project_id, "model": "session-tracker", "input_messages": [], "output_message": "Session ended",
             "latency_ms": 0, "session_id": session_id, "metadata": md}
        for k, v in (("agent_id", agent_id), ("agent_name", agent_name)):
            if v is not None:
                p[k] = v
        self._post("/api/traces", p)

    def flush(self, timeout=2.0):
        return None


def _short(x, n=600):
    s = x if isinstance(x, str) else json.dumps(x, default=str)
    return s[:n]


def _tally(results):
    out = {}
    for path, ok in results:
        name = path.rsplit("/", 1)[-1]
        sent, acc = out.get(name, (0, 0))
        out[name] = (sent + 1, acc + (1 if ok else 0))
    return {k: f"{acc}/{sent} accepted" for k, (sent, acc) in out.items()}


def record_llm(messages, output, model, latency_ms, usage=None, run=None, **meta):
    """One PRISM trace per model completion; nicrron.chat calls this after every call. Never raises."""
    u = usage or {}
    rec = {"model": model, "latency_ms": int(latency_ms), "tokens_in": int(u.get("prompt_tokens") or 0),
           "tokens_out": int(u.get("completion_tokens") or 0), "chars_out": len(output or ""), **meta}
    if run is not None:
        run.llm_calls.append(rec)
    c = client()
    if c is None:
        return rec
    try:
        c.trace_llm(model=model, input_messages=messages, output=output or "", latency_ms=rec["latency_ms"],
                    token_count_input=rec["tokens_in"], token_count_output=rec["tokens_out"], agent_id=AGENT_ID, agent_name=AGENT_NAME,
                    session_id=run.session_id if run is not None else None, metadata={"app": "receipts", **meta})
    except Exception as e:
        print("PRISM trace_llm failed:", type(e).__name__, file=sys.stderr)
    return rec


class Run:
    """One PRISM session per engine run. `trace_id` (shown in the header) is the session id PRISM groups everything under."""

    def __init__(self, kind="receipts-run"):
        self.session_id = f"{kind}-{time.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
        self.trace_id = self.session_id
        self.spans, self.llm_calls = [], []
        self.exported, self.export_error, self.trajectory_id, self.accepted, self.saved = False, None, None, {}, False
        c = client()
        self._r0 = len(c.results) if c is not None else 0

    @contextlib.contextmanager
    def span(self, name, **attrs):
        t0 = time.time()
        rec = {"name": name, "attrs": dict(attrs), "status": "success"}
        try:
            yield rec
        except BaseException:
            rec["status"] = "error"
            raise
        finally:
            rec["ms"] = int(1000 * (time.time() - t0))
            self.spans.append(rec)

    def steps(self):
        """Trajectory steps in the SDK's shape: engine and Akta spans are tool calls, the app summary is the final answer."""
        out = []
        for s in self.spans:
            tool = s["name"].split("/")[0].split(".")[0]
            kind = "tool_call" if tool in ("engine", "akta") else ("final_answer" if s["name"] == "summarize" else "reasoning")
            attrs = dict(s["attrs"])
            output = attrs.pop("output", None)
            step = {"step_type": kind, "label": s["name"], "duration_ms": s.get("ms", 0), "status": s["status"],
                    "input_summary": _short(attrs), "output_summary": _short(output if output is not None else attrs)}
            if kind == "tool_call":
                step["tool_name"] = tool
            out.append(step)
        return out

    def to_dict(self):
        return {"session_id": self.session_id, "exported": self.exported, "trajectory_id": self.trajectory_id,
                "export_error": self.export_error, "accepted": self.accepted, "host": host() if enabled() else None,
                "llm_calls": self.llm_calls, "spans": self.spans}

    def save(self, final_status="success"):
        """Submit the trajectory, close the session, write the local log. Returns exported: PRISM accepted the trajectory."""
        c = client()
        if c is not None and not self.saved:
            try:
                from integrations import nicrron
                resp = c.submit_trajectory(self.steps(), agent_name=AGENT_NAME, agent_id=AGENT_ID, conversation_id=self.session_id,
                                           model=nicrron.MODEL, final_status=final_status)
                self.exported = resp is not None
                self.trajectory_id = (resp or {}).get("id") or (resp or {}).get("trajectory_id")
                if not self.exported:
                    self.export_error = "trajectory not accepted (see stderr for the HTTP status)"
                c.end_session(self.session_id, reason="run complete", agent_id=AGENT_ID, agent_name=AGENT_NAME)
                c.flush(timeout=TIMEOUT)
            except Exception as e:
                self.exported, self.export_error = False, type(e).__name__
                print("PRISM export failed:", type(e).__name__, file=sys.stderr)
            self.accepted = _tally(c.results[self._r0:])
        self.saved = True
        LOG.mkdir(parents=True, exist_ok=True)
        (LOG / f"{self.session_id}.json").write_text(json.dumps(self.to_dict(), indent=1, default=str))
        return self.exported
