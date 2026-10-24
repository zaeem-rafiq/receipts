"""Regression tests for the review fixes: failed live calls never poison the cache or crash, tag codes beat keywords,
an unchecked world never reads VERIFIED, claim numbers come from the deck quote, and provenance covers the ledger numbers."""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from akta import client, rules  # noqa: E402
from engine import findings, load  # noqa: E402
from llm import summarize  # noqa: E402

CFG = load.load_config()


class _Resp:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def _live_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AKTA_API_KEY", "test-key-not-real")
    monkeypatch.setenv("AKTA_OFFLINE", "0")
    monkeypatch.setenv("AKTA_LIVE_BUDGET", "10")
    monkeypatch.setattr(client, "_live_used", 0)
    monkeypatch.setattr(client, "CACHE", tmp_path / "akta")
    monkeypatch.setattr(client, "MOCK", ROOT / "demo_cache" / "akta" / "mock")
    monkeypatch.setattr(client.time, "sleep", lambda *_: None)
    client.ERRORS.clear()


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_failed_live_call_is_not_cached_and_falls_to_mock(monkeypatch, tmp_path, status):
    import requests
    _live_env(monkeypatch, tmp_path)
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(status))
    rec = client.get("news", "https://monday.com")
    assert rec["mode"] == "MOCK"
    assert not (tmp_path / "akta" / "news" / "monday.com.json").exists()
    assert client.ERRORS[("news", "monday.com")] == f"HTTP {status}"


def test_timeout_degrades_instead_of_crashing(monkeypatch, tmp_path):
    import requests
    _live_env(monkeypatch, tmp_path)

    def boom(*a, **k):
        raise requests.exceptions.ReadTimeout("slow")
    monkeypatch.setattr(requests, "get", boom)
    rec = client.get("enrichment", "monday.com")
    assert rec["mode"] == "MOCK"
    assert client.ERRORS[("enrichment", "monday.com")] == "ReadTimeout"


def test_live_success_is_cached_and_reads_back_as_cached(monkeypatch, tmp_path):
    import requests
    _live_env(monkeypatch, tmp_path)
    body = {"data": [{"id": "a1", "title": "t", "url": "u", "full_text": "drop me"}]}
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(200, body))
    first = client.get("news", "ramp.com")
    assert first["mode"] == "LIVE" and "full_text" not in first["response"]["data"][0]
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(500))
    second = client.get("news", "ramp.com")
    assert second["mode"] == "CACHED" and second["response"]["data"][0]["id"] == "a1"


def test_unknown_domain_without_mock_is_unresolved(monkeypatch, tmp_path):
    import requests
    _live_env(monkeypatch, tmp_path)
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(429))
    rec = client.get("news", "nonexistent-example.test")
    assert rec.get("unresolved") and rec["mode"] == "MISS"


def test_mode_summary_is_honest_about_mixtures():
    assert client.mode_summary([]) == "OFF"
    assert client.mode_summary(["CACHED", "CACHED"]) == "CACHED"
    assert client.mode_summary(["LIVE", "CACHED"]) == "LIVE"
    assert client.mode_summary(["CACHED", "MOCK", "MOCK"]).startswith("MOCK (2 MOCK, 1 real")
    assert client.mode_summary(["MISS", "CACHED"]).startswith("MISS (")


def test_tag_codes_beat_shutdown_keywords():
    art = {"title": "monday.com cuts roughly 20% of global workforce", "types": [{"code": "WT02"}],
           "ai_summary": "monday.com is laying off roughly 20% of staff and shutting down its Berlin office."}
    c = rules.classify(art, "monday.com", CFG)
    assert c["class"] == "layoffs_major" and not c["keyword_classified"]


def test_keyword_shutdown_only_without_tags_and_whole_words():
    assert rules.classify({"title": "Relay announces shutdown; team joins Google", "types": []}, "Relay", CFG)["class"] == "shutdown"
    assert rules.classify({"title": "Relay will shut down on Sept 14", "types": []}, "Relay", CFG)["class"] == "shutdown"
    assert rules.classify({"title": "Vendors brace for a government shutdown", "types": []}, "Vendor", CFG)["class"] == "none"
    assert rules.classify({"title": "Acme ships a windowing feature", "types": []}, "Acme", CFG)["class"] == "none"


def test_unavailable_news_makes_active_logo_unverified_not_verified(monkeypatch):
    full = findings.run(run_date=date(2026, 10, 24))  # before the patch: every slot checked
    real_get = client.get

    def fake_get(endpoint, website):
        if client.domain_of(website) == "clay.com":
            return {"unresolved": True, "mode": "MISS", "response": {}}
        return real_get(endpoint, website)
    monkeypatch.setattr(client, "get", fake_get)
    F = findings.run(run_date=date(2026, 10, 24))
    clay = next(l for l in F["logos"] if l["akta"]["domain"] == "clay.com")
    assert clay["status"] == "ACTIVE" and clay["verdict"] == "UNVERIFIED" and clay["card"] == "grey_unverified"
    assert clay["mrr_at_risk"] == 0 and clay["akta"]["news_status"] == "unavailable"
    assert "logo_03" in F["headline"]["unverified_slots"]
    # the unchecked customer is not counted as logo-verified recurring ARR
    assert F["headline"]["logo_verified_arr"] == full["headline"]["logo_verified_arr"] - 12 * clay["mrr_now"]


def test_empty_news_204_still_counts_as_checked(monkeypatch):
    real_get = client.get

    def fake_get(endpoint, website):
        rec = real_get(endpoint, website)
        if endpoint == "news" and client.domain_of(website) == "clay.com":
            return {"mode": "CACHED", "fetched_at": "x", "response": {"data": [], "empty": True}}
        return rec
    monkeypatch.setattr(client, "get", fake_get)
    F = findings.run(run_date=date(2026, 10, 24))
    clay = next(l for l in F["logos"] if l["akta"]["domain"] == "clay.com")
    assert clay["verdict"] == "VERIFIED" and clay["akta"]["news_status"] == "checked"


@pytest.mark.parametrize("text,expected", [
    ("Raising $4M at a $20M post-money valuation.", 20_000_000),
    ("Raising $4M at a $20,000,000 post-money valuation", 20_000_000),
    ("$4M raise; post-money valuation of $25M", 25_000_000),
    ("Raising $4M on a $20M pre-money", None),
    ("", None),
])
def test_post_money_parser(text, expected):
    assert load.parse_post_money(text) == expected


def test_run_survives_unparseable_post_money(monkeypatch):
    real = load.load_logos

    def fake(data=load.DATA):
        logos, claims, src = real(data)
        for c in claims:
            if c["id"] == "ask":
                c["text"] = c["quote"] = "Raising $4M on a $20M pre-money"
        return logos, claims, src
    monkeypatch.setattr(load, "load_logos", fake)
    F = findings.run(run_date=date(2026, 10, 24))
    assert F["headline"]["post_money"] is None and F["display"]["multiple_deck"] == "unparsed"
    assert F["headline"]["recurring_arr"] == 840000


def test_ledger_provenance_covers_headline_numbers():
    F = findings.run(run_date=date(2026, 10, 24))
    ledger = next(p for p in F["provenance"] if p["slot"] == "ledger")
    kinds = {i["kind"] for i in ledger["items"]}
    assert {"definition", "bridge", "recurring_mrr", "ttm", "implementation_rows", "customers_ever_billed", "claim"} <= kinds
    ttm = next(i for i in ledger["items"] if i["kind"] == "ttm")
    assert ttm["value"] == 811800 and len(ttm["row_ids"]) > 0
    rec = next(i for i in ledger["items"] if i["kind"] == "recurring_mrr")
    assert rec["value"] == 70000 and len(rec["row_ids"]) == F["ledger"]["active_customers"]
    for p in F["provenance"]:
        if p["slot"] != "ledger":
            assert any(i["kind"] == "company" for i in p["items"]) or not next(l for l in F["logos"] if l["slot"] == p["slot"])["akta"]["domain"]


def test_guardrail_blocks_reformatted_numbers():
    F = findings.run(run_date=date(2026, 10, 24))
    d = F["display"]
    assert summarize.guardrail("The deck claims $1,200,000 ARR and the ledger supports $840,000.", d) == []
    assert summarize.guardrail("The deck claims $1.2M ARR.", d)  # '$1.2' is not an engine token: blocked
    assert summarize.guardrail("ARR flagged is 13.3 percent", d) == ["13.3"]
