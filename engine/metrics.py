"""Per-customer status/MRR/tenure, recurring MRR/ARR, deck ARR reproduction, bridge, concentration. Deterministic pandas only."""
import pandas as pd


def month_index(d):
    return d.year * 12 + d.month


def customer_table(charges, subs, customers, as_of):
    ok = charges[charges["status"] == "succeeded"]
    rows = []
    for _, c in customers.iterrows():
        cid = c["customer_id"]
        cs = subs[subs["customer_id"] == cid]
        ch = ok[ok["customer_id"] == cid]
        active = cs[cs["status"].isin(["active", "past_due"]) & (cs["start"] <= as_of)]
        if len(cs) == 0:
            status = "ONE_TIME" if len(ch) else "NO_CHARGES"
            tenure = None
        else:
            start = cs["start"].min()
            if len(active):
                end = as_of
            else:
                end = cs["canceled_at"].max()
            tenure = month_index(end) - month_index(start) + 1
            if len(active):
                status = "ACTIVE"
            else:
                status = "PILOT" if tenure <= 3 else "CHURNED"
        mrr = 0
        for _, s in active.iterrows():
            mrr += s["amount"] / 12 if s["interval"] == "year" else s["amount"]
        rows.append({
            "customer_id": cid,
            "name": c["name"],
            "status": status,
            "mrr_now": int(round(mrr)),
            "tenure_months": tenure,
            "lifetime_revenue": int(ch["amount"].sum()),
            "charge_ids": list(ch.sort_values("created")["charge_id"]),
            "subscription_ids": list(cs["subscription_id"]),
            "active_interval": (active["interval"].iloc[0] if len(active) else None),
        })
    t = pd.DataFrame(rows)
    total = t["mrr_now"].sum()
    t["share_of_mrr"] = t["mrr_now"] / total if total else 0.0
    return t


def month_slice(ok, year, month):
    return ok[(ok["created"].dt.year == year) & (ok["created"].dt.month == month)]


def headline(charges, subs, ctab, as_of, deck_arr):
    ok = charges[charges["status"] == "succeeded"]
    sep = month_slice(ok, as_of.year, as_of.month)
    recurring_mrr = int(ctab["mrr_now"].sum())
    recurring_arr = 12 * recurring_mrr

    # trailing months
    def prev(y, m, k):
        idx = y * 12 + (m - 1) - k
        return idx // 12, idx % 12 + 1

    m3_slices = [month_slice(ok, *prev(as_of.year, as_of.month, k)) for k in range(3)]
    m3 = [s["amount"].sum() for s in m3_slices]
    m3_ids = [cid for s in m3_slices for cid in s["charge_id"]]
    ttm_start = pd.Timestamp(*prev(as_of.year, as_of.month, 11), 1)
    ttm = ok[(ok["created"] >= ttm_start) & (ok["created"] <= as_of)]
    active_subs = subs[subs["status"].isin(["active", "past_due"])]
    contract_values = sum(s["amount"] if s["interval"] == "year" else 12 * s["amount"] for _, s in active_subs.iterrows())

    defs = [
        ("12 x total succeeded charges in " + as_of.strftime("%b %Y"), 12 * int(sep["amount"].sum()), list(sep["charge_id"])),
        ("12 x subscription charges in " + as_of.strftime("%b %Y"), 12 * int(sep[sep["subkind"] == "subscription"]["amount"].sum()),
         list(sep[sep["subkind"] == "subscription"]["charge_id"])),
        ("12 x recurring MRR (annual ratable)", recurring_arr, list(active_subs["subscription_id"])),
        ("12 x trailing 3-month average of total charges", int(round(4 * sum(m3))), m3_ids),
        ("trailing 12-month total charges", int(ttm["amount"].sum()), list(ttm["charge_id"])),
        ("sum of active contract values", int(contract_values), list(active_subs["subscription_id"])),
    ]
    reproduction = [{"definition": d, "value": v, "pct_diff": round((v - deck_arr) / deck_arr, 4), "ids": ids} for d, v, ids in defs]

    impl = sep[sep["subkind"].isin(["implementation", "setup"])]
    one = sep[sep["subkind"] == "one_time"]
    annual_subs = active_subs[active_subs["interval"] == "year"]
    annual_in_sep = sep[sep["subkind"] == "prepaid_annual"]
    other_month_annual = annual_subs[~annual_subs["subscription_id"].isin(annual_in_sep["subscription_id"])]
    bridge = [
        {"step": "implementation_fees_sep_annualized", "rows": len(impl), "row_ids": list(impl["charge_id"]), "delta": -12 * int(impl["amount"].sum())},
        {"step": "one_time_services_sep_annualized", "rows": len(one), "row_ids": list(one["charge_id"]), "delta": -12 * int(one["amount"].sum())},
        {"step": "annual_contracts_other_months_ratable", "rows": len(other_month_annual), "row_ids": list(other_month_annual["subscription_id"]),
         "delta": int(other_month_annual["amount"].sum())},
    ]
    sep_total_arr = 12 * int(sep["amount"].sum())
    bridge_check = sep_total_arr + sum(b["delta"] for b in bridge)

    impl_all = ok[ok["subkind"] == "implementation"]
    prior_start = pd.Timestamp(as_of.year - 1, as_of.month, 1)
    impl_prior = impl_all[(impl_all["created"] >= prior_start) & (impl_all["created"] < pd.Timestamp(as_of.year, as_of.month, 1))]
    impl_sep = month_slice(impl_all, as_of.year, as_of.month)

    active = ctab[ctab["status"] == "ACTIVE"]
    shares = sorted(active["mrr_now"], reverse=True)
    return {
        "recurring_mrr": recurring_mrr,
        "recurring_arr": recurring_arr,
        "reproduction": reproduction,
        "bridge": bridge,
        "bridge_start": sep_total_arr,
        "bridge_check": bridge_check,
        "monthly_totals": {f"{prev(as_of.year, as_of.month, k)[1]:02d}": int(m3[k]) for k in range(3)},
        "monthly_total_ids": {f"{prev(as_of.year, as_of.month, k)[1]:02d}": list(m3_slices[k]["charge_id"]) for k in range(3)},
        "ttm_total": int(ttm["amount"].sum()),
        "ttm_ids": list(ttm["charge_id"]),
        "implementation_prior_12m_ids": list(impl_prior["charge_id"]),
        "implementation_sep_ids": list(impl_sep["charge_id"]),
        "customers_ever_billed_ids": sorted(ok["customer_id"].unique().tolist()),
        "customers_ever_billed": int(ok["customer_id"].nunique()),
        "active_customers": len(active),
        "active_monthly": int((active["active_interval"] == "month").sum()),
        "active_annual": int((active["active_interval"] == "year").sum()),
        "top1_share": round(shares[0] / recurring_mrr, 4),
        "top5_share": round(sum(shares[:5]) / recurring_mrr, 4),
        "implementation_rows_sep": len(impl_sep),
        "implementation_rows_prior_12m": len(impl_prior),
        "components_sep": {
            "subscription": int(sep[sep["kind"] == "recurring"]["amount"].sum()),
            "implementation": int(impl["amount"].sum()),
            "one_time": int(one["amount"].sum()),
        },
    }


def type_column_agreement(charges):
    agree = (charges["subkind"] == charges["type"]).sum()
    return int(agree), len(charges)
