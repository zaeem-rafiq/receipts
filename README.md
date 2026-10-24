# Receipts

**Every logo on slide 5 gets a receipt.** Drop in a seed deck and the startup's Stripe export; Receipts matches each customer logo to the ledger, says what that customer actually paid (active subscription, churned pilot, one-time implementation fee, or never in the ledger), and then asks the Akta API what has happened to that customer since: layoffs, an acquisition, a shutdown. Three numbers on top, each one tied to its rows:

| Deck ARR | Recurring ARR | ARR flagged (policy-weighted) |
|---|---|---|
| what slide 4 claims | what the ledger supports today | recurring ARR sitting with customers Akta shows in trouble, weighted by the policy in `data_room/config.yaml` |

Built at Deal Flow, NYC's first VC hackathon (Betaworks, Oct 24 2026), Track 2: Diligence. Sponsor award entered: Wokelo "Best Use of External Data" (Akta API).

## Fiction disclosure

The startup in the data room, **Bramblefin**, is fictional and its ledger is synthetic. The customer names are **real public companies used for demonstration only**; the commercial relationships, amounts and dates are invented. The outside-in signals shown for those companies come from the Akta API (public news and firmographics) or, when no key is present, from clearly labelled MOCK fixtures.

## Run it

```
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # fill in keys locally; .env is git-ignored
python llm/extract.py           # writes data_room/claims.json (fallback claims without NICRRON_API_KEY)
python -m pytest -q tests       # 110 checks against tests/oracle.json
streamlit run streamlit_app.py
```

Keys are read from the environment, a git-ignored `.env` in the repo root (`cp .env.example .env`), or the Streamlit Secrets box: `AKTA_API_KEY`, `NICRRON_API_KEY`, `PRISMTRACE_API_KEY` (plus `PRISMTRACE_PROJECT_ID` and `PRISMTRACE_HOST`, which default to the Receipts project and PRISM's API host). Missing keys never crash the app; the matching badge reads OFF or MOCK. `AKTA_OFFLINE=1` (the default, and the public host's setting) serves Akta data from `demo_cache/akta/` only; `AKTA_OFFLINE=0 AKTA_LIVE_BUDGET=10` on a laptop allows ten live lookups. `python scripts/warm.py` fills the cache for the 12 logo slots and the pre-warmed live-panel names.

## What is real and what is not

- **Engine** (`engine/`, `akta/rules.py`): deterministic pandas. No language model touches a number. Every value in `findings.json` carries its provenance (charge ids, subscription ids, customer ids, or the Akta record it came from) and the provenance file downloads from the app.
- **Akta**: `akta/client.py` reads `demo_cache/akta/{enrichment,news}/<domain>.json` first, then calls live within the budget, then falls back to `demo_cache/akta/mock/`, which is hand-written from public news and is **not** Akta output. Each card shows LIVE, CACHED or MOCK.
- **Nicrron**: the only model route (`integrations/nicrron.py`, OpenAI-compatible gateway, `anthropic/claude-haiku-5-5`), used for deck claim extraction at build time and for the summary prose. The summary is checked digit-for-digit against the engine's display strings; any number the engine did not print is rejected and a templated summary is shown instead.
- **PRISM by Block Convey**: one PRISM session per run through the `prismtrace` SDK (`integrations/prism.py`): every Nicrron completion is a trace with model, messages, output, latency and token counts; the run's engine, Akta and summary spans are submitted as one trajectory and the session is closed. The header badge is green only when PRISM accepted the trajectory, grey with "export failed" or "local only" otherwise; the local copy is always under `demo_cache/traces/`. The digit rule above is asserted locally on every summary and is the guardrail registered in PRISM; `scripts/prism_challenge.py` runs summarizer v1 and v2 on the same inputs so the rule's effect is visible (`--selftest` needs no key).
- **Roundtable**: the hand-off between extraction and engine (`claims.json` in, `findings.json` out) goes through `integrations/roundtable.py`. Until the SDK is confirmed this is a local versioned stub and the badge says so.

## Layout

```
data_room/     deck.md, stripe_charges.csv, stripe_subscriptions.csv, customers.csv, logos_fallback.json, config.yaml
engine/        load.py, match.py, metrics.py, findings.py
akta/          client.py (cache / live / mock), rules.py (event classification and policy weights)
llm/           extract.py (deck claims), summarize.py (prose with the digit guardrail)
integrations/  nicrron.py, prism.py, roundtable.py
tests/         oracle.json (expected values), slot_map.json, test_oracle.py, test_rules.py
scripts/       warm.py (Akta cache fill)
streamlit_app.py
```

## Credits

The idea, the product direction and the diligence rules are Zaeem Rafiq's. The team worked in lanes (engine, Akta, UI, sponsor integrations, story); teammate names and lanes are listed below as they are confirmed. AI coding tools (Claude Code) were used for implementation during the hackathon; the data room and expected values were prepared beforehand, the code was written on build day, per the rules.

- Engine and oracle: Zaeem Rafiq
- Akta, UI, sponsor integrations, story: (teammates, to be added)
