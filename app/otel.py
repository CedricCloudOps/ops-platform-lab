"""OpenTelemetry setup shared by the app and the worker.

Traces are exported to Grafana Tempo over OTLP/HTTP. Set OTEL_SDK_DISABLED=true
to turn tracing off (used by the unit tests, which have no collector).
"""
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

OTLP_ENDPOINT = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://tempo:4318")
DISABLED = os.environ.get("OTEL_SDK_DISABLED", "").lower() == "true"


def setup_tracing(service_name):
    """Configure the global tracer provider and return a tracer.

    Spans are batched and shipped in the background: if Tempo is unreachable the
    exporter retries and logs, it never blocks or breaks the request path.
    """
    if DISABLED:
        return trace.get_tracer(service_name)

    provider = TracerProvider(
        resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=OTLP_ENDPOINT + "/v1/traces")))
    trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name)


def instrument_clients():
    """Auto-instrument the backend libraries (PostgreSQL, Redis, MinIO/urllib3).

    Each call the app makes to a backend then becomes a child span, so a trace
    shows exactly where an upload spent its time.
    """
    if DISABLED:
        return
    from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.instrumentation.urllib3 import URLLib3Instrumentor
    Psycopg2Instrumentor().instrument()
    RedisInstrumentor().instrument()
    URLLib3Instrumentor().instrument()      # the MinIO client speaks HTTP via urllib3
