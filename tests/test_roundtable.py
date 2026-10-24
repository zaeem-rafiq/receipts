"""Offline tests for the Roundtable adapter: local fallback, remote mirror, honest badge."""
import pytest

from integrations import roundtable as rt


class FakeRemote:
    def __init__(self, fail=False):
        self.fail, self.files, self.msgs = fail, {}, []

    def put_file(self, name, text, note):
        if self.fail:
            raise ConnectionError("down")
        self.files.setdefault(name, []).append(text)
        return len(self.files[name])

    def get_file(self, name, version):
        if self.fail:
            raise ConnectionError("down")
        vs = self.files.get(name, [])
        if not vs:
            return None, 0
        v = version or len(vs)
        return vs[v - 1], v

    def post_message(self, text):
        if self.fail:
            raise ConnectionError("down")
        self.msgs.append(text)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "STORE", tmp_path)
    monkeypatch.setattr(rt, "STATE", {"remote_ok": False, "last_error": None, "calls": 0})
    return tmp_path


def test_no_key_is_local_stub(store, monkeypatch):
    monkeypatch.delenv("ROUNDTABLE_API_KEY", raising=False)
    assert rt.put_file("claims.json", {"a": 1}) == 1
    assert rt.put_file("claims.json", {"a": 2}) == 2
    assert rt.get_file("claims.json") == ({"a": 2}, 2)
    assert rt.get_file("claims.json", 1) == ({"a": 1}, 1)
    assert not rt.enabled() and rt.status() == "local stub"


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code, self._payload = status, payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_real_client_wire_shape(store, monkeypatch):
    """Same call shape as @roundtable/sdk 0.1.1: POST {url}/api/tools/<tool>, Bearer key, request_id on writes."""
    import requests
    monkeypatch.setenv("ROUNDTABLE_API_KEY", "test-not-a-key")
    monkeypatch.delenv("ROUNDTABLE_URL", raising=False)
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append((url, json, headers))
        if url.endswith("/write_file"):
            return FakeResponse(200, {"version": {"id": "ver_1"}})
        if url.endswith("/read_file"):
            return FakeResponse(200, {"content": '{"a": 1}', "version": "ver_1"})
        return FakeResponse(200, {"ok": True})

    monkeypatch.setattr(requests, "post", fake_post)
    assert rt.put_file("claims.json", {"a": 1}, note="source=llm") == 1
    assert rt.get_file("claims.json") == ({"a": 1}, 1)
    rt.post_message("engine run")
    assert rt.enabled() and rt.status() == "Roundtable workspace"
    (u1, b1, h1), (u2, b2, _), (u3, b3, _) = calls
    assert u1 == "https://roundtable.bot/api/tools/write_file"
    assert h1["Authorization"] == "Bearer test-not-a-key"
    assert h1["User-Agent"] == "roundtable-transfer/1.0"
    assert b1["path"] == "receipts/claims.json" and b1["message"] == "source=llm" and b1["request_id"]
    assert u2.endswith("/read_file") and "request_id" not in b2
    assert u3.endswith("/record") and b3["kind"] == "journal" and b3["request_id"]


def test_real_client_401_stays_local(store, monkeypatch):
    import requests
    monkeypatch.setenv("ROUNDTABLE_API_KEY", "test-not-a-key")
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse(401, {"error": "A valid agent token is required."}))
    assert rt.put_file("claims.json", {"a": 1}) == 1
    assert rt.get_file("claims.json") == ({"a": 1}, 1)
    assert not rt.enabled() and "local stub" in rt.status()


def test_remote_success_turns_badge_real(store, monkeypatch):
    fake = FakeRemote()
    monkeypatch.setattr(rt, "_client", lambda: fake)
    assert rt.put_file("findings.json", {"x": 1}, note="engine run") == 1
    assert rt.get_file("findings.json") == ({"x": 1}, 1)
    rt.post_message("hello")
    assert rt.enabled() and rt.status() == "Roundtable workspace"
    assert fake.msgs == ["hello"]
    assert (store / "findings.json" / "v1.json").exists()  # local copy kept


def test_remote_failure_falls_back_and_says_so(store, monkeypatch):
    monkeypatch.setattr(rt, "_client", lambda: FakeRemote(fail=True))
    assert rt.put_file("claims.json", {"a": 1}) == 1
    assert rt.get_file("claims.json") == ({"a": 1}, 1)
    assert not rt.enabled() and rt.status() == "remote failed, local stub"
