"""Akta depth: the Profile and World columns of a receipt (docs/AKTA_DEPTH.md). Deterministic; no LLM; no money.

world(): every tagged article in the news record, not just the most severe one: counts by code, family and sentiment,
plus an on-subject flag (the logo's own website is an is_primary company mention on the article).
profile(): the company record (firmographic, financial_estimate, company_hierarchy, strategic_signal sections),
plus the extra calls scripts/warm_depth.py caches (company search status, funding_detail, ma_and_investment,
headcount trends, company addition). Each extra is null when its cache file is absent; nothing is mocked.

Shapes of search / funding_detail / ma_and_investment / headcount-trends / addition responses are UNVERIFIED
(docs.akta.pro was not reachable from the build sandbox), so their parsers are defensive and keep the raw source path.
"""
import json
import re
from collections import Counter
from datetime import date
from functools import wraps

from akta import client, rules

WEIGHTED = ["RK07", "CM03", "WT02", "CM01", "CM09", "SD01"]  # the codes rules.py turns into a policy class
EXTRA_DIRS = {"search": "search", "depth": "enrichment_depth", "headcount": "headcount", "addition": "addition"}


def body(rec):
    """Real cache nests under response.data; the MOCK fixtures do not. Accept both."""
    r = (rec or {}).get("response") or {}
    d = r.get("data", r) if isinstance(r, dict) else r
    return d if isinstance(d, dict) else {}


def extra(kind, domain):
    """Cached result of one warm_depth.py call, or None. Never calls out."""
    p = client.CACHE / EXTRA_DIRS[kind] / f"{domain}.json"
    if not p.exists():
        return None
    try:
        rec = json.loads(p.read_text())
    except ValueError:
        return None
    rec["mode"] = "CACHED"
    rec["path"] = f"demo_cache/akta/{EXTRA_DIRS[kind]}/{domain}.json"
    return rec


def _label(v):
    if isinstance(v, dict):
        return v.get("label") or v.get("code")
    return v


def _ym(d):
    """{'month': 6, 'year': 2025} or '2025-06-..' -> (year, month) or None. Month defaults to 1 when only a year is given."""
    if isinstance(d, dict) and d.get("year"):
        return int(d["year"]), int(d.get("month") or 1)
    m = re.match(r"(\d{4})-(\d{2})", str(d or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


def _months_between(ym, run_date):
    return (run_date.year - ym[0]) * 12 + run_date.month - ym[1]


def _ym_str(ym):
    return f"{ym[0]}-{ym[1]:02d}" if ym else None


# ---------------------------------------------------------------- World

def on_subject(article, domain):
    """True if the logo's own website is an is_primary mention; False if it is only a passing mention;
    None if the article carries no company_mentions (MOCK fixtures)."""
    ms = article.get("company_mentions")
    if not ms:
        return None
    for m in ms:
        if client.domain_of(m.get("website") or "") == domain and m.get("is_primary"):
            return True
    return False


def _never_raise(fn):
    """The engine hook must never break a run: empty input -> {}, any failure -> {"error": name}."""
    @wraps(fn)
    def inner(rec, *a, **k):
        if not rec:
            return {}
        try:
            return fn(rec, *a, **k)
        except Exception as e:  # noqa: BLE001 (labels only; the money path never depends on this)
            return {"error": type(e).__name__}
    return inner


def _domain(rec, domain):
    return domain or client.domain_of(str(((rec or {}).get("params") or {}).get("company") or "")) or ""


def _cfg(cfg):
    if cfg is None:
        from engine import load
        cfg = load.load_config()
    return cfg


def _events_from_cache(domain, cfg, run_date):
    """Same deterministic rules as the engine, read straight from the news cache file (no live call)."""
    rec = client._read(client.CACHE / "news" / f"{domain}.json") or client._read(client.MOCK / "news" / f"{domain}.json")
    return rules.events_for((rec or {}).get("response"), domain.split(".")[0], cfg, run_date) if rec else []


@_never_raise
def world(news_rec, events=None, domain=None, top=None):
    domain = _domain(news_rec, domain)
    if top is None and events:
        top = rules.most_severe(events)
    resp = (news_rec or {}).get("response") or {}
    arts = resp.get("data") if isinstance(resp.get("data"), list) else []
    by_code, by_family, by_sent, names = Counter(), Counter(), Counter(), {}
    subj = {}
    for a in arts:
        aid = str(a.get("id", ""))
        s = on_subject(a, domain)
        subj[aid] = s
        if s is False:
            continue  # passing mentions stay out of the ledger counts; they are listed as off-subject
        for t in a.get("tags") or a.get("types") or []:
            code = t.get("code") if isinstance(t, dict) else str(t)
            if not code:
                continue
            by_code[code] += 1
            by_family[code[:2]] += 1
            if isinstance(t, dict) and t.get("name"):
                names[code] = t["name"]
        by_sent[str(a.get("sentiment", "")).lower() or "unknown"] += 1
    read = len(arts)
    total = resp.get("total", read) if isinstance(resp.get("total"), int) else read
    on = sum(1 for v in subj.values() if v is True)
    off = sum(1 for v in subj.values() if v is False)
    weighted = {c: by_code[c] for c in WEIGHTED if by_code.get(c)}
    top_id = str((top or {}).get("article_id") or "")
    top_subject = subj.get(top_id) if top_id else None
    off_events = [e["article_id"] for e in (events or []) if subj.get(str(e.get("article_id"))) is False]
    counted = read - off
    if not read:
        line = "No articles in the 180-day window." if not news_rec or not news_rec.get("unresolved") else "News not checked."
    else:
        sent = ", ".join(f"{by_sent[k]} {k}" for k in ("positive", "neutral", "negative") if by_sent.get(k))
        line = (f"Read {read} of {total} articles (180 days); {counted} about {domain}" + (f" ({sent})" if sent else "")
                + (", tagged " + ", ".join(f"{c} x{n}" for c, n in weighted.items()) if weighted else ", no weighted tags")
                + (f"; {off} passing mentions set aside" if off else "") + ".")
    return {
        "articles_read": read, "articles_total": total, "articles_on_subject": on, "articles_off_subject": off,
        "by_code": dict(by_code.most_common()), "by_family": dict(by_family.most_common()), "by_sentiment": dict(by_sent),
        "code_names": names, "weighted_codes": weighted,
        "top_codes": [{"code": c, "name": names.get(c, ""), "n": n} for c, n in by_code.most_common(5)],
        "top_event_on_subject": top_subject, "off_subject_event_ids": off_events,
        "momentum_line": line, "mode": news_rec.get("mode"), "fetched_at": news_rec.get("fetched_at"),
        "provenance": [{"kind": "article", "id": aid, "on_subject": s} for aid, s in subj.items()],
    }


# ---------------------------------------------------------------- Profile

_BAND = re.compile(r"^(\d+(?:\.\d+)?)([kmb])_(\d+(?:\.\d+)?)([kmb])$|^(\d+(?:\.\d+)?)([kmb])_plus$")
_MULT = {"k": 1e3, "m": 1e6, "b": 1e9}


def revenue_band(code):
    """'250m_500m' -> (250e6, 500e6); '1b_5b' -> (1e9, 5e9); 'pre_revenue' -> (0, 0); unknown -> None."""
    if not code:
        return None
    if code == "pre_revenue":
        return (0, 0)
    m = _BAND.match(str(code))
    if not m:
        return None
    if m.group(5):
        return (float(m.group(5)) * _MULT[m.group(6)], None)
    return (float(m.group(1)) * _MULT[m.group(2)], float(m.group(3)) * _MULT[m.group(4)])


def _moves(ss, run_date):
    out = []
    for kind in ("recent_move", "leadership_change"):
        for x in (ss or {}).get(kind) or []:
            ym = _ym(x.get("date"))
            out.append({"kind": kind, "type": ((x.get("type") or {}).get("code")), "date": _ym_str(ym),
                        "months_ago": _months_between(ym, run_date) if ym else None,
                        "description": x.get("description", ""), "source": (x.get("source") or [None])[0]})
    return sorted(out, key=lambda m: m["date"] or "", reverse=True)


def _funding(dep, moves, company_type, run_date, cfg):
    """funding_detail section if warm_depth cached it, else the latest funding_round in strategic_signal.recent_move."""
    fd = (dep or {}).get("funding_detail")
    src, last = None, None
    if fd:
        rounds = fd if isinstance(fd, list) else (fd.get("rounds") or fd.get("funding_rounds") or [fd])
        dated = [(r, _ym(r.get("date") or r.get("announced_on") or r.get("announced_date"))) for r in rounds if isinstance(r, dict)]
        dated = [d for d in dated if d[1]]
        if dated:
            r, ym = max(dated, key=lambda d: d[1])
            last = {"date": _ym_str(ym), "stage": _label(r.get("stage") or r.get("round_type") or r.get("series")),
                    "amount": _label(r.get("amount") or r.get("amount_raised") or r.get("money_raised")), "ym": ym}
            src = "funding_detail"
    if last is None and str(company_type).lower() == "private":  # a public company's "funding_round" moves are not venture rounds
        fr = [m for m in moves if m["kind"] == "recent_move" and m["type"] == "funding_round" and m["date"]]
        if fr:
            m = fr[0]
            last = {"date": m["date"], "stage": None, "amount": None, "description": m["description"],
                    "source_url": m["source"], "ym": _ym(m["date"])}
            src = "strategic_signal.recent_move"
    if last is None:
        return None
    age = _months_between(last.pop("ym"), run_date)
    limit = cfg.get("depth", {}).get("funding_aged_months", 24)
    return {**last, "age_months": age, "section": src,
            "funding_aged": bool(age > limit and str(company_type).lower() == "private"),
            "line": f"Last round {last['date']} ({age} months ago, from Akta {src})"}


def _ma(dep, moves, hierarchy, ev_class, run_date, cfg):
    """Structural M&A role. ma_and_investment if cached; else hierarchy subsidiaries / recent_move acquisitions
    (the company as buyer). News stays the only target-side source unless ma_and_investment says otherwise."""
    window = cfg.get("recent_window_days", 180) // 30
    buys = []
    for s in (hierarchy or {}).get("subsidiaries") or []:
        ym = _ym(s.get("acquired_on"))
        if ym and _months_between(ym, run_date) <= window:
            buys.append({"name": s.get("name"), "date": _ym_str(ym), "source": "company_hierarchy.subsidiaries"})
    for m in moves:
        if m["type"] == "acquisition" and m["months_ago"] is not None and m["months_ago"] <= window:
            buys.append({"name": None, "date": m["date"], "description": m["description"], "source": "strategic_signal.recent_move"})
    mi = (dep or {}).get("ma_and_investment")
    role, section = None, None
    if mi:
        txt = json.dumps(mi).lower()
        if '"target"' in txt or '"acquiree"' in txt:
            role, section = "target", "ma_and_investment"
        elif '"acquirer"' in txt or '"buyer"' in txt:
            role, section = "acquirer", "ma_and_investment"
    if role is None and buys:
        role, section = "acquirer", buys[0]["source"]
    if role is None and ev_class == "acquisition":
        role, section = "target", "news (pending; not in the company record)"
    if role is None:
        return None
    return {"role": role, "section": section, "recent_acquisitions": buys,
            "confirms_news": (ev_class == "acquirer" and role == "acquirer") or (ev_class == "acquisition" and role == "target" and section == "ma_and_investment")}


def _status_check(fg, search, ev_class, domain):
    rec_status = str(_label(fg.get("operating_status")) or "").strip()
    ctype = str(_label(fg.get("company_type")) or "").strip()
    srch = None
    raw = ((search or {}).get("response") or {}).get("data") if search else None
    sb = body(search) if search else None
    if isinstance(raw, list):  # real Company Search shape: response.data is a ranked list of candidates
        cands = raw
    elif sb:
        cands = sb.get("results") or sb.get("companies") or ([sb] if sb.get("company_status") else [])
    else:
        cands = []
    if cands:
        for c in cands if isinstance(cands, list) else []:
            if not isinstance(c, dict):
                continue
            if client.domain_of(str(c.get("website", ""))) == domain or len(cands) == 1:
                srch = _label(c.get("company_status"))
                break
    status = srch or ctype
    source = "Company Search company_status" if srch else "enrichment firmographic"
    low = f"{status} {rec_status}".lower()
    if ev_class == "acquisition":
        if "acquired" in low:
            agrees, line = True, f"Akta company record: {status} ({source}); confirms the acquisition."
        else:
            agrees, line = None, f"Akta company record still says {status}, {rec_status}: the deal is announced, not closed."
    elif ev_class == "shutdown":
        if any(k in low for k in ("shut", "closed", "delisted", "defunct")):
            agrees, line = True, f"Akta company record: {status}, {rec_status}; confirms the shutdown."
        else:
            agrees, line = False, f"Conflict: Akta company record says {status}, {rec_status}; the shutdown rests on news alone."
    elif any(k in low for k in ("acquired", "shut", "closed", "delisted")):
        agrees, line = False, (f"Akta {source} lists status '{status}' (operating status: {rec_status or 'not given'}); "
                              "no matching event in the 180-day news window. Ask the founder.")
    else:
        agrees, line = True, f"Akta company record: {status}, {rec_status}."
    return {"company_status": status or None, "operating_status": rec_status or None, "source": source,
            "agrees": agrees, "line": line}


def _headcount(hc, cfg, wt02_on_subject):
    """Headcount Trends -> change over the series and a contraction LABEL (weight 0 in money; see config depth)."""
    b = body(hc) if hc else None
    if b is None and hc and isinstance((hc.get("response") or {}).get("data"), list):
        b = {"series": hc["response"]["data"]}
    if not b:
        return None
    series = None
    for k in ("series", "data", "trends", "headcount_trends", "history", "points"):
        if isinstance(b.get(k), list):
            series = b[k]
            break
    pts = []
    for p in series or []:
        if not isinstance(p, dict):
            continue
        ym = _ym(p.get("date") or p.get("month") or p.get("period"))
        v = next((p[k] for k in ("headcount", "total_headcount", "employee_count", "count", "value", "total") if isinstance(p.get(k), (int, float))), None)
        if ym and v is not None:
            pts.append((ym, float(v)))
    pts.sort()
    if len(pts) < 2 or pts[0][1] <= 0:
        return {"points": len(pts), "change_pct": None, "contraction": False, "line": "Headcount trend returned too few points."}
    chg = (pts[-1][1] - pts[0][1]) / pts[0][1]
    thr = cfg.get("depth", {}).get("contraction_min_drop", 0.10)
    contraction = chg <= -thr
    return {"points": len(pts), "from": _ym_str(pts[0][0]), "to": _ym_str(pts[-1][0]),
            "start": int(pts[0][1]), "end": int(pts[-1][1]), "change_pct": round(chg, 4),
            "series": [int(v) for _, v in pts],
            "contraction": contraction, "corroborates_layoffs": bool(contraction and wt02_on_subject),
            "line": f"Headcount {int(pts[0][1]):,} ({_ym_str(pts[0][0])}) to {int(pts[-1][1]):,} ({_ym_str(pts[-1][0])}), "
                    f"{100 * chg:+.1f}%" + (" : contraction" if contraction else "")}


@_never_raise
def profile(enr_rec, domain=None, row=None, cfg=None, run_date=None, events=None, wld=None):
    run_date = run_date or date.today()
    cfg = _cfg(cfg)
    domain = _domain(enr_rec, domain)
    mrr_now = (row or {}).get("mrr_now", 0) or 0
    if events is None:
        events = _events_from_cache(domain, cfg, run_date)
    top = rules.most_severe(events)
    ev_class = top["class"] if top else "none"
    b = body(enr_rec)
    fg = b.get("firmographic") or {}
    fe = b.get("financial_estimate") or {}
    hier = b.get("company_hierarchy") or {}
    ss = b.get("strategic_signal") or {}
    dep_rec = extra("depth", domain)
    dep = body(dep_rec) if dep_rec else None
    search, hc, add = extra("search", domain), extra("headcount", domain), extra("addition", domain)
    empty = bool(enr_rec and ((enr_rec.get("response") or {}).get("empty") or enr_rec.get("unresolved")))
    moves = _moves(ss, run_date)
    rev = fe.get("revenue_estimate") or {}
    band = revenue_band(rev.get("code") if isinstance(rev, dict) else None)
    arr = 12 * int(mrr_now or 0)
    if band is None or not rev:
        size_line = None
    elif band[0] == 0:
        size_line = f"Akta revenue estimate: {_label(rev)}." + (f" Pays {client_usd(arr)} ARR." if arr else "")
    else:
        share = 100 * arr / band[0]
        size_line = (f"Pays {client_usd(arr)} ARR against an Akta revenue estimate of {_label(rev)} "
                     f"(at most {share:.1f}% of their revenue)." if arr and share >= 1 else
                     f"Pays {client_usd(arr)} ARR against an Akta revenue estimate of {_label(rev)} "
                     f"(at most {share:.3f}% of their revenue)." if arr else f"Akta revenue estimate: {_label(rev)}.")
    wt02 = bool((wld or {}).get("weighted_codes", {}).get("WT02"))
    sections = ["firmographic", "financial_estimate", "company_hierarchy", "strategic_signal"]
    unavailable = [s for s in sections if s not in b]
    if dep is None:
        unavailable += ["funding_detail", "ma_and_investment"]
    else:
        unavailable += [s for s in ("funding_detail", "ma_and_investment") if s not in dep]
    if search is None:
        unavailable.append("company_search")
    if hc is None:
        unavailable.append("headcount_trends")
    funding = _funding(dep, moves, _label(fg.get("company_type")), run_date, cfg)
    ma = _ma(dep, moves, hier, ev_class, run_date, cfg)
    status = _status_check(fg, search, ev_class, domain) if fg else None
    addition = None
    if empty:
        ab = body(add) if add else {}
        addition = {"submitted": bool(add), "request_id": ab.get("request_id") or ab.get("id") if add else None,
                    "status": _label(ab.get("status")) if add else None,
                    "line": (f"Not in Akta yet; submitted for addition (request {ab.get('request_id') or ab.get('id') or 'id not returned'})."
                             if add else "Not in Akta yet; run scripts/warm_depth.py to submit it through Company Addition.")}
    prov = [{"kind": "company", "id": f"{domain}:{sec}:{fld}"} for sec, fld in (
        ("firmographic", "company_type"), ("firmographic", "operating_status"), ("firmographic", "headcount_range"),
        ("financial_estimate", "revenue_estimate"), ("financial_estimate", "valuation_estimate"),
        ("company_hierarchy", "subsidiaries"), ("strategic_signal", "recent_move")) if (b.get(sec) or {}).get(fld)]
    for kind, rec in (("search", search), ("depth", dep_rec), ("headcount", hc), ("addition", add)):
        if rec:
            prov.append({"kind": "company", "id": f"{domain}:{EXTRA_DIRS[kind]}", "path": rec["path"], "fetched_at": rec.get("fetched_at")})
    return {
        "name": fg.get("name"), "legal_name": fg.get("legal_name"),
        "company_type": _label(fg.get("company_type")), "ticker": fg.get("ticker"), "founded_year": fg.get("founded_year"),
        "headcount_range": fg.get("headcount_range"),
        "revenue_estimate": _label(rev) if rev else None, "valuation_estimate": _label(fe.get("valuation_estimate")),
        "size_line": size_line,
        "subsidiaries": [{"name": s.get("name"), "acquired_on": _ym_str(_ym(s.get("acquired_on"))), "type": _label(s.get("type"))}
                         for s in hier.get("subsidiaries") or []],
        "subsidiaries_count": len(hier.get("subsidiaries") or []),
        "recent_moves": moves[:5], "recent_move": moves[0]["description"] if moves else None,
        "scale_indicators": [{"type": (x.get("type") or {}).get("code"), "value": x.get("value"), "description": x.get("description")}
                             for x in (ss.get("scale_indicator") or [])[:5]],
        "funding": funding, "funding_aged": bool(funding and funding["funding_aged"]),
        "ma": ma, "ma_role": (ma or {}).get("role"),
        "status_check": status, "company_status": (status or {}).get("company_status"),
        "headcount_trend": _headcount(hc, cfg, wt02), "headcount_trend_6m": None,
        "addition": addition, "event_class_seen": ev_class,
        "mode": enr_rec.get("mode"), "fetched_at": enr_rec.get("fetched_at"),
        "sections_unavailable": unavailable,
        "provenance": prov,
    }


def client_usd(n):
    return f"${int(n):,}"


def lines(col):
    """The plain strings the UI prints for one column (a world() or profile() dict), in order; [] when empty or failed."""
    if not col or "error" in col:
        return []
    if "momentum_line" in col:
        return [col["momentum_line"]]
    out = [col.get("size_line"), (col.get("status_check") or {}).get("line"), (col.get("funding") or {}).get("line"),
           (col.get("headcount_trend") or {}).get("line"), (col.get("addition") or {}).get("line")]
    return [s for s in out if s]
