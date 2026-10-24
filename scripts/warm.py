"""T0 Akta warm-up: fill demo_cache/akta/{enrichment,news}/<domain>.json for the 12 logo slots
and the pre-warmed live-panel names, so the public host runs cache-only (AKTA_OFFLINE=1).

Run on a laptop where AKTA_API_KEY is exported in the shell (never paste it anywhere else):
    python scripts/warm.py                 # default sections, skips domains already cached
    python scripts/warm.py --force         # refetch everything
    python scripts/warm.py --only monday.com,braze.com
    AKTA_SECTIONS=firmographic,financial_estimate,company_hierarchy,strategic_signal,company_assessment \
        python scripts/warm.py --force     # deeper pass (section credits add up; see docs/AKTA_DEPTH.md)

403 and 5xx answers are logged and NOT cached, so the MOCK fixture still serves that domain.
204 (no match) is cached as empty: that logo slot needs a swap or Company Addition.
The key is read from the environment by akta.client and never printed.
"""
import argparse
import csv
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from akta import client  # noqa: E402

# Not-in-ledger slots (Relay, Linear) plus the pre-warmed live-panel names from PLAN.md section 6.
EXTRA = ["relay.app", "linear.app", "ramp.com", "cloudflare.com", "miro.com", "rippling.com",
         "notion.so", "vanta.com", "hubspot.com", "airtable.com", "posthog.com", "wix.com"]


def targets():
    slot_map = json.loads((ROOT / "tests" / "slot_map.json").read_text())
    with open(ROOT / "data_room" / "customers.csv", newline="") as f:
        rows = {r["customer_id"]: r for r in csv.DictReader(f)}
    doms = []
    for _slot, cid in slot_map.items():
        r = rows.get(cid)
        if r and r.get("website"):
            d = client.domain_of(r["website"])
            if d not in doms:
                doms.append(d)
    for d in EXTRA:
        if d not in doms:
            doms.append(d)
    return doms


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="refetch domains that are already cached")
    ap.add_argument("--budget", type=int, default=60, help="max live calls this run (2 per domain)")
    ap.add_argument("--only", default="", help="comma-separated domains")
    ap.add_argument("--sections", default=os.environ.get("AKTA_SECTIONS", client.SECTIONS))
    a = ap.parse_args(argv)
    if not os.environ.get("AKTA_API_KEY"):
        print("AKTA_API_KEY is not set in this shell. Export it and re-run. Nothing was fetched.")
        return 2
    os.environ["AKTA_OFFLINE"] = "0"
    os.environ["AKTA_LIVE_BUDGET"] = str(a.budget)
    client.SECTIONS = a.sections
    only = {d.strip() for d in a.only.split(",") if d.strip()}
    doms = [d for d in targets() if not only or d in only]
    print(f"{len(doms)} domains, sections={a.sections}, budget={a.budget} calls")
    stats = {"fetched": 0, "cached": 0, "empty": 0, "not_cached_403": 0, "not_cached_error": 0}
    empties, failures = [], []
    for d in doms:
        for ep in ("enrichment", "news"):
            path = client.CACHE / ep / f"{d}.json"
            if path.exists() and not a.force:
                stats["cached"] += 1
                print(f"  {ep:10s} {d:18s} already cached")
                continue
            if client.budget_left() <= 0:
                print("budget exhausted; re-run with --budget to continue")
                break
            try:
                rec = client._live(ep, d)
            except Exception as e:  # network or JSON failure: log, keep going
                rec, err = None, f"{type(e).__name__}: {e}"
                print(f"  {ep:10s} {d:18s} FAILED {err}")
                failures.append((ep, d, err))
                stats["not_cached_error"] += 1
                continue
            resp = (rec or {}).get("response") or {}
            if rec is None:
                print(f"  {ep:10s} {d:18s} skipped (no key, offline or budget)")
            elif resp.get("forbidden"):
                path.unlink(missing_ok=True)
                stats["not_cached_403"] += 1
                failures.append((ep, d, "403: plan or section not allowed"))
                print(f"  {ep:10s} {d:18s} 403 (not cached; MOCK still serves it)")
            elif resp.get("error"):
                path.unlink(missing_ok=True)
                stats["not_cached_error"] += 1
                failures.append((ep, d, f"HTTP {resp['error']}"))
                print(f"  {ep:10s} {d:18s} HTTP {resp['error']} (not cached)")
            elif resp.get("empty"):
                stats["empty"] += 1
                empties.append((ep, d))
                print(f"  {ep:10s} {d:18s} 204 no match (cached as empty)")
            else:
                stats["fetched"] += 1
                n = len(resp.get("data", [])) if ep == "news" else len(resp)
                print(f"  {ep:10s} {d:18s} ok ({n} {'articles' if ep == 'news' else 'sections'})")
    print("\nsummary:", json.dumps(stats))
    if empties:
        print("no match (swap the slot or use Company Addition):", ", ".join(f"{ep}/{d}" for ep, d in empties))
    if failures:
        print("not cached:", "; ".join(f"{ep}/{d}: {why}" for ep, d, why in failures))
    print(f"cache dir: {client.CACHE}  (commit demo_cache/akta/enrichment and /news; the mock/ folder stays)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
