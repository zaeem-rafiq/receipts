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


def test_key_without_wired_client_stays_stub(store, monkeypatch):
    monkeypatch.setenv("ROUNDTABLE_API_KEY", "test-not-a-key")
    rt.put_file("claims.json", {"a": 1})
    assert not rt.enabled()


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
