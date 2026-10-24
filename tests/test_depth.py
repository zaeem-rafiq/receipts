"""akta/depth.py: World ledger and Profile column. Offline; real cache where it exists, synthetic tmp files for the
extra calls (search, funding/M&A, headcount, addition) whose real shapes are UNVERIFIED."""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from akta import client, depth  # noqa: E402
from engine import load  # noqa: E402
from scripts import warm_depth  # noqa: E402

CFG = load.load_config()
RUN = date(2026, 10, 24)
REAL = ROOT / "demo_cache" / "akta"


def real(endpoint, domain):
    p = REAL / endpoint / f"{domain}.json"
    if not p.exists():
        pytest.skip(f"no real cache for {endpoint}/{domain}")
    rec = json.loads(p.read_text())
    rec["mode"] = "CACHED"
    return rec


def enr(fg=None, **sections):
    return {"mode": "CACHED", "fetched_at": "t", "params": {"company": "example.com"},
            "response": {"data": {"firmographic": fg or {}, **sections}}}


def put(tmp, kind, domain, response):
    p = tmp / depth.EXTRA_DIRS[kind] / f"{domain}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"fetched_at": "t", "response": response}))


# ---------------- contract with the engine hook

def test_empty_input_returns_empty_dict():
    assert depth.world({}) == {} and depth.world(None) == {}
    assert depth.profile({}) == {} and depth.profile(None, "x.com") == {}


def test_bad_input_never_raises():
    assert "error" in depth.world({"response": {"data": [{"tags": 5}]}})
    assert "error" in depth.profile({"response": {"data": {"firmographic": "oops"}}}, "x.com", cfg=CFG)


# ---------------- World

def test_world_counts_only_on_subject_articles():
    w = depth.world(real("news", "braze.com"), [])
    assert w["articles_read"] == w["articles_on_subject"] + w["articles_off_subject"] + sum(
        1 for p in w["provenance"] if p["on_subject"] is None)
    assert w["articles_total"] >= w["articles_read"]
    assert w["weighted_codes"].get("CM03", 0) >= 1
    assert sum(w["by_sentiment"].values()) == w["articles_read"] - w["articles_off_subject"]
    assert len(w["provenance"]) == w["articles_read"]  # every article id is named
    assert "about braze.com" in w["momentum_line"]


def test_on_subject_flag():
    a = {"company_mentions": [{"website": "https://www.mercury.com", "is_primary": False},
                              {"website": "https://mcb.com", "is_primary": True}]}
    assert depth.on_subject(a, "mercury.com") is False
    a["company_mentions"][0]["is_primary"] = True
    assert depth.on_subject(a, "mercury.com") is True
    assert depth.on_subject({}, "mercury.com") is None  # MOCK fixtures carry no mentions


def test_world_flags_off_subject_top_event():
    news = {"mode": "CACHED", "params": {"company": "mercury.com"}, "response": {"data": [
        {"id": 1, "tags": [{"code": "RK07"}], "company_mentions": [{"website": "mercury.com", "is_primary": False}]}]}}
    ev = [{"article_id": 1, "class": "shutdown", "in_window": True}]
    w = depth.world(news, ev)
    assert w["top_event_on_subject"] is False and w["off_subject_event_ids"] == [1]
    assert w["weighted_codes"] == {}


# ---------------- Profile

def test_revenue_band():
    assert depth.revenue_band("1b_5b") == (1e9, 5e9)
    assert depth.revenue_band("250m_500m") == (250e6, 500e6)
    assert depth.revenue_band("pre_revenue") == (0, 0)
    assert depth.revenue_band("weird") is None


def test_profile_real_monday_record():
    p = depth.profile(real("enrichment", "monday.com"), "monday.com", {"mrr_now": 12_000}, CFG, RUN, events=[])
    assert p["company_type"] == "Public" and p["revenue_estimate"] == "$1B-$5B"
    assert "$144,000 ARR" in p["size_line"]
    assert p["funding"] is None  # public company: recent_move funding_round is not a venture round
    assert any(x["id"] == "monday.com:financial_estimate:revenue_estimate" for x in p["provenance"])
    assert "headcount_trends" in p["sections_unavailable"]


def test_funding_age_from_recent_move_labels_only():
    fg = {"company_type": {"label": "Private"}, "operating_status": {"label": "Operating"}}
    ss = {"recent_move": [{"date": {"year": 2023, "month": 10}, "type": {"code": "funding_round"}, "description": "Seed"}]}
    p = depth.profile(enr(fg, strategic_signal=ss), "example.com", {"mrr_now": 0}, CFG, RUN, events=[])
    assert p["funding"]["age_months"] == 36 and p["funding_aged"] is True
    assert p["funding"]["section"] == "strategic_signal.recent_move"


def test_status_cross_check():
    fg = {"company_type": {"label": "Private"}, "operating_status": {"label": "Operating"}}
    shut = [{"class": "shutdown", "in_window": True, "article_id": "a"}]
    p = depth.profile(enr(fg), "example.com", None, CFG, RUN, events=shut)
    assert p["status_check"]["agrees"] is False and "Conflict" in p["status_check"]["line"]
    acq = [{"class": "acquisition", "in_window": True, "article_id": "a"}]
    p = depth.profile(enr(fg), "example.com", None, CFG, RUN, events=acq)
    assert p["status_check"]["agrees"] is None and p["ma_role"] == "target"
    fg2 = {"company_type": {"label": "Acquired"}, "operating_status": {"label": "Operating"}}
    p = depth.profile(enr(fg2), "example.com", None, CFG, RUN, events=[])
    assert p["status_check"]["agrees"] is False


def test_recent_subsidiary_marks_acquirer():
    hier = {"subsidiaries": [{"name": "Sub", "acquired_on": {"year": 2026, "month": 7}}]}
    p = depth.profile(enr({"company_type": {"label": "Public"}}, company_hierarchy=hier), "example.com", None, CFG, RUN, events=[])
    assert p["ma_role"] == "acquirer" and p["ma"]["section"] == "company_hierarchy.subsidiaries"


def test_extras_from_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(client, "CACHE", tmp_path)
    put(tmp_path, "search", "example.com", {"data": {"results": [{"website": "https://example.com", "company_status": "acquired"}]}})
    put(tmp_path, "depth", "example.com", {"data": {"funding_detail": {"rounds": [
        {"date": "2024-01-15", "stage": "Series B", "amount": "$40M"}]}}})
    put(tmp_path, "headcount", "example.com", {"data": {"series": [
        {"date": "2026-04", "headcount": 500}, {"date": "2026-07", "headcount": 470}, {"date": "2026-10", "headcount": 440}]}})
    fg = {"company_type": {"label": "Private"}, "operating_status": {"label": "Operating"}}
    p = depth.profile(enr(fg), "example.com", None, CFG, RUN, events=[],
                      wld={"weighted_codes": {"WT02": 1}})
    assert p["company_status"] == "acquired" and p["status_check"]["source"] == "Company Search company_status"
    assert p["funding"]["section"] == "funding_detail" and p["funding"]["stage"] == "Series B" and p["funding"]["age_months"] == 33
    h = p["headcount_trend"]
    assert h["change_pct"] == -0.12 and h["contraction"] is True and h["corroborates_layoffs"] is True
    assert "company_search" not in p["sections_unavailable"]
    assert any(x["id"] == "example.com:headcount" for x in p["provenance"])


def test_company_addition_for_204(tmp_path, monkeypatch):
    monkeypatch.setattr(client, "CACHE", tmp_path)
    empty = {"mode": "CACHED", "response": {"data": [], "empty": True}}
    p = depth.profile(empty, "newco.app", None, CFG, RUN, events=[])
    assert p["addition"]["submitted"] is False and "warm_depth" in p["addition"]["line"]
    put(tmp_path, "addition", "newco.app", {"request_id": "req_123", "status": "pending"})
    p = depth.profile(empty, "newco.app", None, CFG, RUN, events=[])
    assert p["addition"]["request_id"] == "req_123" and "req_123" in p["addition"]["line"]


# ---------------- warm-up script (no network)

def test_warm_depth_dry_run_needs_no_key(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("AKTA_API_KEY", raising=False)
    monkeypatch.setattr(warm_depth, "OUT", tmp_path)
    assert warm_depth.main(["--dry-run", "--only", "monday.com"]) == 0
    out = capsys.readouterr().out
    assert "3 calls" in out and "addition" not in out
    assert warm_depth.main(["--only", "monday.com"]) == 2  # no key: nothing fetched
    assert not any(tmp_path.rglob("*.json"))


def test_warm_depth_plans_addition_only_for_204(monkeypatch, tmp_path):
    monkeypatch.setattr(warm_depth, "OUT", tmp_path)
    (tmp_path / "enrichment").mkdir()
    (tmp_path / "enrichment" / "newco.app.json").write_text(json.dumps({"response": {"data": [], "empty": True}}))
    assert ("addition", "newco.app") in warm_depth.plan(["newco.app"], False)
    assert ("addition", "monday.com") not in warm_depth.plan(["monday.com"], False)
