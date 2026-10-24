# Receipts prototype (throwaway, Oct 24 2026)

Built in a sandbox from phase-b/docs/PLAN.md, the data room and tests/oracle.json. Not a repo; nothing here was pushed or deployed.

## Run
    python -m venv .venv && . .venv/bin/activate
    pip install -r requirements.txt
    python llm/extract.py            # writes data_room/claims.json (fallback without NICRRON_API_KEY)
    python -m pytest -q tests        # 110 checks
    streamlit run streamlit_app.py

## What is real and what is mocked
- Engine (engine/, akta/rules.py): deterministic pandas, all oracle ledger values pass. No LLM touches a number.
- Akta: client follows PLAN.md section 6 (cache -> live within AKTA_LIVE_BUDGET when AKTA_OFFLINE=0 -> MOCK -> unresolved).
  demo_cache/akta/mock/ is HAND-WRITTEN from oracle.json event notes, not Akta output; the badge says MOCK.
  Drop real warm-up files into demo_cache/akta/{enrichment,news}/<domain>.json and they win. Live path UNTESTED (no key in sandbox).
- Nicrron: OpenAI client at https://api.nicrron.ai/v1, model anthropic/claude-haiku-5-5. Without NICRRON_API_KEY the summary
  is a deterministic template. Digit guardrail blocks any model number not in findings['display']. Live path UNTESTED.
- PRISM: one local trace per run (demo_cache/traces/); OTLP export when PRISMTRACE_API_KEY is set (needs opentelemetry-sdk and
  opentelemetry-exporter-otlp-proto-http). Export UNTESTED.
- Roundtable: local versioned stub (demo_cache/roundtable/) with put_file/get_file/post_message; real SDK UNVERIFIED.
