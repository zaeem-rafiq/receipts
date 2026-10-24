"""Orchestrate ledger + match + Akta rules -> findings dict. All money math is here or in metrics.py."""
from datetime import date

import pandas as pd

from akta import client as akta
from akta import rules
from engine import load, match, metrics

QUESTIONS = {
    "AT_RISK": "{name} is {share} of MRR and had {event} on {date}; when does the contract renew and have you spoken to them since?",
    "PILOT_OR_CHURNED": "{name} appears on the deck but churned after {tenure} months; what did the pilot conclude?",
    "ONE_TIME": "{name} paid a {amount} setup fee and never subscribed; is a subscription in the pipeline?",
    "NOT_IN_LEDGER": "{name} is on the deck but has no charges; is it a signed-not-live customer, a design partner, or a logo from a prior company?",
    "VERIFIED": "{name} has paid for {tenure} months; may we call them as a reference?",
}
EVENT_WORDS = {"layoffs_major": "major layoffs", "layoffs_minor": "layoffs", "acquisition": "an acquisition announced",
               "shutdown": "a shutdown announced", "funding": "a funding round", "acquirer": "M&A (buyer)"}


def usd(n):
    return f"-${abs(int(n)):,}" if n < 0 else f"${int(n):,}"


def pct(x, d=1):
    return f"{100 * x:.{d}f}%"


def run(run_date=None, events_override=None, akta_enabled=True, data=load.DATA):
    """events_override: {slot: class} injects events (tests); akta_enabled=False -> events {} for every slot."""
    run_date = run_date or date.today()
    cfg = load.load_config(data / "config.yaml")
    as_of = pd.Timestamp(cfg["as_of"])
    charges, subs, customers = load.load_ledger(data)
    logos, claims, extraction_source = load.load_logos(data)
    claim = {c["id"]: c for c in claims}
    deck_arr = claim["arr"]["value"]
    ctab = metrics.customer_table(charges, subs, customers, as_of)
    h = metrics.headline(charges, subs, ctab, as_of, deck_arr)
    agree, nrows = metrics.type_column_agreement(charges)
    provenance = []
    modes = []

    out_logos = []
    for lg in logos:
        m = match.match_logo(lg["name"], customers, cfg)
        row = ctab[ctab["customer_id"] == m["customer_id"]].iloc[0].to_dict() if m["customer_id"] else None
        status = row["status"] if row else "NOT_IN_LEDGER"
        if status == "CHURNED":
            status = "PILOT"  # deck logos that churned are shown with pilots
        # Akta
        ak = {"domain": akta.domain_of(lg["website"]) if lg["website"] else "", "events": [], "mode": "OFF"}
        if akta_enabled and lg["website"]:
            enr = akta.get("enrichment", lg["website"])
            nws = akta.get("news", lg["website"])
            modes += [enr["mode"], nws["mode"]]
            fg = (enr.get("response") or {}).get("firmographic") or {}
            ak["headcount_range"] = fg.get("headcount_range")
            ak["operating_status"] = (fg.get("operating_status") or {}).get("label")
            ak["segment"], ak["headcount_lower"] = rules.segment_from_range(ak["headcount_range"], cfg)
            ak["events"] = rules.events_for(nws.get("response"), lg["name"], cfg, run_date)
            ak["fetched_at"] = nws.get("fetched_at")
            ak["mode"] = nws["mode"]
        else:
            ak["segment"], ak["headcount_range"] = "unverified", None
        top = rules.most_severe(ak["events"], ak.get("operating_status"))
        ev_class = top["class"] if top else "none"
        if events_override is not None:
            ev_class = events_override.get(lg["slot"], "none")
            top = {"class": ev_class, "trigger": "injected", "article_id": "", "title": "", "date": None} if ev_class != "none" else None
        weight = cfg["policy"].get(ev_class, 0.0)
        mrr_now = row["mrr_now"] if row else 0
        if status == "ACTIVE":
            verdict = "AT_RISK" if weight > 0 else "VERIFIED"
        elif status == "PILOT":
            verdict = "PILOT_OR_CHURNED"
        elif status == "ONE_TIME":
            verdict = "ONE_TIME"
        else:
            verdict = "NOT_IN_LEDGER"
        mrr_at_risk = int(round(mrr_now * weight)) if status == "ACTIVE" else 0
        card = {"VERIFIED": "green_plus" if ev_class == "funding" else "green", "AT_RISK": "amber",
                "PILOT_OR_CHURNED": "amber_pilot", "ONE_TIME": "grey",
                "NOT_IN_LEDGER": "red" if weight > 0 else "grey"}[verdict]
        q = QUESTIONS[verdict].format(
            name=lg["name"], share=pct(row["share_of_mrr"]) if row else "", event=EVENT_WORDS.get(ev_class, ev_class),
            date=(top or {}).get("date") or "a recent date", tenure=int(row["tenure_months"]) if row and pd.notna(row["tenure_months"]) else "",
            amount=usd(row["lifetime_revenue"]) if row else "")
        lp = [{"kind": "charge", "id": c} for c in (row["charge_ids"] if row else [])]
        lp += [{"kind": "subscription", "id": s} for s in (row["subscription_ids"] if row else [])]
        if top and top.get("article_id"):
            lp.append({"kind": "article", "id": top["article_id"]})
        lp.append({"kind": "rule", "id": f"policy.{ev_class}={weight}"})
        provenance.append({"slot": lg["slot"], "items": lp})
        out_logos.append({
            **lg, "customer_id": m["customer_id"], "match_tier": m["tier"], "nearest_name": m["nearest_name"], "nearest_ratio": m["ratio"],
            "status": status, "verdict": verdict, "card": card,
            "mrr_now": mrr_now, "tenure_months": int(row["tenure_months"]) if row and pd.notna(row["tenure_months"]) else None,
            "lifetime_revenue": row["lifetime_revenue"] if row else 0, "share_of_mrr": row["share_of_mrr"] if row else 0.0,
            "charge_ids": row["charge_ids"] if row else [], "subscription_ids": row["subscription_ids"] if row else [],
            "event_class": ev_class, "event": top, "weight": weight, "mrr_at_risk": mrr_at_risk,
            "question": q, "akta": ak,
        })

    rec_mrr, rec_arr = h["recurring_mrr"], h["recurring_arr"]
    mrr_at_risk = sum(l["mrr_at_risk"] for l in out_logos)
    exposed = [l for l in out_logos if l["status"] == "ACTIVE" and l["weight"] > 0]
    mrr_exposed = sum(l["mrr_now"] for l in exposed)
    logo_verified_mrr = sum(l["mrr_now"] for l in out_logos if l["verdict"] in ("VERIFIED", "AT_RISK"))
    ent = [l for l in out_logos if l["akta"].get("segment") == "enterprise"]
    any_akta = any(l["akta"].get("headcount_range") for l in out_logos)
    post = None
    import re
    mm = re.search(r"\$(\d+(?:\.\d+)?)M post-money", claim["ask"]["text"])
    post = int(float(mm.group(1)) * 1_000_000) if mm else None
    raise_ = claim["ask"]["value"]
    counts = {}
    for l in out_logos:
        counts[l["status"]] = counts.get(l["status"], 0) + 1

    headline = {
        "deck_arr": deck_arr, "recurring_mrr": rec_mrr, "recurring_arr": rec_arr,
        "mrr_at_risk": mrr_at_risk, "arr_at_risk": 12 * mrr_at_risk,
        "arr_at_risk_share": round(12 * mrr_at_risk / rec_arr, 4),
        "recurring_arr_not_at_risk": rec_arr - 12 * mrr_at_risk,
        "mrr_exposed": mrr_exposed, "arr_exposed": 12 * mrr_exposed, "exposure_share": round(12 * mrr_exposed / rec_arr, 4),
        "customers_with_risk_event": len(exposed),
        "enterprise_count": len(ent) if any_akta else None, "deck_enterprise_claim": claim["enterprise"]["value"],
        "top1_share": h["top1_share"], "top5_share": h["top5_share"],
        "logo_verified_arr": 12 * logo_verified_mrr, "logo_verified_share": round(logo_verified_mrr / rec_mrr, 4),
        "raise": raise_, "post_money": post,
        "multiples": {"on_deck_arr": round(post / deck_arr, 1), "on_recurring_arr": round(post / rec_arr, 1)},
        "deck_customers_claim": claim["customers"]["value"],
    }
    display = {
        "deck_arr": usd(deck_arr), "recurring_arr": usd(rec_arr), "recurring_mrr": usd(rec_mrr),
        "arr_at_risk": usd(headline["arr_at_risk"]), "arr_at_risk_pct": pct(headline["arr_at_risk_share"]),
        "arr_exposed": usd(headline["arr_exposed"]), "exposure_pct": pct(headline["exposure_share"]),
        "exposed_customers": str(len(exposed)),
        "top1_share": pct(h["top1_share"]), "top5_share": pct(h["top5_share"]),
        "enterprise": f"{headline['enterprise_count']} of {len(out_logos)}" if any_akta else "unverified",
        "deck_enterprise_claim": str(claim["enterprise"]["value"]),
        "customers_ever_billed": str(h["customers_ever_billed"]), "active_customers": str(h["active_customers"]),
        "logo_verified_arr": usd(headline["logo_verified_arr"]),
        "multiple_deck": f"{headline['multiples']['on_deck_arr']}x", "multiple_recurring": f"{headline['multiples']['on_recurring_arr']}x",
    }
    tie_out = [
        f"Charge kind classified from subscription_id + description; agrees with the file's type column on {agree}/{nrows} rows.",
        f"Implementation rows: {h['implementation_rows_sep']} in {as_of.strftime('%B')} vs {h['implementation_rows_prior_12m']} in the prior 12 months.",
        f"Exposure (unweighted): {display['arr_exposed']} of recurring ARR at {len(exposed)} customers with a risk event ({display['exposure_pct']}).",
        f"Bridge: {usd(h['bridge_start'])} " + " ".join(f"{'+' if b['delta'] >= 0 else '-'} {usd(abs(b['delta']))}" for b in h["bridge"])
        + f" = {usd(h['bridge_check'])} (recurring ARR {display['recurring_arr']}).",
    ]
    return {
        "headline": headline, "display": display, "ledger": h, "logos": out_logos, "tie_out_lines": tie_out,
        "logo_counts": counts, "provenance": provenance, "claims": claims,
        "meta": {"as_of": str(cfg["as_of"]), "run_date": run_date.isoformat(), "akta_mode": akta.mode_summary(modes) if akta_enabled else "OFF",
                 "extraction_source": extraction_source, "type_column_agreement": f"{agree}/{nrows}",
                 "live_budget_left": akta.budget_left(), "akta_offline": akta.offline()},
    }
