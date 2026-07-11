import os, io, json, time
from flask import Flask, request, redirect, render_template_string
import psycopg2
import redis
from minio import Minio
from kafka import KafkaProducer

DATABASE_URL   = os.environ.get("DATABASE_URL", "postgresql://vault:vaultpass@postgres:5432/vault")
REDIS_HOST     = os.environ.get("REDIS_HOST", "redis")
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "minio:9000")
MINIO_USER     = os.environ.get("MINIO_USER", "admin")
MINIO_PASSWORD = os.environ.get("MINIO_PASSWORD", "admin12345")
KAFKA_BROKER   = os.environ.get("KAFKA_BROKER", "kafka:9092")
BUCKET         = "documents"

app = Flask(__name__)
r = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)

def db():
    return psycopg2.connect(DATABASE_URL)

def minio_client():
    return Minio(MINIO_ENDPOINT, access_key=MINIO_USER, secret_key=MINIO_PASSWORD, secure=False)

def init():
    # Wait for PostgreSQL, then create the table
    for _ in range(30):
        try:
            conn = db(); cur = conn.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS documents ("
                        "id SERIAL PRIMARY KEY, name TEXT, created_at TIMESTAMP DEFAULT now())")
            conn.commit(); cur.close(); conn.close()
            break
        except Exception as e:
            print("waiting for postgres...", e); time.sleep(2)
    # Create the MinIO bucket if needed
    try:
        mc = minio_client()
        if not mc.bucket_exists(BUCKET):
            mc.make_bucket(BUCKET)
    except Exception as e:
        print("minio init:", e)

PAGE = """<!doctype html><title>Document Vault</title>
<h1>Document Vault</h1>
<p><b>Total uploads:</b> {{count}}</p>
<form method=post enctype=multipart/form-data action=/upload>
  <input type=file name=file required> <button>Upload</button>
</form>
<h3>Latest documents</h3>
<ul>{% for d in docs %}<li>{{d[1]}} &mdash; {{d[2]}}</li>{% endfor %}</ul>"""

@app.route("/")
def index():
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT id, name, created_at FROM documents ORDER BY id DESC LIMIT 20")
    docs = cur.fetchall(); cur.close(); conn.close()
    count = r.get("uploads") or 0
    return render_template_string(PAGE, docs=docs, count=count)

@app.route("/upload", methods=["POST"])
def upload():
    f = request.files["file"]
    data = f.read()
    # 1) store the file in MinIO (S3)
    minio_client().put_object(BUCKET, f.filename, io.BytesIO(data), length=len(data))
    # 2) store metadata in PostgreSQL
    conn = db(); cur = conn.cursor()
    cur.execute("INSERT INTO documents(name) VALUES (%s)", (f.filename,))
    conn.commit(); cur.close(); conn.close()
    # 3) increment the counter in Redis
    r.incr("uploads")
    # 4) publish an event to Kafka
    try:
        p = KafkaProducer(bootstrap_servers=KAFKA_BROKER,
                          value_serializer=lambda v: json.dumps(v).encode())
        p.send("document-events", {"event": "upload", "name": f.filename})
        p.flush()
    except Exception as e:
        print("kafka producer error:", e)
    return redirect("/")

@app.route("/health")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    init()
    app.run(host="0.0.0.0", port=5000)
