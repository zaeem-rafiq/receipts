"""PRISM challenge: the same rule, two summarizer versions, N runs each, on the fixed data room.

Rule (registered as a PRISM guardrail and asserted locally): every digit run in the summary must appear verbatim in the
engine's display strings (findings['display']). v1 feeds the model the raw findings JSON (numbers as integers and ratios,
so the model rounds, multiplies and reformats); v2 feeds only the pre-formatted display strings. v1 fails the rule, v2
passes it, on identical inputs. Each run is one PRISM trace (the Nicrron call) plus a span with the version, the output and guardrail.digit_rule; all runs share one PRISM session.

    python scripts/prism_challenge.py --runs 20        # needs NICRRON_API_KEY; PRISMTRACE_API_KEY sends the session to PRISM
    python scripts/prism_challenge.py --selftest        # no model: shows the rule on two canned outputs (labelled canned)
"""
import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine import findings  # noqa: E402
from integrations import nicrron, prism  # noqa: E402
from llm import summarize  # noqa: E402

V1_PROMPT = ("You write a five-line diligence summary for a VC partner from the findings JSON below. Give ARR figures in "
             "millions with one decimal, percentages rounded to whole numbers, and compute the share of ARR at risk yourself. "
             "Plain sentences, one per line.\n\n")

CANNED = {
    "v1": "The deck claims $1.2M ARR while the ledger supports $0.84M; about 13% of recurring ARR is flagged.",
    "v2": "The deck claims $1,200,000 ARR; the ledger supports $840,000 of recurring ARR. ARR flagged (policy-weighted) is $111,600 (13.3%).",
}


def v1_input(F):
    h = F["headline"]
    return {k: h[k] for k in ("deck_arr", "recurring_arr", "arr_at_risk", "arr_at_risk_share", "arr_exposed", "exposure_share",
                              "top1_share", "top5_share", "enterprise_count", "deck_enterprise_claim")}


def one_run(version, F, run):
    display = F["display"]
    if version == "v1":
        prompt = V1_PROMPT + json.dumps(v1_input(F))
    else:
        prompt = summarize.PROMPT + json.dumps(display)
    with run.span(f"summarize.{version}", version=version, provider="nicrron", model=nicrron.MODEL) as rec:
        text, _ = nicrron.chat([{"role": "user", "content": prompt}], run=run, purpose=f"challenge.{version}")
        bad = summarize.guardrail(text, display)
        rec["attrs"].update({"input": prompt[-2000:], "output": text, "guardrail.digit_rule": "fail" if bad else "pass",
                             "guardrail.blocked_tokens": json.dumps(bad)})
    return text, bad


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--selftest", action="store_true", help="no model call: apply the rule to two canned outputs")
    a = ap.parse_args(argv)
    F = findings.run(run_date=date.today())
    display = F["display"]
    if a.selftest:
        for v, text in CANNED.items():
            bad = summarize.guardrail(text, display)
            print(f"[canned {v}] {'FAIL' if bad else 'PASS'} blocked={bad}\n    {text}")
        print("(canned strings, not model output; run without --selftest and with NICRRON_API_KEY for the real challenge)")
        return 0
    if not nicrron.enabled():
        print("NICRRON_API_KEY is not set; nothing ran. Export it in this shell (never paste it in chat).")
        return 2
    run = prism.Run(kind="prism-challenge")
    tally = {"v1": {"pass": 0, "fail": 0}, "v2": {"pass": 0, "fail": 0}}
    samples = {"v1": [], "v2": []}
    for i in range(a.runs):
        for v in ("v1", "v2"):
            try:
                text, bad = one_run(v, F, run)
            except Exception as e:
                print(f"run {i + 1} {v}: model error {type(e).__name__}")
                continue
            tally[v]["fail" if bad else "pass"] += 1
            if len(samples[v]) < 2:
                samples[v].append((text.replace("\n", " ")[:160], bad))
            print(f"run {i + 1:2d} {v}: {'FAIL' if bad else 'pass'} {bad if bad else ''}")
    run.save()
    print("\ntally:", json.dumps(tally))
    for v in ("v1", "v2"):
        for text, bad in samples[v]:
            print(f"  sample {v}: blocked={bad} :: {text}")
    status = ("accepted by PRISM: " + ", ".join(f"{k} {v}" for k, v in run.accepted.items()) if run.exported
              else ("export failed: " + str(run.export_error) if prism.enabled() else "local only: set PRISMTRACE_API_KEY to export"))
    print(f"PRISM session {run.session_id} ({status}); local copy demo_cache/traces/{run.session_id}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
