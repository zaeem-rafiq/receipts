"""One trace per run. Spans are always recorded locally (trace id shown in the UI); with PRISMTRACE_API_KEY set they are
also exported over OTLP http/protobuf to PRISM. The export path follows PLAN.md env names and is UNTESTED from the sandbox."""
import contextlib
import json
import os
import time
import uuid
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "demo_cache" / "traces"
_tracer = None


def enabled():
    return bool(os.environ.get("PRISMTRACE_API_KEY")) and os.environ.get("PRISM_ENABLED", "1") != "0"


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
    def __init__(self):
        self.trace_id = uuid.uuid4().hex[:16]
        self.spans = []

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
