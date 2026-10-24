# Receipts: notes for coding agents

Hackathon repo (Deal Flow, Track 2 Diligence). Rules that hold for every change: synthetic or public data only; keys come from
the environment, a git-ignored `.env` or the Streamlit Secrets box, never from chat or a commit; money math is deterministic
(no model touches a number); every number traces to a source row, file or API response; anything not verified is marked
UNVERIFIED. Run `python -m pytest -q tests` before pushing.

## PRISM tracing (do not remove)

This project sends traces to PRISM. Env vars: `PRISMTRACE_API_KEY`,
`PRISMTRACE_PROJECT_ID`, `PRISMTRACE_HOST`.

Tracing is currently wired at: `integrations/prism.py` (session per run, trajectory, end_session, HTTP fallback),
`integrations/nicrron.py` (every completion -> `prism.record_llm` -> `trace_llm`), `llm/summarize.py` and
`scripts/prism_challenge.py` (pass the run so calls land in its session), `streamlit_app.py` (`compute()` opens the run,
`run.save()` submits it; the PRISM badge is green only when the trajectory was accepted), `llm/extract.py` (build-time
extraction, traced without a session).

**Standing rule.** Whenever you add or change an agent, chain, graph, tool,
retriever, or any entry point that calls a model, wire it to PRISM before you
finish. Unwired code is invisible in the dashboard. If you are unsure whether
something is covered, assume it is not and wire it.
