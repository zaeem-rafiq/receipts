"""Five lines of prose from findings['display'] via Nicrron. Digit guardrail: every number in the output must appear verbatim
in the display strings. If the model is off or the guardrail fails, a deterministic template is used instead."""
import json
import re

from integrations import nicrron

NUM = re.compile(r"\$?\d[\d,]*(?:\.\d+)?%?x?")


def allowed_tokens(display):
    toks = set()
    for v in display.values():
        for m in NUM.findall(str(v)):
            toks.add(m)
            toks.add(m.lstrip("$"))
    return toks


MIN_CHARS = 40  # a five-line summary is far longer; anything shorter is an empty or truncated reply
TRUNCATED = "<empty or truncated output>"


def is_truncated(text):
    """An empty or cut-off reply cannot be shown, and letting it "pass" the digit rule would make the rule look trivial."""
    return len((text or "").strip()) < MIN_CHARS


def guardrail(text, display):
    """Return list of numeric tokens in text that the engine did not print. Empty list = pass."""
    ok = allowed_tokens(display)
    bad = []
    for m in NUM.findall(text):
        core = m.rstrip(".,")
        if core not in ok and core.lstrip("$") not in ok:
            bad.append(core)
    return bad


def template(d):
    return "\n".join([
        f"The deck claims {d['deck_arr']} ARR; the ledger supports {d['recurring_arr']} of recurring ARR.",
        "The deck figure reproduces only as 12 times all September charges, including implementation and one-time fees.",
        f"ARR flagged (policy-weighted) is {d['arr_at_risk']} ({d['arr_at_risk_pct']}); unweighted exposure is {d['arr_exposed']} ({d['exposure_pct']}).",
        f"Enterprise check: {d['enterprise']} logos over 1,000 employees against a deck claim of {d['deck_enterprise_claim']}.",
        f"Top customer is {d['top1_share']} of MRR; the top five are {d['top5_share']}.",
    ])


PROMPT = ("You write a five-line diligence summary for a VC partner. Use ONLY the values in the JSON below, copied exactly; "
          "do not compute, round, or introduce any number that is not already a value in the JSON (the labels are not values, so "
          "write 'the largest customer' and 'the five largest customers' in words). Plain sentences, one per line.\n\n")

# Labels for the model carry no digits: a key like top5_share once made the model write "top 5", which the digit rule blocks.
LABELS = {
    "deck_arr": "deck ARR claim", "recurring_arr": "recurring ARR per the ledger", "recurring_mrr": "recurring MRR per the ledger",
    "arr_at_risk": "ARR flagged (policy-weighted)", "arr_at_risk_pct": "ARR flagged as a share of recurring ARR",
    "arr_exposed": "ARR exposed (unweighted)", "exposure_pct": "ARR exposed as a share of recurring ARR",
    "exposed_customers": "customers with a risk event", "top1_share": "largest customer's share of MRR",
    "top5_share": "five largest customers' share of MRR", "enterprise": "enterprise logos verified by headcount, of the deck's logos",
    "deck_enterprise_claim": "deck's enterprise logo claim", "customers_ever_billed": "customers ever billed",
    "active_customers": "active customers", "logo_verified_arr": "logo-verified recurring ARR",
    "multiple_deck": "ask multiple on deck ARR", "multiple_recurring": "ask multiple on recurring ARR", "post_money": "post-money valuation",
}


def prompt_input(display):
    """The display strings under digit-free labels, which is what the model is shown."""
    return {LABELS.get(k, k.replace("_", " ")): v for k, v in display.items()}


def summarize(display, run=None):
    """Returns dict(text, source, guardrail_failures)."""
    if not nicrron.enabled():
        return {"text": template(display), "source": "template (Nicrron off)", "guardrail_failures": []}
    try:
        cm = run.span("summarize", provider="nicrron", model=nicrron.MODEL) if run else None
        rec = cm.__enter__() if cm else {"attrs": {}}
        text, meta = nicrron.chat([{"role": "user", "content": PROMPT + json.dumps(prompt_input(display))}], run=run, purpose="summary")
        bad = [TRUNCATED] if is_truncated(text) else guardrail(text, display)
        rec["attrs"].update({"input": json.dumps(prompt_input(display)), "output": text, "guardrail.digit_rule": "fail" if bad else "pass",
                             "finish_reason": meta.get("finish_reason"), "chars_out": len(text)})
        if cm:
            cm.__exit__(None, None, None)
        if bad == [TRUNCATED]:
            return {"text": template(display), "source": f"template (model returned {len(text or '')} chars; finish_reason {meta.get('finish_reason')})",
                    "guardrail_failures": bad}
        if bad:
            return {"text": template(display), "source": "template (guardrail blocked model output)", "guardrail_failures": bad}
        return {"text": text, "source": f"Nicrron {nicrron.MODEL}", "guardrail_failures": []}
    except Exception as e:
        return {"text": template(display), "source": f"template (Nicrron error: {type(e).__name__})", "guardrail_failures": []}
