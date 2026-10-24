"""Akta depth warm-up: the calls scripts/warm.py does not make, cached for akta/depth.py (docs/AKTA_DEPTH.md Layers 1 and 2).

    company search      GET  company/search?query=<website>                         -> demo_cache/akta/search/<domain>.json      (0 credits, 100/day)
    funding + M&A       GET  company/enrichment?sections=funding_detail,ma_and_investment -> demo_cache/akta/enrichment_depth/<domain>.json (3 + 5 credits)
    headcount trends    GET  alternative-data/headcount-trends?company=<website>     -> demo_cache/akta/headcount/<domain>.json   (2.5 credits)
    company addition    POST company/addition {"website": ...}, only for logos whose enrichment cache is a 204 -> demo_cache/akta/addition/<domain>.json (0 credits)

Run on the laptop where AKTA_API_KEY is exported (never paste it anywhere else):
    python scripts/warm_depth.py --dry-run     # list the calls and the credit estimate; needs no key
    python scripts/warm_depth.py               # the 12 logo slots, skips anything already cached
    python scripts/warm_depth.py --all         # plus the live-panel names warm.py caches
    python scripts/warm_depth.py --only monday.com,braze.com --force

UNVERIFIED (docs.akta.pro was unreachable from the build sandbox): the search, headcount-trends and addition paths,
their query/body parameter names, and every response shape; whether the promo plan includes funding_detail,
ma_and_investment and alternative data. A 403/404/422 is logged and NOT cached, so the card just shows the
section as unavailable. If one combined section call is refused, each section is retried alone.
The key is read from the environment and never printed.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from akta import client  # noqa: E402
from integrations import env  # noqa: E402,F401  (loads .env into os.environ)

OUT = client.CACHE
CREDITS = {"search": 0, "depth": 8, "headcount": 2.5, "addition": 0}
DIRS = {"search": "search", "depth": "enrichment_depth", "headcount": "headcount", "addition": "addition"}


def slot_domains():
    logos = json.loads((ROOT / "data_room" / "logos_fallback.json").read_text())["logos"]
    return [client.domain_of(l["website"]) for l in logos if l.get("website")]


def enrichment_empty(domain):
    rec = client._read(OUT / "enrichment" / f"{domain}.json")
    return bool(rec and (rec.get("response") or {}).get("empty"))


def call(method, path, params=None, body=None):
    """One Akta request with warm.py's retry rules. Returns (status, json-or-None)."""
    import requests
    key = os.environ["AKTA_API_KEY"]
    status = None
    for wait in (2.5, 2, 4, 8):
        time.sleep(wait)
        try:
            r = requests.request(method, client.BASE + path, params=params, json=body,
                                 headers={"x-api-key": key}, timeout=30)
        except requests.RequestException as e:
            status = type(e).__name__
            continue
        status = r.status_code
        if status == 204:
            return 204, {"data": [], "empty": True}
        if status in (429, 500, 502, 503, 504):
            continue
        if status >= 400:
            return status, None
        try:
            return status, r.json()
        except ValueError:
            return "bad json", None
    return status, None


def save(kind, domain, params, status, resp):
    p = OUT / DIRS[kind] / f"{domain}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "params": params, "status": status,
                             "response": resp, "mode": "LIVE"}, indent=1))


def plan(domains, force):
    jobs = []
    for d in domains:
        for kind in ("search", "depth", "headcount"):
            if force or not (OUT / DIRS[kind] / f"{d}.json").exists():
                jobs.append((kind, d))
        if enrichment_empty(d) and (force or not (OUT / "addition" / f"{d}.json").exists()):
            jobs.append(("addition", d))
    return jobs


def run_job(kind, d):
    if kind == "search":
        params = {"query": d}
        st, resp = call("GET", "company/search", params)
    elif kind == "headcount":
        params = {"company": d}
        st, resp = call("GET", "alternative-data/headcount-trends", params)
    elif kind == "addition":
        params = {"website": d}
        st, resp = call("POST", "company/addition", body=params)
    else:
        params = {"company": d, "sections": "funding_detail,ma_and_investment"}
        st, resp = call("GET", "company/enrichment", params)
        if resp is None and st in (403, 422):  # plan may allow one section and not the other
            merged, got = {}, []
            for sec in ("funding_detail", "ma_and_investment"):
                s2, r2 = call("GET", "company/enrichment", {"company": d, "sections": sec})
                print(f"  {d} {sec}: {s2}")
                if r2:
                    data = r2.get("data", r2)
                    if isinstance(data, dict):
                        merged.update({k: v for k, v in data.items() if k == sec})
                        got.append(sec)
            if got:
                params, st, resp = {"company": d, "sections": ",".join(got)}, 200, {"data": merged}
    if resp is None:
        print(f"  {kind:9s} {d}: {st} (not cached)")
        return False
    save(kind, d, params, st, resp)
    print(f"  {kind:9s} {d}: {st} cached")
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--all", action="store_true", help="also the live-panel names from scripts/warm.py")
    ap.add_argument("--only", default="", help="comma-separated domains")
    ap.add_argument("--force", action="store_true", help="refetch what is already cached")
    ap.add_argument("--dry-run", action="store_true", help="print the calls and credits, call nothing")
    ap.add_argument("--budget", type=int, default=60, help="max calls this run")
    a = ap.parse_args(argv)
    if a.only:
        domains = [client.domain_of(x.strip()) for x in a.only.split(",") if x.strip()]
    else:
        domains = slot_domains()
        if a.all:
            from scripts import warm
            domains += [d for d in warm.EXTRA if d not in domains]
    jobs = plan(domains, a.force)
    credits = sum(CREDITS[k] for k, _ in jobs)
    print(f"{len(jobs)} calls for {len(domains)} domains, about {credits:g} credits (section prices from docs/AKTA_DEPTH.md; plan tier UNVERIFIED)")
    if a.dry_run:
        for k, d in jobs:
            print(f"  {k:9s} {d}")
        return 0
    if not os.environ.get("AKTA_API_KEY"):
        print("AKTA_API_KEY is not set in this shell. Export it and re-run. Nothing was fetched.")
        return 2
    ok = 0
    for k, d in jobs[: a.budget]:
        ok += run_job(k, d)
    print(f"done: {ok}/{min(len(jobs), a.budget)} cached. Commit demo_cache/akta/{{search,enrichment_depth,headcount,addition}}/ to build/t0.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
