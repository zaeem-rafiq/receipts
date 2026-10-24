"""One trace per run. Spans are always recorded locally (trace id shown in the UI); with PRISMTRACE_API_KEY set they are
also exported over OTLP http/protobuf to PRISM. The export path follows PLAN.md env names and is UNTESTED from the sandbox."""
import contextlib
import json
import os
import time
import uuid
from pathlib import Path

from integrations import env  # noqa: F401

LOG = Path(__file__).resolve().parent.parent / "demo_cache" / "traces"
_tracer = None


def enabled():
    """A key is configured. Whether spans actually leave the process is exporting()."""
    return bool(os.environ.get("PRISMTRACE_API_KEY")) and os.environ.get("PRISM_ENABLED", "1") != "0"


def exporting():
    """True only when the OTel exporter is up; the badge is green only on this."""
    return bool(_otel())


def _otel():
    global _tracer
    if _tracer is not None or not enabled():
        return _tracer
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "https://prism.blockconvey.com/api/otlp")
        exp = OTLPSpanExporter(endpoint=endpoint, headers={"X-PRISMtrace-Key": os.environ["PRISMTRACE_API_KEY"]})
        tp = TracerProvider(resource=Resource.create({"service.name": "receipts",
                                                      "prism.project_id": os.environ.get("PRISMTRACE_PROJECT_ID", "")}))
        tp.add_span_processor(BatchSpanProcessor(exp))
        trace.set_tracer_provider(tp)
        _tracer = trace.get_tracer("receipts")
    except Exception as e:  # missing package or bad config: badge goes OFF, app keeps running
        _tracer = False
        print("PRISM export disabled:", type(e).__name__)
    return _tracer


class Run:
    """One root span 'receipts-run' per run; trace_id is the OTel trace id (what PRISM shows) when exporting, else a local id."""

    def __init__(self):
        self.spans = []
        self._root_cm, self._root = None, None
        tr = _otel()
        if tr:
            self._root_cm = tr.start_as_current_span("receipts-run")
            self._root = self._root_cm.__enter__()
            self.trace_id = format(self._root.get_span_context().trace_id, "032x")
            self.exported = True
        else:
            self.trace_id = "local-" + uuid.uuid4().hex[:12]
            self.exported = False

    @contextlib.contextmanager
    def span(self, name, **attrs):
        t0 = time.time()
        rec = {"name": name, "attrs": dict(attrs)}
        tr = _otel()
        cm = tr.start_as_current_span(name) if tr else contextlib.nullcontext()
        with cm as s:
            try:
                yield rec
            finally:
                rec["ms"] = int(1000 * (time.time() - t0))
                if s is not None:
                    for k, v in rec["attrs"].items():
                        s.set_attribute(k, v if isinstance(v, (str, int, float, bool)) else json.dumps(v)[:4000])
                self.spans.append(rec)

    def save(self):
        LOG.mkdir(parents=True, exist_ok=True)
        (LOG / f"{self.trace_id}.json").write_text(json.dumps(self.spans, indent=1, default=str))
        if self._root_cm:
            try:
                self._root_cm.__exit__(None, None, None)
                from opentelemetry import trace
                tp = trace.get_tracer_provider()
                if hasattr(tp, "force_flush"):
                    tp.force_flush(5000)
            except Exception as e:  # export trouble never breaks the run
                print("PRISM flush failed:", type(e).__name__)
