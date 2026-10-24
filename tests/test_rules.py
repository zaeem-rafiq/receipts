import yaml
from pathlib import Path
from akta import rules

CFG = yaml.safe_load((Path(__file__).parent.parent / "data_room" / "config.yaml").read_text())
BRAZE = {"title": "Salesforce agreed to acquire Braze", "ai_summary": "Salesforce agreed to acquire Braze for about $5.66B.", "types": [{"code": "CM03"}]}


def test_cm03_target():
    assert rules.classify(BRAZE, "Braze", CFG)["class"] == "acquisition"


def test_cm03_buyer():
    assert rules.classify(BRAZE, "Salesforce", CFG)["class"] == "acquirer"


def test_layoff_major_pct():
    a = {"title": "x", "ai_summary": "cuts roughly 20% of staff", "types": [{"code": "WT02"}]}
    assert rules.classify(a, "x", CFG)["class"] == "layoffs_major"


def test_layoff_minor():
    a = {"title": "x", "ai_summary": "cuts 7% of staff, 40 people", "types": [{"code": "WT02"}]}
    assert rules.classify(a, "x", CFG)["class"] == "layoffs_minor"


def test_shutdown_keyword():
    a = {"title": "Relay will shut down", "ai_summary": "", "types": []}
    c = rules.classify(a, "Relay", CFG)
    assert c["class"] == "shutdown" and c["keyword_classified"]


def test_segment():
    assert rules.segment_from_range("1001-5000", CFG)[0] == "enterprise"
    assert rules.segment_from_range("201-500", CFG)[0] == "mid"
    assert rules.segment_from_range("10001+", CFG)[0] == "enterprise"
    assert rules.segment_from_range("weird", CFG)[0] == "unverified"
