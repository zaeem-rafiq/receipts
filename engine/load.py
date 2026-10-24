"""Read and validate the data room. Charge kind is derived from subscription_id + description, never the type column."""
import json
import re
from pathlib import Path

import pandas as pd
import yaml

DATA = Path(__file__).resolve().parent.parent / "data_room"

ONE_TIME_KEYWORDS = ["implementation", "setup", "migration", "backfill", "training", "services"]
SUFFIX = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}


def load_config(path=DATA / "config.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)


def derive_kind(row, sub_interval):
    """Return (kind, subkind). kind is recurring|one_time; subkind mirrors the file's type vocabulary."""
    if isinstance(row["subscription_id"], str) and row["subscription_id"]:
        interval = sub_interval.get(row["subscription_id"], "month")
        return "recurring", ("prepaid_annual" if interval == "year" else "subscription")
    desc = str(row["description"]).lower()
    if "implementation" in desc:
        return "one_time", "implementation"
    if "setup" in desc:
        return "one_time", "setup"
    if any(k in desc for k in ONE_TIME_KEYWORDS):
        return "one_time", "one_time"
    return "one_time", "unclassified"


def load_ledger(data=DATA):
    charges = pd.read_csv(data / "stripe_charges.csv", dtype={"subscription_id": str})
    subs = pd.read_csv(data / "stripe_subscriptions.csv")
    customers = pd.read_csv(data / "customers.csv").fillna("")
    charges["subscription_id"] = charges["subscription_id"].fillna("")
    charges["created"] = pd.to_datetime(charges["created"])
    subs["start"] = pd.to_datetime(subs["start"])
    subs["canceled_at"] = pd.to_datetime(subs["canceled_at"])
    sub_interval = dict(zip(subs["subscription_id"], subs["interval"]))
    kinds = charges.apply(lambda r: derive_kind(r, sub_interval), axis=1)
    charges["kind"] = [k[0] for k in kinds]
    charges["subkind"] = [k[1] for k in kinds]
    assert charges["charge_id"].is_unique
    assert set(charges["customer_id"]) <= set(customers["customer_id"])
    return charges, subs, customers


def load_logos(data=DATA):
    """Logos and claims. claims.json (LLM extraction) wins when present; else logos_fallback.json."""
    fallback = json.loads((data / "logos_fallback.json").read_text())
    source = "fallback"
    claims_path = data / "claims.json"
    doc = fallback
    if claims_path.exists():
        doc = json.loads(claims_path.read_text())
        source = doc.get("source", "llm")
    websites = {norm_simple(l["name"]): l["website"] for l in fallback["logos"]}
    logos = []
    for i, l in enumerate(doc["logos"]):
        logos.append({
            "slot": l.get("slot") or f"logo_{i + 1:02d}",
            "name": l["name"],
            "website": websites.get(norm_simple(l["name"]), l.get("website", "")),
            "slide": l.get("slide"),
        })
    claims = []
    for c in doc["claims"]:
        claims.append({**c, "value": parse_claim_number(c["text"])})
    return logos, claims, source


def norm_simple(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def parse_claim_number(text):
    """First money-or-count figure in a claim. '$1.2M ARR' -> 1200000; '48 customers' -> 48. Regex only, never an LLM."""
    m = re.search(r"\$?\s*(\d[\d,]*(?:\.\d+)?)\s*([kKmMbB])?\b", text)
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    if m.group(2):
        n *= SUFFIX[m.group(2).lower()]
    return int(round(n))


def parse_all_numbers(text):
    out = []
    for m in re.finditer(r"\$?\s*(\d[\d,]*(?:\.\d+)?)\s*([kKmMbB])?\b", text):
        n = float(m.group(1).replace(",", ""))
        if m.group(2):
            n *= SUFFIX[m.group(2).lower()]
        out.append(int(round(n)))
    return out


def deck_text(data=DATA):
    return (data / "deck.md").read_text()
