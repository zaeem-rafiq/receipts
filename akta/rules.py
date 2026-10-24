"""Akta articles -> event class -> policy weight. Deterministic; no LLM."""
import re
from datetime import date, datetime, timedelta

SEVERITY = ["shutdown", "acquisition", "layoffs_major", "layoffs_minor", "acquirer", "funding", "product_launch", "none"]
SHUTDOWN_KW = ["ceased operations", "shut down", "shuts down", "shutting down", "winding down", "wind down", "bankruptcy", "shutdown"]
SHUTDOWN_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k in SHUTDOWN_KW) + r")\b", re.I)
NOT_SHUTDOWN_RE = re.compile(r"\b(government|federal)\s+shutdown\b", re.I)


def _text(a):
    return f"{a.get('title', '')} {a.get('ai_summary', '')}"


def _codes(a):
    tags = a.get("types") or a.get("tags") or []
    out = []
    for t in tags:
        out.append(t.get("code") if isinstance(t, dict) else str(t))
    return [c for c in out if c]


def layoff_class(text, cfg):
    ev = cfg["events"]
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(%|percent)", text):
        if float(m.group(1)) >= ev["layoffs_major_min_pct"]:
            return "layoffs_major", f"percent >= {ev['layoffs_major_min_pct']}"
    for m in re.finditer(r"(\d[\d,]*)\s+(people|employees|staff|jobs|workers)", text):
        if int(m.group(1).replace(",", "")) >= ev["layoffs_major_min_people"]:
            return "layoffs_major", f"people >= {ev['layoffs_major_min_people']}"
    for kw in ev["layoffs_major_keywords"]:
        if re.search(rf"\b{kw}\b", text, re.I):
            return "layoffs_major", f"keyword '{kw}'"
    return "layoffs_minor", "below thresholds"


def is_target_side(text, name):
    n = re.escape(name.split(".")[0] if name.lower().endswith(".com") else name)
    pats = [
        rf"(acquir(e|es|ed|ing)|to buy|buys|agreed to acquire|acquisition of)\s+(\w+\s){{0,3}}{n}",
        rf"{n}\s+(is|to be|will be)\s+acquired",
    ]
    parts = text if isinstance(text, (list, tuple)) else [text]
    return any(re.search(p, t, re.I) for p in pats for t in parts)


def classify(article, company_name, cfg):
    """Return dict(class, trigger, keyword_classified)."""
    text = _text(article)
    codes = _codes(article)
    if "RK07" in codes:
        return {"class": "shutdown", "trigger": "Akta code RK07", "keyword_classified": False}
    if SHUTDOWN_RE.search(NOT_SHUTDOWN_RE.sub(" ", article.get("title", ""))):
        # No Akta code means shutdown (PLAN section 6); a shutdown headline outranks any other tag on the same article.
        return {"class": "shutdown", "trigger": "shutdown keyword in title", "keyword_classified": True}
    if "CM03" in codes:
        if is_target_side([article.get("title", ""), article.get("ai_summary", "")], company_name):
            return {"class": "acquisition", "trigger": "CM03 + target-side match", "keyword_classified": True}
        return {"class": "acquirer", "trigger": "CM03, buyer side", "keyword_classified": True}
    if "WT02" in codes:
        c, trig = layoff_class(text, cfg)
        return {"class": c, "trigger": trig, "keyword_classified": False}
    if "CM01" in codes or "CM09" in codes:
        return {"class": "funding", "trigger": "Akta code CM01/CM09", "keyword_classified": False}
    if "SD01" in codes:
        return {"class": "product_launch", "trigger": "Akta code SD01", "keyword_classified": False}
    # Keyword fallback only when Akta gave no usable tag (PLAN section 6); whole words, not substrings.
    if SHUTDOWN_RE.search(NOT_SHUTDOWN_RE.sub(" ", text)):
        return {"class": "shutdown", "trigger": "shutdown keyword (no Akta tag)", "keyword_classified": True}
    return {"class": "none", "trigger": "no weighted code", "keyword_classified": False}


def parse_date(s):
    if not s:
        return None
    s = str(s)[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def events_for(news_response, company_name, cfg, run_date):
    window_start = run_date - timedelta(days=cfg["recent_window_days"])
    out = []
    for a in (news_response or {}).get("data", []):
        d = parse_date(a.get("published_date"))
        c = classify(a, company_name, cfg)
        out.append({
            "code": ",".join(_codes(a)),
            "class": c["class"],
            "trigger": c["trigger"],
            "keyword_classified": c["keyword_classified"],
            "date": d.isoformat() if d else None,
            "in_window": bool(d and window_start <= d <= run_date),
            "title": a.get("title", ""),
            "url": a.get("url", ""),
            "publisher": a.get("publisher", ""),
            "article_id": a.get("id", ""),
            "sentiment": str(a.get("sentiment", "")).lower(),
        })
    return out


def most_severe(events, operating_status=None):
    if operating_status and str(operating_status).lower() in ("shut down", "shutdown", "closed"):
        return {"class": "shutdown", "trigger": "operating_status Shut Down", "article_id": "", "title": "", "date": None}
    inw = [e for e in events if e["in_window"]]
    if not inw:
        return None
    return sorted(inw, key=lambda e: SEVERITY.index(e["class"]))[0]


def segment_from_range(hr, cfg):
    if not hr:
        return "unverified", None
    m = re.search(r"(\d[\d,]*)\s*[-–]\s*(\d[\d,]*)|(\d[\d,]*)\+", str(hr))
    if not m:
        return "unverified", None
    lo = int((m.group(1) or m.group(3)).replace(",", ""))
    b = cfg["segment_bands"]
    if lo > b["mid_max"]:
        return "enterprise", lo
    if lo > b["smb_max"]:
        return "mid", lo
    return "smb", lo
