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
    # a MOCK fixture for a made-up live domain, so the live-then-mock fallback can be exercised without a real company
    mock = tmp_path / "mock"
    for kind, body in (("news", {"data": []}), ("enrichment", {"firmographic": {"headcount_range": "11-50"}})):
        (mock / kind).mkdir(parents=True, exist_ok=True)
        (mock / kind / "liveprobe.test.json").write_text(json.dumps({"fetched_at": "mock", "response": body}))
    monkeypatch.setattr(client, "MOCK", mock)
    monkeypatch.setattr(client.time, "sleep", lambda *_: None)
    client.ERRORS.clear()


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_failed_live_call_is_not_cached_and_falls_to_mock(monkeypatch, tmp_path, status):
    import requests
    _live_env(monkeypatch, tmp_path)
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(status))
    rec = client.get("news", "https://liveprobe.test")
    assert rec["mode"] == "MOCK"
    assert not (tmp_path / "akta" / "news" / "liveprobe.test.json").exists()
    assert client.ERRORS[("news", "liveprobe.test")] == f"HTTP {status}"


def test_reserved_example_domain_never_calls_live(monkeypatch, tmp_path):
    import requests
    _live_env(monkeypatch, tmp_path)
    monkeypatch.setattr(client, "MOCK", ROOT / "demo_cache" / "akta" / "mock")  # the repo's fixtures for the fictional customers
    monkeypatch.setattr(requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("live call made")))
    rec = client.get("news", "https://www.ferrymoor.example")
    assert rec["mode"] == "MOCK" and client._live_used == 0 and client.ERRORS == {}


def test_timeout_degrades_instead_of_crashing(monkeypatch, tmp_path):
    import requests
    _live_env(monkeypatch, tmp_path)

    def boom(*a, **k):
        raise requests.exceptions.ReadTimeout("slow")
    monkeypatch.setattr(requests, "get", boom)
    rec = client.get("enrichment", "liveprobe.test")
    assert rec["mode"] == "MOCK"
    assert client.ERRORS[("enrichment", "liveprobe.test")] == "ReadTimeout"


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
        if client.domain_of(website) == "whitlockdata.example":
            return {"unresolved": True, "mode": "MISS", "response": {}}
        return real_get(endpoint, website)
    monkeypatch.setattr(client, "get", fake_get)
    F = findings.run(run_date=date(2026, 10, 24))
    clay = next(l for l in F["logos"] if l["akta"]["domain"] == "whitlockdata.example")
    assert clay["status"] == "ACTIVE" and clay["verdict"] == "UNVERIFIED" and clay["card"] == "grey_unverified"
    assert clay["mrr_at_risk"] == 0 and clay["akta"]["news_status"] == "unavailable"
    assert "logo_03" in F["headline"]["unverified_slots"]
    # the unchecked customer is not counted as logo-verified recurring ARR
    assert F["headline"]["logo_verified_arr"] == full["headline"]["logo_verified_arr"] - 12 * clay["mrr_now"]


def test_empty_news_204_still_counts_as_checked(monkeypatch):
    real_get = client.get

    def fake_get(endpoint, website):
        rec = real_get(endpoint, website)
        if endpoint == "news" and client.domain_of(website) == "whitlockdata.example":
            return {"mode": "CACHED", "fetched_at": "x", "response": {"data": [], "empty": True}}
        return rec
    monkeypatch.setattr(client, "get", fake_get)
    F = findings.run(run_date=date(2026, 10, 24))
    clay = next(l for l in F["logos"] if l["akta"]["domain"] == "whitlockdata.example")
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


def test_failed_live_lookup_is_not_retried_within_the_process(monkeypatch, tmp_path):
    _live_env(monkeypatch, tmp_path)
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(403))
    first = client.get("news", "https://liveprobe.test")
    second = client.get("news", "https://liveprobe.test")
    assert first["mode"] == "MOCK" and second["mode"] == "MOCK"
    assert client._live_used == 1 and client.ERRORS[("news", "liveprobe.test")] == "HTTP 403"


def test_active_logo_without_website_is_unverified_when_akta_is_on(monkeypatch):
    real = load.load_logos

    def blank_one(data):
        logos, claims, src = real(data)
        for lg in logos:
            if lg["slot"] == "logo_03":
                lg["website"] = ""
        return logos, claims, src
    monkeypatch.setattr(load, "load_logos", blank_one)
    F = findings.run(run_date=date(2026, 10, 24))
    lg = next(l for l in F["logos"] if l["slot"] == "logo_03")
    assert lg["status"] == "ACTIVE" and lg["verdict"] == "UNVERIFIED" and lg["card"] == "grey_unverified"
    assert lg["akta"]["mode"] == "MISS" and lg["akta"]["news_status"] == "unavailable" and "logo_03" in F["headline"]["unverified_slots"]
    assert "1 missing" in F["meta"]["akta_mode"]
    off = findings.run(run_date=date(2026, 10, 24), akta_enabled=False)
    assert next(l for l in off["logos"] if l["slot"] == "logo_03")["verdict"] == "VERIFIED"


def test_shutdown_headline_beats_any_akta_tag():
    art = {"title": "Relay announces shutdown; team joins Google Chrome", "ai_summary": "Relay will shut down on Sept 14."}
    for codes in ([], ["CM03"], ["WT02"], ["SD01"], ["CM01"]):
        c = rules.classify({**art, "types": [{"code": c} for c in codes]}, "Relay", CFG)
        assert c["class"] == "shutdown", codes
    # a layoff story that only mentions a closure in the summary keeps its tag
    lay = {"title": "monday.com cuts roughly 20% of global workforce", "types": [{"code": "WT02"}],
           "ai_summary": "monday.com is laying off roughly 20% of staff and shutting down its Berlin office."}
    assert rules.classify(lay, "monday.com", CFG)["class"] == "layoffs_major"


# ---- real-cache rules (found when the warm-up cache of 2026-10-24 landed) ----
def test_percent_counts_only_as_a_share_of_the_workforce():
    stock = {"title": "Monday's AI makeover is pushing managers toward the exit", "types": [{"code": "WT02"}],
             "ai_summary": "The stock has fallen 37% since early 2026, and the company is encouraging employees to adopt AI."}
    assert rules.classify(stock, "monday.com", CFG)["class"] == "layoffs_minor"
    cut = {"title": "Monday faces senior management exits amid AI restructuring", "types": [{"code": "WT02"}],
           "ai_summary": "Several senior executives are expected to leave amid a restructuring that cuts about 20% of its workforce."}
    assert rules.classify(cut, "monday.com", CFG)["class"] == "layoffs_major"
    serves = {"title": "Acme trims team", "types": [{"code": "WT02"}], "ai_summary": "Acme, which serves 12,000 employees at its customers, let go of 30 staff."}
    assert rules.classify(serves, "Acme", CFG)["class"] == "layoffs_minor"


def test_secondary_mentions_never_move_a_verdict():
    arts = {"data": [
        {"id": "a1", "title": "Neobanks on Rented Rails: The Synapse Collapse", "published_date": "2026-09-04", "tags": [{"code": "RK07", "is_primary": True}],
         "ai_summary": "Metropolitan Commercial Bank wound down its fintech business.", "company_mentions": [{"website": "http://www.metropolitanbankny.com", "is_primary": True}, {"website": "https://mercury.com", "is_primary": False}]},
        {"id": "a2", "title": "Mercury's playbook", "published_date": "2026-08-21", "tags": [{"code": "CM01", "is_primary": True}],
         "ai_summary": "Mercury raised a Series C and runs a software layer for banking.", "company_mentions": [{"website": "https://mercury.com", "is_primary": True}]},
    ]}
    evs = rules.events_for(arts, "Mercury", CFG, date(2026, 10, 24), domain="mercury.com")
    assert [e["primary"] for e in evs] == [False, True] and evs[0]["class"] == "shutdown"
    assert rules.most_severe(evs)["class"] == "funding"
    # no company_mentions (MOCK fixtures) or no domain: not gated
    assert all(e["primary"] for e in rules.events_for({"data": [{"id": "m", "title": "x shuts down", "published_date": "2026-10-01"}]}, "x", CFG, date(2026, 10, 24), domain="x.com"))
    assert all(e["primary"] for e in rules.events_for(arts, "Mercury", CFG, date(2026, 10, 24)))


def test_funding_tag_needs_funding_language():
    speaker = {"title": "Clay's Kareem Amin joins Disrupt 2026", "tags": [{"code": "CM01"}], "ai_summary": "Amin will present on the GTM engineer role."}
    assert rules.classify(speaker, "Clay", CFG)["class"] == "none"
    speaker["ai_summary"] += " Clay raised a $115 million Series D at a $7.1 billion valuation."
    assert rules.classify(speaker, "Clay", CFG)["class"] == "funding"


def test_live_enrichment_shape_is_read():
    F = findings.run(run_date=date(2026, 10, 24))
    m = next(l for l in F["logos"] if l["akta"]["domain"] == "harrowgatework.example")
    assert m["akta"]["mode"] in ("CACHED", "MOCK") and m["akta"]["headcount_range"] and m["akta"]["segment"] != "unverified"
    assert F["headline"]["enterprise_count"] == 4


def test_empty_or_truncated_model_output_falls_back_to_template(monkeypatch):
    from integrations import nicrron
    display = findings.run(run_date=date(2026, 10, 24), events_override={})["display"]
    assert summarize.is_truncated("") and summarize.is_truncated("Deck AR") and not summarize.is_truncated(summarize.template(display))
    monkeypatch.setenv("NICRRON_API_KEY", "nk-test-not-real")
    monkeypatch.setattr(nicrron, "chat", lambda *a, **k: ("", {"finish_reason": "length", "usage": None}))
    S = summarize.summarize(display, None)
    assert S["text"] == summarize.template(display) and S["source"].startswith("template (model returned 0 chars")
    good = (f"The deck claims {display['deck_arr']} ARR; the ledger supports {display['recurring_arr']} of recurring ARR.\n"
            "The gap is implementation and one-time fees.\nTwo customers carry risk events.\nThe weights are screening weights.\nAsk about the pilots.")
    monkeypatch.setattr(nicrron, "chat", lambda *a, **k: (good, {"finish_reason": "stop", "usage": None}))
    assert summarize.summarize(display, None)["source"].startswith("Nicrron")


def test_content_text_accepts_string_list_or_alternate_fields():
    from integrations import nicrron

    class M:
        def __init__(self, **kw):
            self.__dict__.update(kw)
    assert nicrron._content_text(M(content="hello")) == "hello"
    assert nicrron._content_text(M(content=[{"type": "text", "text": "a"}, {"type": "text", "text": "b"}])) == "ab"
    assert nicrron._content_text(M(content=None, text="alt")) == "alt"
    assert nicrron._content_text(M(content=None)) == ""


def test_chat_retries_with_a_bigger_budget_when_thinking_eats_max_tokens(monkeypatch, tmp_path):
    from integrations import nicrron, prism
    monkeypatch.setenv("NICRRON_API_KEY", "nk-test-not-real")
    monkeypatch.delenv("PRISMTRACE_API_KEY", raising=False)
    prism.reset()
    seen = []

    class Msg:
        def __init__(self, c):
            self.content = c

    class Choice:
        def __init__(self, c, fin):
            self.message, self.finish_reason = Msg(c), fin

    class Usage:
        def model_dump(self):
            return {"prompt_tokens": 300, "completion_tokens": 400}

    class Resp:
        def __init__(self, c, fin):
            self.choices, self.usage = [Choice(c, fin)], Usage()

    class Completions:
        def create(self, **kw):
            seen.append(kw["max_tokens"])
            return Resp(None, "length") if kw["max_tokens"] <= 2000 else Resp("Deck ARR is $1,200,000.\n" * 3, "stop")

    class FakeOpenAI:
        def __init__(self, **kw):
            self.chat = type("C", (), {"completions": Completions()})()
    import openai
    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    text, meta = nicrron.chat([{"role": "user", "content": "p"}])
    assert seen == [2000, 6000] and text.startswith("Deck ARR") and meta["finish_reason"] == "stop"


def test_prompt_labels_carry_no_digits_and_cover_every_display_key():
    import re
    display = findings.run(run_date=date(2026, 10, 24), events_override={})["display"]
    shown = summarize.prompt_input(display)
    assert set(shown.values()) == set(display.values()) and len(shown) == len(display)
    assert not any(re.search(r"\d", k) for k in shown), [k for k in shown if re.search(r"\d", k)]
    assert all(k in summarize.LABELS for k in display), [k for k in display if k not in summarize.LABELS]
    assert not re.search(r"\d", summarize.PROMPT)
