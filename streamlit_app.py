"""Receipts: the logo slide of a seed deck, checked against the ledger and the world. Prototype."""
import json
from datetime import date

import streamlit as st

from akta import client as akta
from akta import rules
from engine import findings, load
from integrations import nicrron, prism, roundtable
from llm import summarize

st.set_page_config(page_title="Receipts", layout="wide")

COLORS = {"green": "#1f9d55", "green_plus": "#1f9d55", "amber": "#d97706", "amber_pilot": "#b7791f", "grey": "#718096", "red": "#c53030"}
LABEL = {"green": "VERIFIED", "green_plus": "VERIFIED +", "amber": "AT RISK", "amber_pilot": "PILOT", "grey": "", "red": "NOT IN LEDGER"}


@st.cache_data(show_spinner=False)
def compute(run_date_iso, akta_on):
    run = prism.Run()
    with run.span("engine", run_date=run_date_iso, akta=akta_on):
        F = findings.run(run_date=date.fromisoformat(run_date_iso), akta_enabled=akta_on)
    for l in F["logos"]:
        with run.span(f"akta/{l['akta']['domain'] or l['name']}", mode=l["akta"]["mode"], event=l["event_class"]):
            pass
    S = summarize.summarize(F["display"], run)
    F["summary"] = S
    v = roundtable.put_file("findings.json", {k: F[k] for k in ("headline", "display", "tie_out_lines", "meta")}, note="engine run")
    F["meta"]["roundtable_findings_version"] = v
    _, cv = roundtable.get_file("claims.json")
    F["meta"]["roundtable_claims_version"] = cv
    F["meta"]["prism_trace_id"] = run.trace_id
    F["meta"]["prism_spans"] = [s["name"] for s in run.spans]
    run.save()
    return F


def E(s):
    """Escape $ so Streamlit markdown does not render dollar amounts as LaTeX."""
    return str(s).replace("$", "\\$")


def usd(n):
    return E(findings.usd(n))


def badge(name, state, ok):
    color = "#1f9d55" if ok else "#a0aec0"
    return f"<span style='background:{color};color:white;padding:2px 8px;border-radius:10px;margin-right:6px;font-size:0.8rem'>{name} {state}</span>"


# ---------- header ----------
st.title("Receipts")
st.caption("Twelve logos on a seed deck, each checked against the customer revenue export and against the outside world (Akta).")
st.warning("Fictional startup (Bramblefin); customer names are real public companies used for demonstration; the commercial relationships "
           "and the ledger are invented. **Prototype:** Akta data below is a MOCK fixture unless the badge says CACHED or LIVE.")

with st.sidebar:
    st.header("Run")
    run_date = st.date_input("Run date (news window anchor)", value=date.today())
    akta_on = st.toggle("Akta on", value=True, help="Off = events {} for every slot; shows how load-bearing Akta is.")
    st.caption(f"AKTA_OFFLINE={'1' if akta.offline() else '0'} · live budget left: {akta.budget_left()}")

F = compute(run_date.isoformat(), akta_on)
H, D, M = F["headline"], {k: E(v) for k, v in F["display"].items()}, F["meta"]

st.markdown(
    badge("Akta", M["akta_mode"], M["akta_mode"] in ("CACHED", "LIVE"))
    + badge("Nicrron", nicrron.MODEL if nicrron.enabled() else "OFF", nicrron.enabled())
    + badge("PRISM", f"trace {M['prism_trace_id']}" + ("" if prism.enabled() else " (local only)"), prism.enabled())
    + badge("Roundtable", f"claims v{M['roundtable_claims_version']} / findings v{M['roundtable_findings_version']}"
            + ("" if roundtable.enabled() else " (local stub)"), roundtable.enabled()),
    unsafe_allow_html=True)

# ---------- strip ----------
c1, c2, c3, c4 = st.columns(4)
c1.metric("Deck ARR (slide 4)", F["display"]["deck_arr"])
c2.metric("Recurring ARR (ledger)", F["display"]["recurring_arr"])
c3.metric("ARR flagged (policy-weighted)", F["display"]["arr_at_risk"], help="Screening weights, not a valuation. Never subtracted into ARR or used in a multiple.")
c4.metric("Top customer share of MRR", F["display"]["top1_share"])
st.caption(f"Exposure (unweighted): {D['arr_exposed']} of recurring ARR sits with {D['exposed_customers']} customers that had a risk event "
           f"({D['exposure_pct']}). Ask: {D['multiple_deck']} deck ARR vs {D['multiple_recurring']} recurring ARR.")

# ---------- summary ----------
with st.container(border=True):
    st.markdown("**Summary**  \n" + E(F["summary"]["text"]).replace("\n", "  \n"))
    st.caption(f"Source: {F['summary']['source']}. Digit guardrail: every number must appear in the engine's display strings"
               + (f"; blocked tokens: {F['summary']['guardrail_failures']}" if F["summary"]["guardrail_failures"] else "; pass."))

# ---------- tie-out ----------
with st.expander("Tie-out: how the deck's number was built"):
    import pandas as pd
    rep = pd.DataFrame([{k: r[k] for k in ("definition", "value", "pct_diff")} for r in F["ledger"]["reproduction"]])
    rep["within 2%"] = rep["pct_diff"].abs() <= 0.02
    rep["value"] = rep["value"].map(findings.usd)
    rep["pct_diff"] = rep["pct_diff"].map(lambda x: f"{100 * x:+.1f}%")
    st.dataframe(rep, hide_index=True, width="stretch")
    br = pd.DataFrame([{"step": b["step"], "rows": b["rows"], "delta": findings.usd(b["delta"]), "row ids": ", ".join(b["row_ids"])} for b in F["ledger"]["bridge"]])
    st.dataframe(br, hide_index=True, width="stretch")
    for line in F["tie_out_lines"]:
        st.markdown(f"- {E(line)}")

# ---------- wall ----------
st.subheader("Logo wall (deck slide 5)")
if "sel" not in st.session_state:
    st.session_state.sel = "logo_01"
cols = st.columns(6)
for i, l in enumerate(F["logos"]):
    with cols[i % 6]:
        color = COLORS[l["card"]]
        sub = {"ACTIVE": f"{usd(l['mrr_now'])}/mo · {l['tenure_months']} mo", "PILOT": f"pilot, {l['tenure_months']} mo, canceled",
               "ONE_TIME": f"one-time {usd(l['lifetime_revenue'])}", "NOT_IN_LEDGER": "no charges"}[l["status"]]
        ev = l["event_class"] if l["event_class"] != "none" else ""
        st.markdown(f"<div style='border-left:6px solid {color};padding:6px 8px;background:rgba(127,127,127,0.08);border-radius:6px;min-height:92px'>"
                    f"<b>{l['name']}</b><br><span style='color:{color};font-weight:600'>{LABEL[l['card']] or l['status'].replace('_', ' ')}</span><br>"
                    f"<small>{sub}</small><br><small>{ev}</small></div>", unsafe_allow_html=True)
        if st.button("Receipt", key=f"b_{l['slot']}", width="stretch"):
            st.session_state.sel = l["slot"]

# ---------- receipt ----------
l = next(x for x in F["logos"] if x["slot"] == st.session_state.sel)
st.subheader(f"Receipt: {l['name']}  ·  {l['verdict'].replace('_', ' ')}")
a, b, c = st.columns(3)
with a:
    st.markdown("**Ledger**")
    if l["customer_id"]:
        st.write(f"Customer `{l['customer_id']}` (match: {l['match_tier']}, billed as “{l['nearest_name']}”)")
        st.markdown(f"Status {l['status']} · MRR {usd(l['mrr_now'])} · tenure {l['tenure_months'] or 'n/a'} months · "
                 f"lifetime {usd(l['lifetime_revenue'])} · {len(l['charge_ids'])} charge rows")
        charges, _, _ = load.load_ledger()
        st.dataframe(charges[charges["charge_id"].isin(l["charge_ids"])][["charge_id", "created", "amount", "subkind", "description"]],
                     hide_index=True, width="stretch", height=220)
    else:
        st.write(f"Not in the ledger. Nearest ledger name: {l['nearest_name']} (ratio {l['nearest_ratio']}).")
with b:
    st.markdown("**Profile (Akta Company Data)**")
    ak = l["akta"]
    st.write(f"Domain {ak['domain'] or 'n/a'} · headcount range {ak.get('headcount_range') or 'unverified'} · segment {ak.get('segment')}")
    st.write(f"Operating status: {ak.get('operating_status') or 'unverified'}")
    st.caption(f"Mode: {ak['mode']}" + (f" · fetched {ak.get('fetched_at')}" if ak.get("fetched_at") else ""))
with c:
    st.markdown("**World (Akta News, 180 days)**")
    if not ak["events"]:
        st.write("No articles in window.")
    for e in ak["events"]:
        st.markdown(E(f"{e['date']} · {e['publisher']}: {e['title']}"))
        st.caption(f"code {e['code'] or 'none'} → {e['class']} ({e['trigger']}{', keyword-classified' if e['keyword_classified'] else ''})"
                   f"{'' if e['in_window'] else ' · outside window'}")
    st.write(f"Policy weight **{l['weight']:.2f}** → MRR flagged **{usd(l['mrr_at_risk'])}**")
st.info(E(f"Second-meeting question: {l['question']}"))

# ---------- enterprise check ----------
st.subheader("Enterprise check")
st.write(f"**{D['enterprise']}** logos over 1,000 employees (deck claim: {D['deck_enterprise_claim']} enterprise customers).")
st.dataframe([{"logo": x["name"], "headcount_range": x["akta"].get("headcount_range"), "segment": x["akta"].get("segment")} for x in F["logos"]],
             hide_index=True, width="stretch")

# ---------- live panel ----------
st.subheader("Check any company")
q = st.text_input("Company website (e.g. ramp.com, cloudflare.com, miro.com)")
if q:
    cfg = load.load_config()
    enr, nws = akta.get("enrichment", q), akta.get("news", q)
    if enr.get("unresolved") and nws.get("unresolved"):
        st.write("Not in today's cache; live lookups run from the demo laptop (AKTA_OFFLINE=0 with a live budget).")
    else:
        fg = (enr.get("response") or {}).get("firmographic") or {}
        evs = rules.events_for(nws.get("response"), q.split(".")[0].title(), cfg, run_date)
        top = rules.most_severe(evs)
        st.write(f"Headcount range {fg.get('headcount_range') or 'unverified'} · mode {nws['mode']}")
        for e in evs:
            st.markdown(E(f"{e['date']} · {e['title']} → {e['class']}"))
        st.write(f"Most severe in window: {top['class'] if top else 'none'} (weight {cfg['policy'].get(top['class'] if top else 'none', 0):.2f})")

# ---------- provenance ----------
st.download_button("Download provenance (JSON)", json.dumps({"provenance": F["provenance"], "meta": M, "claims": F["claims"]}, indent=1, default=str),
                   file_name="provenance.json")
st.caption(f"Ledger as of {M['as_of']} · news anchored to {M['run_date']} · extraction source: {M['extraction_source']} · "
           f"PRISM spans: {', '.join(M['prism_spans'][:3])}…")
