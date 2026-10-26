"""PRISM wiring: the badge may only be green when PRISM accepted the run, every model call is traced into the run's session,
and the SDK-free fallback speaks the documented HTTP shape. No network: the client is faked or `requests.post` is stubbed."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from integrations import prism  # noqa: E402


class _FakeClient:
    """Stands in for the SDK client: records calls, answers as told."""

    def __init__(self, accept_trajectory=True, accept_traces=True):
        self.results, self.calls = [], []
        self.accept_trajectory, self.accept_traces = accept_trajectory, accept_traces

    def trace_llm(self, **kw):
        self.calls.append(("trace_llm", kw))
        self.results.append(("/api/traces", self.accept_traces))

    def submit_trajectory(self, steps, **kw):
        self.calls.append(("submit_trajectory", {"steps": steps, **kw}))
        self.results.append(("/api/trajectories", self.accept_trajectory))
        return {"id": "traj-1", "step_count": len(steps)} if self.accept_trajectory else None

    def end_session(self, session_id=None, **kw):
        self.calls.append(("end_session", {"session_id": session_id, **kw}))
        self.results.append(("/api/traces", self.accept_traces))

    def flush(self, timeout=2.0):
        self.calls.append(("flush", {}))


@pytest.fixture
def prism_on(monkeypatch, tmp_path):
    monkeypatch.setenv("PRISMTRACE_API_KEY", "pt-sk-test-not-real")
    monkeypatch.setattr(prism, "LOG", tmp_path / "traces")
    fake = _FakeClient()
    monkeypatch.setattr(prism, "_client", fake)
    yield fake
    prism.reset()


def test_without_key_nothing_is_sent_and_badge_stays_grey(monkeypatch, tmp_path):
    monkeypatch.delenv("PRISMTRACE_API_KEY", raising=False)
    monkeypatch.setattr(prism, "LOG", tmp_path / "traces")
    prism.reset()
    run = prism.Run()
    with run.span("engine", run_date="2026-10-24"):
        pass
    prism.record_llm([{"role": "user", "content": "hi"}], "ok", "m", 12, run=run, purpose="summary")
    assert run.save() is False and run.exported is False and prism.client() is None
    log = json.loads((tmp_path / "traces" / f"{run.session_id}.json").read_text())
    assert log["exported"] is False and [s["name"] for s in log["spans"]] == ["engine"] and len(log["llm_calls"]) == 1


def test_run_is_one_session_with_traces_trajectory_and_end_marker(prism_on):
    run = prism.Run()
    with run.span("engine", run_date="2026-10-24", akta=True):
        pass
    with run.span("akta/ferrymoor.example", mode="CACHED", event="shutdown"):
        pass
    with run.span("summarize", provider="nicrron") as rec:
        prism.record_llm([{"role": "user", "content": "p"}], "five lines", "anthropic/claude-haiku-5-5", 850,
                         usage={"prompt_tokens": 120, "completion_tokens": 40}, run=run, purpose="summary")
        rec["attrs"].update({"output": "five lines", "guardrail.digit_rule": "pass"})
    assert run.save() is True and run.exported is True and run.trajectory_id == "traj-1"
    names = [c[0] for c in prism_on.calls]
    assert names == ["trace_llm", "submit_trajectory", "end_session", "flush"]
    t = prism_on.calls[0][1]
    assert t["session_id"] == run.session_id and t["token_count_input"] == 120 and t["token_count_output"] == 40
    assert t["latency_ms"] == 850 and t["agent_id"] == prism.AGENT_ID and t["metadata"]["purpose"] == "summary"
    traj = prism_on.calls[1][1]
    assert traj["conversation_id"] == run.session_id and traj["agent_id"] == prism.AGENT_ID
    kinds = [(s["label"], s["step_type"]) for s in traj["steps"]]
    assert kinds == [("engine", "tool_call"), ("akta/ferrymoor.example", "tool_call"), ("summarize", "final_answer")]
    assert traj["steps"][1]["tool_name"] == "akta" and traj["steps"][2]["output_summary"] == "five lines"
    assert prism_on.calls[2][1]["session_id"] == run.session_id
    assert run.accepted == {"traces": "2/2 accepted", "trajectories": "1/1 accepted"}


def test_rejected_trajectory_is_not_reported_as_exported(prism_on):
    prism_on.accept_trajectory = False
    run = prism.Run()
    with run.span("engine"):
        pass
    assert run.save() is False and run.exported is False and run.export_error
    assert run.accepted["trajectories"] == "0/1 accepted"


def test_sdk_exception_never_breaks_the_run(prism_on):
    def boom(*a, **k):
        raise RuntimeError("socket")
    prism_on.submit_trajectory = boom
    run = prism.Run()
    assert run.save() is False and run.export_error == "RuntimeError"


def test_http_fallback_uses_documented_endpoints_and_header(monkeypatch):
    import requests
    sent = []

    class R:
        def __init__(self, code):
            self.status_code = code

        def json(self):
            return {"id": "x"}

    def fake_post(url, json=None, headers=None, timeout=None):
        sent.append((url, json, headers))
        return R(201 if url.endswith("/api/trajectories") else 200)
    monkeypatch.setattr(requests, "post", fake_post)
    c = prism._Http("pt-sk-test-not-real", "https://api.example.test/", "proj-1")
    c.trace_llm(model="m", input_messages=[{"role": "user", "content": "hi"}], output="ok", latency_ms=5, session_id="s-1",
                agent_id="a", agent_name="A", metadata={"app": "receipts"})
    assert c.submit_trajectory([{"step_type": "reasoning", "label": "x", "duration_ms": 3}], agent_name="A", agent_id="a", conversation_id="s-1")
    c.end_session("s-1", reason="done")
    urls = [u for u, _, _ in sent]
    assert urls == ["https://api.example.test/api/traces", "https://api.example.test/api/trajectories", "https://api.example.test/api/traces"]
    assert all(h == {"X-PRISMtrace-Key": "pt-sk-test-not-real"} for _, _, h in sent)
    trace, traj, end = (j for _, j, _ in sent)
    assert trace["project_id"] == "proj-1" and trace["session_id"] == "s-1" and isinstance(trace["output_message"], str)
    assert traj["conversation_id"] == "s-1" and traj["total_duration_ms"] == 3 and traj["agent_id"] == "a"
    assert end["model"] == "session-tracker" and end["metadata"]["session_end"] is True
    assert c.results == [("/api/traces", True), ("/api/trajectories", True), ("/api/traces", True)]


def test_http_fallback_counts_rejections(monkeypatch):
    import requests

    class R:
        status_code = 401

        def json(self):
            return {}
    monkeypatch.setattr(requests, "post", lambda *a, **k: R())
    c = prism._Http("pt-sk-test-not-real", "https://api.example.test", "proj-1")
    assert c.submit_trajectory([], agent_name="A") is None and c.results == [("/api/trajectories", False)]


def test_nicrron_chat_reports_every_completion_to_prism(monkeypatch, prism_on):
    from integrations import nicrron
    monkeypatch.setenv("NICRRON_API_KEY", "nk-test-not-real")

    class Msg:
        content = "hello"

    class Choice:
        message = Msg()

    class Usage:
        def model_dump(self):
            return {"prompt_tokens": 7, "completion_tokens": 2}

    class Resp:
        choices = [Choice()]
        usage = Usage()

    class Completions:
        def create(self, **kw):
            return Resp()

    class FakeOpenAI:
        def __init__(self, **kw):
            self.chat = type("C", (), {"completions": Completions()})()
    import openai
    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    run = prism.Run()
    text, meta = nicrron.chat([{"role": "user", "content": "p"}], run=run, purpose="summary")
    assert text == "hello" and meta["usage"]["prompt_tokens"] == 7 and "latency_ms" in meta
    assert len(run.llm_calls) == 1 and run.llm_calls[0]["tokens_in"] == 7
    assert prism_on.calls[0][0] == "trace_llm" and prism_on.calls[0][1]["session_id"] == run.session_id
