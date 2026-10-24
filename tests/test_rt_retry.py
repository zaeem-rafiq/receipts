"""A Roundtable call that fails once on a cold start is retried on the next page view, so the badge recovers."""
import os

from streamlit.testing.v1 import AppTest

from integrations import roundtable as rt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FlakyRemote:
    def __init__(self):
        self.calls = 0

    def _tick(self):
        self.calls += 1
        if self.calls <= 2:  # compute() makes two calls (put findings, get claims); both time out on the cold start
            raise TimeoutError("cold start")

    def put_file(self, name, text, note):
        self._tick()
        return "ver_remote"

    def get_file(self, name, version):
        self._tick()
        return None, None

    def post_message(self, text):
        pass


def test_badge_recovers_after_one_failed_call(monkeypatch, tmp_path):
    os.environ.setdefault("AKTA_OFFLINE", "1")
    monkeypatch.setenv("ROUNDTABLE_API_KEY", "test-not-a-key")
    monkeypatch.setattr(rt, "STORE", tmp_path)
    monkeypatch.setattr(rt, "STATE", {"remote_ok": False, "last_error": None, "calls": 0})
    flaky = FlakyRemote()
    monkeypatch.setattr(rt, "_client", lambda: flaky)
    import streamlit as st
    st.cache_data.clear()
    at = AppTest.from_file(os.path.join(ROOT, "streamlit_app.py"), default_timeout=120).run()
    assert not at.exception, at.exception
    html = "\n".join(m.value for m in at.markdown)
    assert "files shared" in html, html[:300]
    assert flaky.calls >= 3  # two failures inside compute(), then the retry on render succeeded
    assert rt.status() == "Roundtable workspace"
