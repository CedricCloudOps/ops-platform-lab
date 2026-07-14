import os, io, json, time
import psycopg2
from minio import Minio
from kafka import KafkaConsumer
import clamd


def read_secret(name, default=""):
    """Read a secret from <NAME>_FILE (Docker secret) if present, else env, else default."""
    path = os.environ.get(name + "_FILE")
    if path:
        try:
            with open(path) as fh:
                return fh.read().strip()
        except OSError:
            pass
    return os.environ.get(name, default)


KAFKA_BROKER   = os.environ.get("KAFKA_BROKER", "kafka:9092")
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "minio:9000")
MINIO_USER     = os.environ.get("MINIO_USER", "admin")
MINIO_PASSWORD = read_secret("MINIO_PASSWORD", "admin12345")
CLAMAV_HOST    = os.environ.get("CLAMAV_HOST", "clamav")
CLAMAV_PORT    = int(os.environ.get("CLAMAV_PORT", "3310"))
BUCKET         = "documents"

PG_USER      = os.environ.get("POSTGRES_USER", "vault")
PG_HOST      = os.environ.get("POSTGRES_HOST", "postgres")
PG_DB        = os.environ.get("POSTGRES_DB", "vault")
PG_PASSWORD  = read_secret("POSTGRES_PASSWORD", "vaultpass")
DATABASE_URL = os.environ.get("DATABASE_URL") or \
    "postgresql://%s:%s@%s:5432/%s" % (PG_USER, PG_PASSWORD, PG_HOST, PG_DB)


def minio_client():
    return Minio(MINIO_ENDPOINT, access_key=MINIO_USER, secret_key=MINIO_PASSWORD, secure=False)


def clamav():
    return clamd.ClamdNetworkSocket(host=CLAMAV_HOST, port=CLAMAV_PORT, timeout=120)


def wait_for_clamav():
    # ClamAV loads its virus database at startup (can take 1-2 min).
    for _ in range(60):
        try:
            if clamav().ping() == "PONG":
                print("ClamAV is ready.", flush=True)
                return
        except Exception as e:
            print("waiting for clamav (loading virus db)...", e, flush=True)
        time.sleep(5)


def scan_bytes(data):
    # instream returns e.g. {'stream': ('OK', None)} or {'stream': ('FOUND', 'Eicar-Signature')}
    result = clamav().instream(io.BytesIO(data))
    return "clean" if result["stream"][0] == "OK" else "infected"


def set_status(doc_id, name, status):
    conn = psycopg2.connect(DATABASE_URL); cur = conn.cursor()
    if doc_id is not None:
        cur.execute("UPDATE documents SET scan_status=%s WHERE id=%s", (status, doc_id))
    else:
        cur.execute("UPDATE documents SET scan_status=%s WHERE name=%s", (status, name))
    conn.commit(); cur.close(); conn.close()


def handle(event):
    name = event.get("name"); doc_id = event.get("id")
    print("Scanning:", name, flush=True)
    try:
        obj = minio_client().get_object(BUCKET, name)
        data = obj.read(); obj.close(); obj.release_conn()
        status = scan_bytes(data)
    except Exception as e:
        print("scan error:", e, flush=True); status = "error"
    set_status(doc_id, name, status)
    print("Result:", name, "->", status, flush=True)


def main():
    wait_for_clamav()
    for _ in range(40):
        try:
            consumer = KafkaConsumer(
                "document-events",
                bootstrap_servers=KAFKA_BROKER,
                auto_offset_reset="earliest",
                value_deserializer=lambda v: json.loads(v.decode()),
                group_id="worker",
            )
            print("Worker connected to Kafka, waiting for events...", flush=True)
            for msg in consumer:
                handle(msg.value)
            return
        except Exception as e:
            print("waiting for kafka...", e, flush=True); time.sleep(3)


if __name__ == "__main__":
    main()
