"""Akta client: disk cache keyed by (endpoint, domain). Order: real cache -> live (if key and budget) -> MOCK fixture -> unresolved.

AKTA_OFFLINE=1 (default) never calls out. AKTA_LIVE_BUDGET caps uncached live lookups for the whole process.
Live path follows PLAN.md section 6; it is UNTESTED from this sandbox (no key here).
"""
import hashlib
import json
import os
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

from integrations import env  # noqa: F401  (loads .env / Streamlit secrets into os.environ)

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "demo_cache" / "akta"
MOCK = CACHE / "mock"
BASE = "https://api.akta.pro/api/v1/"
SECTIONS = "firmographic,financial_estimate,company_hierarchy,strategic_signal"
_live_used = 0  # module-level, survives Streamlit reruns
ERRORS = {}  # (endpoint, domain) -> last live failure, for the UI; never persisted


def domain_of(website):
    w = website if "://" in website else "https://" + website
    d = urlparse(w).netloc.lower()
    return d[4:] if d.startswith("www.") else d


def offline():
    return os.environ.get("AKTA_OFFLINE", "1") != "0"


def budget_left():
    return max(0, int(os.environ.get("AKTA_LIVE_BUDGET", "0")) - _live_used)


def _read(path):
    if path.exists():
        return json.loads(path.read_text())
    return None


def _live(endpoint, domain):
    global _live_used
    import requests
    key = os.environ.get("AKTA_API_KEY")
    if not key or offline() or budget_left() <= 0:
        return None
    today = date.today()
    if endpoint == "enrichment":
        url, params = BASE + "company/enrichment", {"company": domain, "sections": SECTIONS}
    else:
        url, params = BASE + "news", {"company": domain, "start_date": (today - timedelta(days=180)).isoformat(),
                                      "end_date": today.isoformat(), "limit": 50}
    _live_used += 1
    resp, err = None, None
    try:
        for wait in (0, 2, 4, 8):
            time.sleep(wait or 2.5)
            r = requests.get(url, params=params, headers={"x-api-key": key}, timeout=30)
            if r.status_code == 204:
                resp = {"data": [], "empty": True}
                break
            if r.status_code in (429, 500, 502, 503, 504):
                err = f"HTTP {r.status_code}"
                continue
            if r.status_code >= 400:  # 401 bad key, 403 plan/section, 404, 422: never retried, never cached
                err = f"HTTP {r.status_code}"
                break
            resp, err = r.json(), None
            break
    except (requests.RequestException, ValueError) as e:  # timeout, DNS, bad JSON: degrade, never crash the page
        resp, err = None, type(e).__name__
    if resp is None:
        ERRORS[(endpoint, domain)] = err or "unknown"
        return None  # nothing persisted: get() falls through to the MOCK fixture or unresolved
    ERRORS.pop((endpoint, domain), None)
    if endpoint == "news" and isinstance(resp.get("data"), list):
        for a in resp["data"]:
            a.pop("full_text", None)
            a.pop("original_language", None)
            a.setdefault("id", hashlib.sha1(a.get("url", "").encode()).hexdigest()[:12])
    rec = {"fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "params": params, "response": resp, "mode": "LIVE"}
    out = CACHE / endpoint / f"{domain}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=1))
    return rec


def get(endpoint, website):
    domain = domain_of(website)
    rec = _read(CACHE / endpoint / f"{domain}.json")
    if rec:
        rec["mode"] = "CACHED"  # a file written by an earlier LIVE call is a cache hit now, never LIVE
        return rec
    rec = _live(endpoint, domain)
    if rec:
        return rec
    rec = _read(MOCK / endpoint / f"{domain}.json")
    if rec:
        rec["mode"] = "MOCK"
        return rec
    return {"unresolved": True, "mode": "MISS", "response": {}}


def mode_summary(modes):
    """Header badge text. Honest about mixtures: any MOCK or MISS in the run is named with its share."""
    if not modes:
        return "OFF"
    n = len(modes)
    real = sum(1 for m in modes if m in ("LIVE", "CACHED"))
    if real == n:
        return "LIVE" if "LIVE" in modes else "CACHED"
    mock = sum(1 for m in modes if m == "MOCK")
    miss = n - real - mock
    parts = [f"{mock} MOCK" if mock else "", f"{real} real" if real else "", f"{miss} missing" if miss else ""]
    return ("MOCK " if mock else "MISS ") + "(" + ", ".join(p for p in parts if p) + f" of {n})"
