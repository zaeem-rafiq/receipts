"""Every engine-computable value in tests/oracle.json, keyed by slot. Akta-dependent checks use the MOCK fixtures (or the real cache when present)."""
import json
from datetime import date
from pathlib import Path

import pytest

from engine import findings

T = Path(__file__).parent
O = json.loads((T / "oracle.json").read_text())
SLOTS = json.loads((T / "slot_map.json").read_text())
RUN = date(2026, 10, 24)


@pytest.fixture(scope="module")
def F():
    return findings.run(run_date=RUN)


@pytest.fixture(scope="module")
def F_no_events():
    return findings.run(run_date=RUN, events_override={})


@pytest.fixture(scope="module")
def F_injected():
    return findings.run(run_date=RUN, events_override={"logo_01": "layoffs_major", "logo_04": "acquisition"})


def defs(F):
    return {r["definition"]: r for r in F["ledger"]["reproduction"]}


def logo(F, slot):
    return next(l for l in F["logos"] if l["slot"] == slot)


# ---- ledger keys (events injected as {}) ----
LEDGER = [
    ("recurring_mrr", lambda F: F["headline"]["recurring_mrr"], O["recurring_mrr"]),
    ("recurring_arr", lambda F: F["headline"]["recurring_arr"], O["recurring_arr"]),
    ("deck_arr_claim", lambda F: F["headline"]["deck_arr"], O["deck_arr_claim"]),
    ("repro_value", lambda F: F["ledger"]["reproduction"][0]["value"], O["deck_arr_reproduction"]["value"]),
    ("repro_pct", lambda F: F["ledger"]["reproduction"][0]["pct_diff"], O["deck_arr_reproduction"]["pct_diff"]),
    ("comp_subscription", lambda F: F["ledger"]["components_sep"]["subscription"], O["deck_arr_reproduction"]["components"]["subscription"]),
    ("comp_implementation", lambda F: F["ledger"]["components_sep"]["implementation"], O["deck_arr_reproduction"]["components"]["implementation"]),
    ("comp_one_time", lambda F: F["ledger"]["components_sep"]["one_time"], O["deck_arr_reproduction"]["components"]["one_time"]),
    ("def_b", lambda F: F["ledger"]["reproduction"][1]["value"], O["other_definitions_not_within_2pct"]["12_x_sep_subscription_charges"]),
    ("def_c", lambda F: F["ledger"]["reproduction"][2]["value"], O["other_definitions_not_within_2pct"]["12_x_recurring_mrr"]),
    ("def_d", lambda F: F["ledger"]["reproduction"][3]["value"], O["other_definitions_not_within_2pct"]["12_x_trailing_3mo_avg_total"]),
    ("def_e", lambda F: F["ledger"]["reproduction"][4]["value"], O["other_definitions_not_within_2pct"]["trailing_12mo_total"]),
    ("def_f", lambda F: F["ledger"]["reproduction"][5]["value"], O["other_definitions_not_within_2pct"]["sum_active_contract_values"]),
    ("only_a_within_2pct", lambda F: [abs(r["pct_diff"]) <= 0.02 for r in F["ledger"]["reproduction"]], [True, False, False, False, False, False]),
    ("m07", lambda F: F["ledger"]["monthly_totals"]["07"], O["monthly_totals_2026"]["07"]),
    ("m08", lambda F: F["ledger"]["monthly_totals"]["08"], O["monthly_totals_2026"]["08"]),
    ("m09", lambda F: F["ledger"]["monthly_totals"]["09"], O["monthly_totals_2026"]["09"]),
    ("bridge_check", lambda F: F["ledger"]["bridge_check"], O["bridge_check"]),
    ("customers_ever_billed", lambda F: F["ledger"]["customers_ever_billed"], O["customers_ever_billed"]),
    ("active_customers", lambda F: F["ledger"]["active_customers"], O["active_customers"]),
    ("active_monthly", lambda F: F["ledger"]["active_monthly"], O["active_monthly"]),
    ("active_annual", lambda F: F["ledger"]["active_annual"], O["active_annual"]),
    ("logo_counts", lambda F: F["logo_counts"], O["logo_counts"]),
    ("logo_verified_arr", lambda F: F["headline"]["logo_verified_arr"], O["logo_verified_arr"]),
    ("logo_verified_share", lambda F: F["headline"]["logo_verified_share"], O["logo_verified_share_of_recurring"]),
    ("top1", lambda F: F["headline"]["top1_share"], O["top1_share"]),
    ("top5", lambda F: F["headline"]["top5_share"], O["top5_share"]),
    ("impl_sep", lambda F: F["ledger"]["implementation_rows_sep"], O["implementation_rows"]["sep_2026"]),
    ("impl_prior", lambda F: F["ledger"]["implementation_rows_prior_12m"], O["implementation_rows"]["prior_12_months"]),
    ("deck_enterprise_claim", lambda F: F["headline"]["deck_enterprise_claim"], O["deck_enterprise_claim"]),
    ("raise", lambda F: F["headline"]["raise"], O["ask"]["raise"]),
    ("post_money", lambda F: F["headline"]["post_money"], O["ask"]["post_money"]),
    ("mult_deck", lambda F: F["headline"]["multiples"]["on_deck_arr"], O["ask"]["multiple_on_deck_arr"]),
    ("mult_rec", lambda F: F["headline"]["multiples"]["on_recurring_arr"], O["ask"]["multiple_on_recurring_arr"]),
    ("type_agreement", lambda F: F["meta"]["type_column_agreement"], "320/320"),
]
for b in O["bridge"]:
    LEDGER.append((f"bridge_{b['step']}_rows", (lambda s: lambda F: next(x for x in F["ledger"]["bridge"] if x["step"] == s)["rows"])(b["step"]), b["rows"]))
    LEDGER.append((f"bridge_{b['step']}_delta", (lambda s: lambda F: next(x for x in F["ledger"]["bridge"] if x["step"] == s)["delta"])(b["step"]), b["delta"]))
for slot, cid in SLOTS.items():
    LEDGER.append((f"{slot}_customer_id", (lambda s: lambda F: logo(F, s)["customer_id"])(slot), cid))
for slot, exp in O["slots"].items():
    LEDGER.append((f"{slot}_status", (lambda s: lambda F: logo(F, s)["status"])(slot), exp["status"]))
    if "mrr" in exp:
        LEDGER.append((f"{slot}_mrr", (lambda s: lambda F: logo(F, s)["mrr_now"])(slot), exp["mrr"]))
    if "tenure_months" in exp:
        LEDGER.append((f"{slot}_tenure", (lambda s: lambda F: logo(F, s)["tenure_months"])(slot), exp["tenure_months"]))
    if "lifetime_revenue" in exp:
        LEDGER.append((f"{slot}_lifetime", (lambda s: lambda F: logo(F, s)["lifetime_revenue"])(slot), exp["lifetime_revenue"]))


@pytest.mark.parametrize("name,get,exp", LEDGER, ids=[x[0] for x in LEDGER])
def test_ledger(F_no_events, name, get, exp):
    assert get(F_no_events) == exp


def test_slot01_rows_equal_tenure(F_no_events):
    assert len(logo(F_no_events, "logo_01")["charge_ids"]) == O["slots"]["logo_01"]["tenure_months"]


def test_matching_tiers(F_no_events):
    for s in O["matching"]["alias_slots"]:
        assert logo(F_no_events, s)["match_tier"] == "exact_or_alias"
    for s in O["matching"]["normalized_only_slots"]:
        assert logo(F_no_events, s)["match_tier"] == "normalized"
    for s in O["matching"]["must_not_match"]:
        assert logo(F_no_events, s)["customer_id"] == ""


# ---- risk with injected events (no Akta dependency) ----
def test_risk_injected(F_injected):
    h = F_injected["headline"]
    assert (h["mrr_at_risk"], h["arr_at_risk"], h["mrr_exposed"]) == (O["mrr_at_risk"], O["arr_at_risk"], O["exposure_unweighted"]["mrr_exposed"])
    assert h["arr_exposed"] == O["exposure_unweighted"]["arr_exposed"]
    assert h["arr_at_risk_share"] == O["arr_at_risk_share_of_recurring"]
    assert h["exposure_share"] == O["exposure_unweighted"]["share_of_recurring"]
    assert h["recurring_arr_not_at_risk"] == O["recurring_arr_not_at_risk"]
    assert h["customers_with_risk_event"] == O["exposure_unweighted"]["customers_with_risk_event"]


# ---- full run over the Akta cache (MOCK fixtures until the real cache lands) ----
CARD = [(s, e) for s, e in O["slots"].items()]


@pytest.mark.parametrize("slot,exp", CARD, ids=[c[0] for c in CARD])
def test_cards_with_akta(F, slot, exp):
    l = logo(F, slot)
    assert l["card"] == exp["card"]
    if "weight" in exp:
        assert l["weight"] == exp["weight"]
    if "mrr_at_risk" in exp:
        assert l["mrr_at_risk"] == exp["mrr_at_risk"]


def test_headline_with_akta(F):
    h = F["headline"]
    assert (h["mrr_at_risk"], h["arr_at_risk"], h["arr_exposed"]) == (O["mrr_at_risk"], O["arr_at_risk"], O["exposure_unweighted"]["arr_exposed"])
    assert h["enterprise_count"] == O["enterprise_count_expected"]
