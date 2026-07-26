"""Unit tests for the Document Vault app.

These run WITHOUT PostgreSQL, Redis, MinIO or Kafka: importing app.py only
builds the Flask object (the connections happen in init(), called from
__main__), so we can exercise the routes that don't touch a backend.
Backend-dependent routes (upload/download) belong to integration tests.
"""
import os
import sys
import pathlib

import pytest

# Credentials must be set BEFORE importing the app: they are read at import time.
os.environ["ADMIN_USER"] = "admin"
os.environ["ADMIN_PASSWORD"] = "test-password"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["OTEL_SDK_DISABLED"] = "true"   # no trace collector in CI

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import app as vault  # noqa: E402


@pytest.fixture
def client():
    vault.app.config["TESTING"] = True
    with vault.app.test_client() as c:
        yield c


def login(client):
    return client.post("/login",
                       data={"username": "admin", "password": "test-password"},
                       follow_redirects=False)


# --- health & metrics: unauthenticated, scraped by Docker and Prometheus ----

def test_health_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_metrics_exposes_prometheus_format(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # The app's own metrics must be exposed, in Prometheus text format.
    assert "vault_http_requests_total" in body
    assert "vault_uploads_total" in body
    assert "# TYPE" in body


def test_metrics_counts_requests(client):
    """Hitting an endpoint must increment the request counter."""
    client.get("/health")
    body = client.get("/metrics").get_data(as_text=True)
    assert 'endpoint="health"' in body


# --- authentication --------------------------------------------------------

def test_login_page_is_reachable(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "Document Vault" in resp.get_data(as_text=True)


def test_login_with_valid_credentials_redirects_home(client):
    resp = login(client)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")


def test_login_with_bad_password_is_rejected(client):
    resp = client.post("/login", data={"username": "admin", "password": "wrong"})
    assert resp.status_code == 200                      # form redisplayed
    assert "Identifiants invalides" in resp.get_data(as_text=True)


def test_protected_route_redirects_to_login(client):
    """An anonymous user must never reach the vault."""
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_logout_clears_the_session(client):
    login(client)
    resp = client.get("/logout")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
    # After logout the protected route must redirect again.
    assert client.get("/").status_code == 302


# --- secrets handling ------------------------------------------------------

def test_read_secret_prefers_the_file(tmp_path):
    """The _FILE convention (Docker secrets) wins over the env var."""
    secret_file = tmp_path / "pw.txt"
    secret_file.write_text("  from-file  \n")     # whitespace must be stripped
    os.environ["DEMO_SECRET"] = "from-env"
    os.environ["DEMO_SECRET_FILE"] = str(secret_file)
    try:
        assert vault.read_secret("DEMO_SECRET") == "from-file"
    finally:
        del os.environ["DEMO_SECRET"], os.environ["DEMO_SECRET_FILE"]


def test_read_secret_falls_back_to_env_then_default():
    os.environ["DEMO_SECRET"] = "from-env"
    try:
        assert vault.read_secret("DEMO_SECRET") == "from-env"
    finally:
        del os.environ["DEMO_SECRET"]
    assert vault.read_secret("DEMO_SECRET_MISSING", "fallback") == "fallback"


# --- distributed tracing across Kafka --------------------------------------

def test_trace_context_survives_kafka_headers():
    """The app injects the trace context into Kafka headers and the worker
    extracts it — that round-trip is what links an upload to its later scan."""
    from opentelemetry import trace
    from opentelemetry.propagate import inject, extract
    from opentelemetry.sdk.trace import TracerProvider

    # OTEL_SDK_DISABLED (set above for the app) makes the SDK produce non-recording
    # spans, which propagate nothing — lift it for this test only.
    os.environ.pop("OTEL_SDK_DISABLED", None)
    try:
        provider = TracerProvider()
        tracer = provider.get_tracer("test")

        with tracer.start_as_current_span("upload") as span:
            expected_trace_id = span.get_span_context().trace_id
            carrier = {}
            inject(carrier)
    finally:
        os.environ["OTEL_SDK_DISABLED"] = "true"

    # The app encodes the carrier as Kafka headers; the worker decodes them.
    kafka_headers = [(k, v.encode()) for k, v in carrier.items()]
    assert any(k == "traceparent" for k, _ in kafka_headers)

    decoded = {k: v.decode() for k, v in kafka_headers}
    ctx = extract(decoded)
    restored = trace.get_current_span(ctx).get_span_context()

    # Same trace on the other side of the broker: the scan joins the upload.
    assert restored.trace_id == expected_trace_id
