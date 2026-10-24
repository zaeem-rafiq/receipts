"""Receipts: the logo slide of a seed deck, checked against the ledger and the world. Prototype."""
import json
from datetime import date

import streamlit as st
import streamlit.components.v1 as components

from integrations import env  # noqa: F401  (.env or the Secrets box -> os.environ, before the clients read it)
from akta import client as akta
from akta import rules
from engine import findings, load
from integrations import nicrron, prism, roundtable
from llm import summarize

st.set_page_config(page_title="Receipts", layout="wide")

# Visual layer from the design team's mockups: serif headings, mono labels, receipt-paper cards. Styling only.
st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Instrument+Serif&family=IBM+Plex+Mono:wght@400;600&display=swap');
h1, h2, h3 {font-family: 'Instrument Serif', Georgia, serif !important; font-weight: 400 !important; letter-spacing: -0.01em;}
.rc-wordmark {font-family: 'Instrument Serif', Georgia, serif; font-size: 3rem; line-height: 1.1; margin: 0;}
.rc-wordmark span {color: #B8361E;}
[data-testid="stMetric"] {background: #FFFDF8; border: 1px solid #D9D2C3; border-radius: 4px; padding: 14px 16px;}
[data-testid="stMetricLabel"] p {font-family: 'IBM Plex Mono', monospace; text-transform: uppercase; letter-spacing: 0.04em; font-size: 0.7rem; white-space: normal;}
[data-testid="stMetricLabel"] div {overflow: visible; white-space: normal;}
[data-testid="stMetricValue"] {font-family: 'Instrument Serif', Georgia, serif; font-variant-numeric: tabular-nums;}
[data-testid="stColumn"]:nth-child(3) [data-testid="stMetric"] {background: #F6E1DA; border-color: #E3B3A6;}
[data-testid="stColumn"]:nth-child(3) [data-testid="stMetricValue"] {color: #B8361E;}
.rc-card {background: #FFFDF8; border: 1px solid #D9D2C3; border-top: 4px solid var(--rc); border-radius: 2px; padding: 8px 10px; min-height: 170px;}
.rc-card b {font-size: 0.95rem;}
.rc-stamp {display: inline-block; font-family: 'IBM Plex Mono', monospace; font-size: 0.68rem; font-weight: 600; letter-spacing: 0.06em;
           color: var(--rc); border: 1px solid var(--rc); padding: 0 5px; margin: 3px 0; border-radius: 2px;}
.rc-card small {font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem; color: #555;}
.rc-card hr {border: none; border-top: 1px dashed #CFC6B3; margin: 4px 0;}
</style>""", unsafe_allow_html=True)

COLORS = {"green": "#1f9d55", "green_plus": "#1f9d55", "amber": "#d97706", "amber_pilot": "#b7791f", "grey": "#718096",
          "grey_unverified": "#718096", "red": "#c53030"}
LABEL = {"green": "VERIFIED", "green_plus": "VERIFIED +", "amber": "AT RISK", "amber_pilot": "PILOT", "grey": "",
         "grey_unverified": "WORLD CHECK N/A", "red": "NOT IN LEDGER"}


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
    F["meta"]["prism_exported"] = run.save()  # True only when PRISM accepted the trajectory
    F["meta"]["prism_llm_calls"] = len(run.llm_calls)
    F["meta"]["prism_accepted"] = run.accepted
    F["meta"]["prism_export_error"] = run.export_error
    return F


def E(s):
    """Escape $ so Streamlit markdown does not render dollar amounts as LaTeX."""
    return str(s).replace("$", "\\$")


def usd(n):
    return E(findings.usd(n))


def badge(name, state, ok, tip=""):
    color = "#1f9d55" if ok else "#a0aec0"
    return (f"<span title='{tip}' style='display:inline-block;background:{color};color:white;padding:2px 8px;border-radius:10px;"
            f"margin:0 6px 4px 0;font-size:0.8rem'>{name} {state}</span> ")


def cash(n):
    """Dollar amount for raw HTML blocks (no markdown escape, no LaTeX)."""
    return findings.usd(n).replace("$", "&#36;")


def plain(cls):
    return cls.replace("_", " ")


VERDICT_WHY = {
    "VERIFIED": "Billed customer in the ledger and no weighted risk news in the window.",
    "AT_RISK": "Billed customer in the ledger, but the news window has a risk event (listed first under World).",
    "PILOT_OR_CHURNED": "The ledger shows a pilot that was canceled; it is not a paying customer today.",
    "ONE_TIME": "The ledger shows only a one-time charge, not recurring revenue.",
    "NOT_IN_LEDGER": "No charges for this name in the customer revenue export.",
    "UNVERIFIED": "Billed customer in the ledger, but the outside-world (Akta news) check did not run, so it is not marked verified.",
}


# ---------- header ----------
st.markdown("<h1 class='rc-wordmark'>Receipts<span>.</span></h1>", unsafe_allow_html=True)
st.caption("Twelve logos on a seed deck, each checked against the customer revenue export and against the outside world (Akta).")
st.warning("Fictional startup (Bramblefin); customer names are real public companies used for demonstration; the commercial relationships "
           "and the ledger are invented. **Akta data:** the badge below says where it came from: CACHED = real Akta API responses saved "
           "earlier and replayed; LIVE = fetched now; MOCK = hand-written test data, not Akta output.")
with st.container(border=True):
    st.markdown("**Start here (about one minute)**  \n"
                "1. Read the four numbers: what the deck claims versus what the revenue ledger supports.  \n"
                "2. In the **Logo wall**, click **Receipt** under any logo. The page jumps to that logo's evidence and its verdict.  \n"
                "3. Try any company yourself in [Check any company](#check-any-company) (type a website, press Enter).")
    with st.expander("What the words mean"):
        st.markdown(
            "- **ARR** (annual recurring revenue) = monthly recurring revenue × 12. **MRR** = monthly recurring revenue.  \n"
            "- **Deck ARR**: the number on the startup's pitch slide. **Recurring ARR**: what the subscription ledger supports.  \n"
            "- **ARR flagged (policy-weighted)**: recurring revenue from customers with risk news, multiplied by a fixed weight per "
            "event type (for example layoffs or an acquisition). A screening signal, not a valuation; never subtracted from ARR.  \n"
            "- **Exposure (unweighted)**: the same customers' revenue with no weight applied.  \n"
            "- **Receipt**: the evidence for one logo: its ledger rows, its company profile and its news.  \n"
            "- **Tie-out**: how the deck's number can be rebuilt from the ledger.  \n"
            "- **Second-meeting question**: a question an investor could ask the founder next.  \n"
            "- **Policy weight**: the fixed share of a customer's revenue flagged for each event type (shutdown 1.00, acquisition or "
            "major layoffs 0.50, minor layoffs 0.25; funding, product launch and **acquirer** 0.00).  \n"
            "- **Acquisition** = the customer is being bought (a risk). **Acquirer** = the customer is buying another company "
            "(buyer side, not a risk).  \n"
            "- **Akta**: company data and news API. **Nicrron**: AI model gateway that writes the summary. **PRISM**: run tracing. "
            "**Roundtable**: file hand-off between steps. A grey badge means that tool was not used on this host.")

with st.sidebar:
    st.header("Run")
    run_date = st.date_input("Run date (news is checked for the 180 days before this date)", value=date.today())
    akta_on = st.toggle("Use Akta news", value=True, help="Off = ignore all news for every logo; shows how much the verdicts depend on Akta.")
    st.caption(f"Live Akta lookups: {'off on this host (cached data only)' if akta.offline() else 'on'} · "
               f"live calls left: {akta.budget_left()}")

F = compute(run_date.isoformat(), akta_on)
H, D, M = F["headline"], {k: E(v) for k, v in F["display"].items()}, F["meta"]

# Badges report what this run actually did, never what a key would allow.
summary_via_model = F["summary"]["source"].startswith("Nicrron")
extraction_via_model = M["extraction_source"] == "llm"
nicrron_state = (f"{nicrron.MODEL} (summary{' + extraction' if extraction_via_model else ''})" if summary_via_model
                 else (f"{nicrron.MODEL} (extraction only; summary: template)" if extraction_via_model
                       else ("template (model call failed or blocked)" if nicrron.enabled() else "OFF")))
st.markdown(
    badge("Akta", M["akta_mode"], M["akta_mode"] in ("CACHED", "LIVE"), "Company data and news")
    + badge("Nicrron", nicrron_state, summary_via_model or extraction_via_model, "AI model gateway that writes the summary")
    + badge("PRISM", f"session {M['prism_trace_id']}"
            + ("" if M.get("prism_exported") else (" (export failed)" if prism.enabled() else " (local only)")), bool(M.get("prism_exported")), "Run tracing")
    + badge("Roundtable", f"claims v{M['roundtable_claims_version']} / findings v{M['roundtable_findings_version']}"
            + ("" if roundtable.enabled() else f" ({roundtable.status()})"), roundtable.enabled(), "File hand-off between steps"),
    unsafe_allow_html=True)
st.caption("Badges show what this run actually used. Green = used; grey = not used on this host (the numbers do not depend on it).")

# ---------- strip ----------
c1, c2, c3, c4 = st.columns(4)
c1.metric("Deck ARR (slide 4)", F["display"]["deck_arr"])
c2.metric("Recurring ARR (ledger)", F["display"]["recurring_arr"])
c3.metric("ARR flagged (policy-weighted)", F["display"]["arr_at_risk"], help="Screening weights, not a valuation. Never subtracted into ARR or used in a multiple.")
c4.metric("Top customer share of MRR", F["display"]["top1_share"])
st.caption(f"Exposure (unweighted): {D['arr_exposed']} of recurring ARR sits with {D['exposed_customers']} customers that had a risk event "
           f"({D['exposure_pct']}). Valuation asked: {D['multiple_deck']} deck ARR vs {D['multiple_recurring']} recurring ARR.")

# ---------- summary ----------
with st.container(border=True):
    st.markdown("**Summary**  \n" + E(F["summary"]["text"]).replace("\n", "  \n"))
    st.caption(f"Source: {F['summary']['source']}. Number check: every number in this text must match a number the deterministic engine computed"
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
st.caption("Click **Receipt** under a logo to see its evidence. Green = verified paying customer (+ = recent funding news) · "
           "amber = at risk or pilot only · grey = one-time or world check not available · red = not in the ledger.")
if "sel" not in st.session_state:
    st.session_state.sel = "logo_01"
cols = st.columns(6)
for i, l in enumerate(F["logos"]):
    with cols[i % 6]:
        color = COLORS[l["card"]]
        sub = {"ACTIVE": f"{cash(l['mrr_now'])}/month · {l['tenure_months']} months", "PILOT": f"pilot, {l['tenure_months']} months, canceled",
               "ONE_TIME": f"one-time {cash(l['lifetime_revenue'])}", "NOT_IN_LEDGER": "no charges"}[l["status"]]
        ev = f"news: {plain(l['event_class'])}" if l["event_class"] != "none" else ""
        st.markdown(f"<div class='rc-card' style='--rc:{color}'>"
                    f"<b>{l['name']}</b><br><span class='rc-stamp'>{LABEL[l['card']] or l['status'].replace('_', ' ')}</span><hr>"
                    f"<small>{sub}</small><br><small>{ev}</small></div>", unsafe_allow_html=True)
        if st.button("Receipt", key=f"b_{l['slot']}", width="stretch"):
            st.session_state.sel = l["slot"]
            st.session_state.jump = True

# ---------- receipt ----------
l = next(x for x in F["logos"] if x["slot"] == st.session_state.sel)
st.subheader(f"Receipt: {l['name']}  ·  {LABEL[l['card']] or l['verdict'].replace('_', ' ')}", anchor="receipt")
st.markdown(f"**Why:** {VERDICT_WHY.get(l['verdict'], '')}")
if st.session_state.pop("jump", False):
    st.toast(f"Showing the receipt for {l['name']}")
    components.html("<script>try{window.parent.document.getElementById('receipt').scrollIntoView({behavior:'smooth'})}catch(e){}</script>", height=0)
a, b, c = st.columns(3)
with a:
    st.markdown("**Ledger**")
    if l["customer_id"]:
        st.write(f"Customer `{l['customer_id']}` (match: {l['match_tier']}, billed as “{l['nearest_name']}”)")
        st.markdown(f"Status {l['status']} · MRR {usd(l['mrr_now'])} · tenure {l['tenure_months'] or 'n/a'} months · "
                 f"lifetime {usd(l['lifetime_revenue'])} · {len(l['charge_ids'])} charge rows")
        charges, _, _ = load.load_ledger()
        rows = charges[charges["charge_id"].isin(l["charge_ids"])][["created", "amount", "subkind", "charge_id", "description"]].copy()
        rows["created"] = rows["created"].astype(str).str[:10]
        st.dataframe(rows, hide_index=True, width="stretch", height=220)
    else:
        st.write(f"Not in the ledger. Nearest ledger name: {l['nearest_name']} (ratio {l['nearest_ratio']}).")
with b:
    st.markdown("**Profile (Akta Company Data)**")
    ak = l["akta"]
    st.write(f"Domain {ak['domain'] or 'n/a'} · headcount range {ak.get('headcount_range') or 'unverified'} · segment {ak.get('segment')}")
    st.write(f"Operating status: {ak.get('operating_status') or 'unverified'}")
    st.caption(f"Mode: {ak['mode']}" + (f" · fetched {ak.get('fetched_at')}" if ak.get("fetched_at") else "")
               + (f" · last live error: {ak['live_error']}" if ak.get("live_error") else ""))
with c:
    st.markdown(f"**World (Akta News, 180 days) · {ak['mode']}**")
    if ak.get("news_status") == "unavailable":
        st.write("World check unavailable: no cached, live or mock Akta news for this domain, so this card is not marked verified.")
    elif not ak["events"]:
        st.write("No articles in window.")

    def news_line(e):
        st.markdown(E(f"{e['date']} · {e['publisher']}: {e['title']}"))
        st.caption(f"code {e['code'] or 'none'} → {plain(e['class'])} ({e['trigger']}{', matched by keyword' if e['keyword_classified'] else ''})"
                   f"{'' if e['in_window'] else ' · outside window'}"
                   f"{'' if e.get('primary', True) else (' · ignored: news digest covering several companies' if e.get('digest') else ' · ignored: not about this company')}")

    pol = load.load_config()["policy"]

    def counts(e):
        return e["in_window"] and e.get("primary", True) and (pol.get(e["class"], 0) > 0 or e["class"] == "funding")

    weighted = [e for e in ak["events"] if counts(e)]
    other = [e for e in ak["events"] if not counts(e)]
    if weighted:
        st.markdown("Articles that can change the verdict (risk weight above zero, or funding):")
    for e in weighted:
        news_line(e)
    if other:
        with st.expander(f"{len(other)} other articles (no effect on the verdict)"):
            for e in other:
                news_line(e)
    st.write(f"Policy weight **{l['weight']:.2f}** (fixed weight for this event type) → monthly revenue flagged **{usd(l['mrr_at_risk'])}**")
st.info(E(f"Second-meeting question: {l['question']}"))

# ---------- enterprise check ----------
st.subheader("Enterprise check")
st.write(f"**{D['enterprise']}** logos over 1,000 employees (deck claim: {D['deck_enterprise_claim']} enterprise customers).")
st.dataframe([{"logo": x["name"], "headcount_range": x["akta"].get("headcount_range"), "segment": x["akta"].get("segment")} for x in F["logos"]],
             hide_index=True, width="stretch")

# ---------- live panel ----------
st.subheader("Check any company", anchor="check-any-company")
q = st.text_input("Company website or name (e.g. ramp.com, Cloudflare, miro.com), then press Enter")


def known_domains():
    """Bare names a judge may type -> website: the deck logos plus the pre-warmed live-panel list."""
    table = {l["name"].lower(): l["akta"]["domain"] for l in F["logos"] if l["akta"].get("domain")}
    try:
        from scripts.warm import EXTRA
        for d in EXTRA:
            table.setdefault(d.split(".")[0], d)
    except Exception:
        pass
    return table


if q:
    cfg = load.load_config()
    raw = q.strip()
    dom = None
    try:
        dom = akta.domain_of(raw) if "." in raw else known_domains().get(raw.lower())
    except ValueError:
        dom = None
    if not dom:
        st.error("Enter a website like ramp.com, or one of the pre-warmed names (Ramp, Cloudflare, Miro, Rippling, Notion, Vanta, HubSpot, Airtable, PostHog, Wix).")
    else:
        try:
            enr, nws = akta.get("enrichment", dom), akta.get("news", dom)
        except Exception as e:  # the client degrades on its own; this is the last net
            enr, nws = {"unresolved": True, "mode": "MISS", "response": {}}, {"unresolved": True, "mode": "MISS", "response": {}}
            st.error(f"Lookup failed: {type(e).__name__}")
        if enr.get("unresolved") and nws.get("unresolved"):
            err = akta.ERRORS.get(("news", dom)) or akta.ERRORS.get(("enrichment", dom))
            if err:
                why = f"live lookup failed ({err})"
            elif akta.offline():
                why = "live lookups are off on this host, so only pre-warmed companies work here"
            elif akta.budget_left() <= 0:
                why = "this session's live budget is spent (AKTA_LIVE_BUDGET)"
            else:
                why = "no Akta key on this host"
            st.write(f"{dom}: not in today's cache; {why}. Try one of the pre-warmed names.")
        else:
            body = enr.get("response") or {}
            body = body["data"] if isinstance(body.get("data"), dict) else body
            fg = body.get("firmographic") or {}
            name = next((l["name"] for l in F["logos"] if l["akta"].get("domain") == dom), dom.split(".")[0].title())
            evs = rules.events_for(nws.get("response"), name, cfg, run_date, domain=dom)
            top = rules.most_severe(evs)
            st.markdown(f"**Result for {dom}:** most severe event in the last 180 days: "
                        f"**{plain(top['class']) if top else 'none'}** (weight {cfg['policy'].get(top['class'] if top else 'none', 0):.2f})")
            st.write(f"{dom} · headcount range {fg.get('headcount_range') or 'unverified'} · data: {nws['mode']}"
                     + (" (hand-written fixture, not Akta output)" if nws["mode"] == "MOCK" else ""))
            hit = [e for e in evs if e["in_window"] and cfg["policy"].get(e["class"], 0) > 0]
            for e in hit:
                st.markdown(E(f"{e['date']} · {e['title']} → {plain(e['class'])} ({e['trigger']})"))
            rest = [e for e in evs if e not in hit]
            if rest:
                with st.expander(f"{len(rest)} other articles (no risk weight)"):
                    for e in rest:
                        st.markdown(E(f"{e['date']} · {e['title']} → {plain(e['class'])}"))

# ---------- provenance ----------
st.download_button("Download provenance (JSON)",
                   json.dumps({"headline": H, "display": F["display"], "provenance": F["provenance"], "ledger": F["ledger"], "meta": M, "claims": F["claims"]},
                              indent=1, default=str), file_name="provenance.json")
st.caption(f"Ledger as of {M['as_of']} · news anchored to {M['run_date']} · extraction source: {M['extraction_source']} · "
           f"PRISM spans: {', '.join(M['prism_spans'][:3])}…. The JSON lists the ledger row ids (data_room/stripe_charges.csv) "
           "and Akta article ids behind every number.")
