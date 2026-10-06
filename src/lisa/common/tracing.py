"""OpenTelemetry tracing for model calls, tool calls and verifier decisions.

OTEL_EXPORTER_OTLP_ENDPOINT set (e.g. http://localhost:4318, Jaeger all-in-one) -> OTLP/HTTP export.
Always also written to out/traces/<service>.jsonl so traces can be inspected without a backend.
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter, SpanExportResult

_configured = False


class JsonlExporter(SpanExporter):
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def export(self, spans) -> SpanExportResult:
        with open(self.path, "a", encoding="utf-8") as f:
            for s in spans:
                f.write(json.dumps({
                    "name": s.name, "trace_id": f"{s.context.trace_id:032x}", "span_id": f"{s.context.span_id:016x}",
                    "parent_id": f"{s.parent.span_id:016x}" if s.parent else None,
                    "start_ns": s.start_time, "duration_ms": round((s.end_time - s.start_time) / 1e6, 2),
                    "status": s.status.status_code.name, "attributes": dict(s.attributes or {}),
                    "service": s.resource.attributes.get("service.name")}, default=str) + "\n")
        return SpanExportResult.SUCCESS


def setup_tracing(service: str, out_dir: Path | None = None) -> trace.Tracer:
    global _configured
    if not _configured:
        provider = TracerProvider(resource=Resource.create({"service.name": service}))
        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        if endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces")))
        if out_dir is not None:
            provider.add_span_processor(SimpleSpanProcessor(JsonlExporter(Path(out_dir) / "traces" / f"{service}.jsonl")))
        trace.set_tracer_provider(provider)
        _configured = True
    return trace.get_tracer(service)


@contextmanager
def span(name: str, **attrs):
    """Start a span with flat attributes (non-scalars JSON-encoded, strings truncated)."""
    tracer = trace.get_tracer("lisa")
    with tracer.start_as_current_span(name) as sp:
        for k, v in attrs.items():
            if v is None:
                continue
            if not isinstance(v, (str, int, float, bool)):
                v = json.dumps(v, default=str)
            sp.set_attribute(k, v[:2000] if isinstance(v, str) else v)
        yield sp
