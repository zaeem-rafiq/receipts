"""Logo name -> customer_id. Tiers: exact/alias -> normalized exact -> difflib >= min_ratio with margin -> NOT_IN_LEDGER."""
import difflib
import re


def normalize(name, legal_suffixes):
    s = name.lower().strip()
    s = re.sub(r"[^\w\s]", " ", s)
    toks = s.split()
    sufs = {x.strip(".").lower() for x in legal_suffixes}
    while toks and toks[-1] in sufs:
        toks.pop()
    return "".join(toks)


def match_logo(name, customers, cfg):
    sufs = cfg["match"]["legal_suffixes"]
    # tier 1: exact name or alias
    for _, c in customers.iterrows():
        names = [c["name"]] + [a for a in str(c["aliases"]).split("|") if a]
        if any(name.strip().lower() == n.strip().lower() for n in names):
            return {"customer_id": c["customer_id"], "tier": "exact_or_alias", "ratio": 1.0, "nearest_name": c["name"]}
    # tier 2: normalized exact
    target = normalize(name, sufs)
    for _, c in customers.iterrows():
        names = [c["name"]] + [a for a in str(c["aliases"]).split("|") if a]
        if any(target == normalize(n, sufs) for n in names):
            return {"customer_id": c["customer_id"], "tier": "normalized", "ratio": 1.0, "nearest_name": c["name"]}
    # tier 3: fuzzy with margin
    scored = []
    for _, c in customers.iterrows():
        r = difflib.SequenceMatcher(None, target, normalize(c["name"], sufs)).ratio()
        scored.append((r, c["customer_id"], c["name"]))
    scored.sort(reverse=True)
    best = scored[0]
    runner = scored[1][0] if len(scored) > 1 else 0.0
    if best[0] >= cfg["match"]["fuzzy_min_ratio"] and best[0] - runner >= cfg["match"]["fuzzy_min_margin"]:
        return {"customer_id": best[1], "tier": "fuzzy", "ratio": round(best[0], 2), "nearest_name": best[2]}
    return {"customer_id": "", "tier": "none", "ratio": round(best[0], 2), "nearest_name": best[2]}
