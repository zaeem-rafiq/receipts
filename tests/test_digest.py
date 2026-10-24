"""A news digest that mentions several companies never sets a verdict; a real article about the company still does."""
import datetime

from akta import rules
from engine import load

CFG = load.load_config()
RUN = datetime.date(2026, 10, 24)


def _resp(*articles):
    return {"data": list(articles)}


ROUNDUP = {"id": "a1", "title": "FinTech Futures: Top five news stories of the week – 23 October", "published_date": "2026-10-23T12:00:00",
           "publisher": "FinTech Futures", "tags": [{"code": "WT02", "is_primary": True}],
           "company_mentions": [{"website": "https://home.barclays", "is_primary": True}, {"website": "https://ramp.com", "is_primary": True}],
           "ai_summary": "Barclays plans to cut around 5,000 jobs this year, Ramp applied for a US trust bank charter, and Whop raised $200 million."}

MONDAY = {"id": "a2", "title": "Monday faces senior management exits amid AI restructuring", "published_date": "2026-10-17T16:32:34",
          "publisher": "CTech", "tags": [{"code": "WT02", "is_primary": True}], "company_mentions": [{"website": "https://monday.com", "is_primary": True}],
          "ai_summary": "Several senior executives at monday.com are expected to leave amid a restructuring that cuts about 20% of its workforce."}


def test_digest_titles():
    assert rules.is_digest(ROUNDUP)
    assert rules.is_digest({"title": "Startup Funding News Today, October 16, 2026: Ramp, Abby Care & More"})
    assert rules.is_digest({"title": "US Startup Funding Rounds October 2026 — Over $6 Billion in One Week"})
    assert not rules.is_digest(MONDAY)
    assert not rules.is_digest({"title": "Ramp secures $1.85B, homes in on AI"})
    assert not rules.is_digest({"title": "monday.com Gains as New Voice AI Launch Sparks Optimism | MNDY Stock News"})


def test_roundup_layoffs_do_not_move_ramp():
    evs = rules.events_for(_resp(ROUNDUP), "Ramp", CFG, RUN, domain="ramp.com")
    assert evs[0]["class"] == "layoffs_major" and evs[0]["digest"] and not evs[0]["primary"]  # still listed, flagged ignored
    assert rules.most_severe(evs) is None


def test_real_layoff_article_still_counts():
    evs = rules.events_for(_resp(MONDAY), "monday", CFG, RUN, domain="monday.com")
    assert evs[0]["primary"] and not evs[0]["digest"]
    assert rules.most_severe(evs)["class"] == "layoffs_major"
