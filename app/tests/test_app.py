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
    extracts it; that round-trip is what links an upload to its later scan."""
    from opentelemetry import trace
    from opentelemetry.propagate import inject, extract
    from opentelemetry.sdk.trace import TracerProvider

    # OTEL_SDK_DISABLED (set above for the app) makes the SDK produce non-recording
    # spans, which propagate nothing, so lift it for this test only.
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


# --- download: only files the antivirus has cleared ------------------------

class FakeObject:
    def __init__(self, data):
        self.data = data
    def read(self):
        return self.data
    def close(self):
        pass
    def release_conn(self):
        pass


class FakeMinio:
    def __init__(self):
        self.stored = {}
    def put_object(self, bucket, key, stream, length):
        self.stored[key] = stream.read()
    def get_object(self, bucket, key):
        if key not in self.stored:
            raise KeyError(key)
        return FakeObject(self.stored[key])


@pytest.fixture
def fake_minio(monkeypatch):
    fake = FakeMinio()
    monkeypatch.setattr(vault, "minio_client", lambda: fake)
    return fake


@pytest.mark.parametrize("status, expected", [
    ("infected", 403),     # never hand out a file flagged by ClamAV
    ("pending", 409),      # scan not finished yet
    ("error", 409),        # scan failed: not proven clean
])
def test_download_refuses_files_not_cleared(client, fake_minio, monkeypatch, status, expected):
    fake_minio.stored["k/eicar.com"] = b"payload"
    monkeypatch.setattr(vault, "fetch_document", lambda doc_id: ("eicar.com", "k/eicar.com", status))
    login(client)
    assert client.get("/download/1").status_code == expected


def test_download_serves_clean_file(client, fake_minio, monkeypatch):
    fake_minio.stored["k/report.pdf"] = b"%PDF-1.7"
    monkeypatch.setattr(vault, "fetch_document", lambda doc_id: ("report.pdf", "k/report.pdf", "clean"))
    login(client)
    resp = client.get("/download/1")
    assert resp.status_code == 200
    assert resp.data == b"%PDF-1.7"
    assert 'filename="report.pdf"' in resp.headers["Content-Disposition"]


def test_download_legacy_document_falls_back_to_its_name(client, fake_minio, monkeypatch):
    """Documents uploaded before object_key existed were stored under their name."""
    fake_minio.stored["old.txt"] = b"legacy"
    monkeypatch.setattr(vault, "fetch_document", lambda doc_id: ("old.txt", None, "clean"))
    login(client)
    assert client.get("/download/1").data == b"legacy"


def test_download_unknown_document_is_404(client, monkeypatch):
    monkeypatch.setattr(vault, "fetch_document", lambda doc_id: None)
    login(client)
    assert client.get("/download/999").status_code == 404


# --- upload: unique storage key, one reusable Kafka producer ---------------

class FakeProducer:
    instances = 0
    def __init__(self, **kwargs):
        FakeProducer.instances += 1
        self.sent = []
    def send(self, topic, value, headers=None):
        self.sent.append((topic, value))
    def flush(self):
        pass
    def close(self, timeout=None):
        pass


class FakeRedis:
    def incr(self, key):
        return 1


@pytest.fixture
def upload_backends(fake_minio, monkeypatch):
    ids = iter(range(1, 100))
    monkeypatch.setattr(vault, "insert_document", lambda name, key: next(ids))
    monkeypatch.setattr(vault, "r", FakeRedis())
    monkeypatch.setattr(vault, "KafkaProducer", FakeProducer)
    FakeProducer.instances = 0
    vault.reset_kafka_producer()
    yield fake_minio
    vault.reset_kafka_producer()


def upload(client, name, content=b"data"):
    import io
    return client.post("/upload", data={"file": (io.BytesIO(content), name)},
                       content_type="multipart/form-data")


def test_same_filename_twice_does_not_overwrite(client, upload_backends):
    login(client)
    upload(client, "report.pdf", b"first")
    upload(client, "report.pdf", b"second")
    stored = upload_backends.stored
    assert len(stored) == 2                             # two distinct objects
    assert sorted(stored.values()) == [b"first", b"second"]
    assert all(k.endswith("/report.pdf") and k != "report.pdf" for k in stored)


def test_kafka_producer_is_reused_across_uploads(client, upload_backends):
    login(client)
    for i in range(3):
        upload(client, "f%d.txt" % i)
    assert FakeProducer.instances == 1
    event = vault.kafka_producer().sent[-1][1]
    assert event["key"] in upload_backends.stored    # the worker gets the real key


def test_upload_without_file_is_ignored(client, upload_backends):
    login(client)
    resp = client.post("/upload", data={}, content_type="multipart/form-data")
    assert resp.status_code == 302
    assert upload_backends.stored == {}


def test_page_offers_download_link_only_for_clean_files():
    from datetime import datetime
    docs = [(1, "ok.pdf", datetime(2026, 9, 27), "clean"),
            (2, "eicar.com", datetime(2026, 9, 27), "infected"),
            (3, "new.docx", datetime(2026, 9, 27), "pending")]
    with vault.app.test_request_context("/"):
        html = vault.render_template_string(vault.PAGE, docs=docs, count=3, total=3, user="admin")
    assert 'href="/download/1"' in html
    assert 'href="/download/2"' not in html
    assert 'href="/download/3"' not in html
    assert "infecté" in html
