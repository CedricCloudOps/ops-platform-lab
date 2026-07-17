import os, io, json, time, hmac
from functools import wraps
from flask import Flask, request, redirect, render_template_string, Response, abort, session
import psycopg2
import redis
from minio import Minio
from kafka import KafkaProducer

def read_secret(name, default=""):
    """Read a secret from <NAME>_FILE (Docker secret) if present, else the
    <NAME> env var, else a default. Keeps passwords out of environment vars."""
    path = os.environ.get(name + "_FILE")
    if path:
        try:
            with open(path) as fh:
                return fh.read().strip()
        except OSError:
            pass
    return os.environ.get(name, default)

REDIS_HOST     = os.environ.get("REDIS_HOST", "redis")
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "minio:9000")
MINIO_USER     = os.environ.get("MINIO_USER", "admin")
MINIO_PASSWORD = read_secret("MINIO_PASSWORD", "admin12345")
KAFKA_BROKER   = os.environ.get("KAFKA_BROKER", "kafka:9092")

PG_USER        = os.environ.get("POSTGRES_USER", "vault")
PG_HOST        = os.environ.get("POSTGRES_HOST", "postgres")
PG_DB          = os.environ.get("POSTGRES_DB", "vault")
PG_PASSWORD    = read_secret("POSTGRES_PASSWORD", "vaultpass")
DATABASE_URL   = os.environ.get("DATABASE_URL") or \
    "postgresql://%s:%s@%s:5432/%s" % (PG_USER, PG_PASSWORD, PG_HOST, PG_DB)
BUCKET         = "documents"

SECRET_KEY     = read_secret("SECRET_KEY", "dev-insecure-change-me")
ADMIN_USER     = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = read_secret("ADMIN_PASSWORD", "admin")

app = Flask(__name__)
app.secret_key = SECRET_KEY
r = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return redirect("/login")
        return f(*args, **kwargs)
    return wrapper

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
                        "id SERIAL PRIMARY KEY, name TEXT, created_at TIMESTAMP DEFAULT now(), "
                        "scan_status TEXT DEFAULT 'pending')")
            cur.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS scan_status TEXT DEFAULT 'pending'")
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

PAGE = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Document Vault</title>
<style>
:root{
  --bg:#eef1f8;--card:#fff;--text:#141a29;--muted:#6b7280;--border:#e5e8f0;
  --accent:#4f46e5;--accent2:#7c3aed;--ring:rgba(79,70,229,.35);
  --shadow:0 1px 2px rgba(16,24,40,.05),0 4px 16px rgba(16,24,40,.06);
}
@media (prefers-color-scheme:dark){
  :root{--bg:#0d111c;--card:#161c2b;--text:#e8ebf3;--muted:#95a0b8;--border:#242c3e;
        --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.35);}
}
*{box-sizing:border-box}
html,body{margin:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  background:var(--bg);color:var(--text);line-height:1.55;-webkit-font-smoothing:antialiased}
.wrap{max-width:840px;margin:0 auto;padding:28px 18px 64px}
.hero{position:relative;border-radius:18px;padding:30px;color:#fff;
  background:linear-gradient(135deg,var(--accent),var(--accent2));box-shadow:var(--shadow)}
.logout{position:absolute;top:16px;right:18px;color:#fff;opacity:.9;font-size:.78rem;text-decoration:none;border:1px solid rgba(255,255,255,.35);padding:5px 12px;border-radius:8px}
.logout:hover{background:rgba(255,255,255,.14)}
.hero h1{margin:0 0 .3rem;font-size:1.9rem;letter-spacing:-.02em;display:flex;align-items:center;gap:12px}
.hero p{margin:0;opacity:.9;font-size:.95rem}
.hero .chips{margin-top:14px;display:flex;flex-wrap:wrap;gap:8px}
.hero .chip{background:rgba(255,255,255,.18);border:1px solid rgba(255,255,255,.25);
  padding:3px 10px;border-radius:999px;font-size:.75rem;font-weight:500}
.stats{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:18px 0}
.stat{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:18px 20px;box-shadow:var(--shadow)}
.stat .num{font-size:2rem;font-weight:700;letter-spacing:-.02em}
.stat .lbl{color:var(--muted);font-size:.85rem;margin-top:2px}
.card{background:var(--card);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow);padding:20px 22px;margin-bottom:18px}
.upload{display:flex;flex-wrap:wrap;align-items:center;gap:12px}
.filebtn{position:relative;display:inline-flex;align-items:center;gap:8px;cursor:pointer;
  padding:10px 16px;border-radius:10px;border:1px solid var(--border);color:var(--text);font-weight:500}
.filebtn:hover{border-color:var(--accent)}
.filebtn input{position:absolute;inset:0;opacity:0;cursor:pointer}
.fname{color:var(--muted);font-size:.9rem;flex:1;min-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.btn{display:inline-flex;align-items:center;gap:8px;border:0;cursor:pointer;font-weight:600;
  padding:11px 20px;border-radius:10px;color:#fff;background:linear-gradient(135deg,var(--accent),var(--accent2));box-shadow:0 2px 8px var(--ring)}
.btn:hover{filter:brightness(1.06)}
.btn:active{transform:translateY(1px)}
h2.sec{font-size:1.05rem;margin:0 0 14px}
ul.docs{list-style:none;margin:0;padding:0}
ul.docs li{display:flex;align-items:center;gap:14px;padding:12px 6px;border-bottom:1px solid var(--border)}
ul.docs li:last-child{border-bottom:0}
.ext{flex:none;width:44px;height:44px;border-radius:10px;display:flex;align-items:center;justify-content:center;
  font-size:.7rem;font-weight:700;background:rgba(107,114,128,.14);color:#6b7280}
.ext-pdf{background:rgba(224,49,49,.14);color:#e03131}
.ext-doc,.ext-docx{background:rgba(59,125,221,.16);color:#3b7ddd}
.ext-png,.ext-jpg,.ext-jpeg,.ext-gif{background:rgba(30,142,90,.16);color:#1e8e5a}
.ext-xls,.ext-xlsx,.ext-csv{background:rgba(47,158,68,.16);color:#2f9e44}
.ext-zip,.ext-rar{background:rgba(214,158,46,.16);color:#d69e2e}
.doc-info{min-width:0;flex:1}
.doc-name{display:block;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text);text-decoration:none}
a.doc-name:hover{color:var(--accent);text-decoration:underline}
.doc-date{color:var(--muted);font-size:.82rem}
.dl{flex:none;display:inline-flex;align-items:center;justify-content:center;width:38px;height:38px;border-radius:9px;color:var(--muted);border:1px solid var(--border);text-decoration:none}
.dl:hover{color:var(--accent);border-color:var(--accent)}
.status{flex:none;font-size:.72rem;font-weight:600;padding:3px 9px;border-radius:999px;white-space:nowrap}
.status-clean{background:rgba(30,142,90,.16);color:#1e8e5a}
.status-infected{background:rgba(224,49,49,.16);color:#e03131}
.status-pending{background:rgba(107,114,128,.16);color:#6b7280}
.status-error{background:rgba(214,158,46,.16);color:#d69e2e}
.empty{color:var(--muted);text-align:center;padding:28px 0}
.footer{color:var(--muted);font-size:.8rem;text-align:center;margin-top:8px}
@media(max-width:560px){.stats{grid-template-columns:1fr}.hero h1{font-size:1.6rem}.btn{flex:1;justify-content:center}}
</style>
</head>
<body>
<div class="wrap">
  <header class="hero">
    <a class="logout" href="/logout">Déconnexion</a>
    <h1>
      <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="12" cy="12" r="3"/><path d="M12 6v3M12 15v3M18 12h-3M9 12H6"/></svg>
      Document Vault
    </h1>
    <p>Stockage sécurisé de documents — pipeline conteneurisé</p>
    <div class="chips">
      <span class="chip">Flask</span><span class="chip">PostgreSQL</span>
      <span class="chip">MinIO (S3)</span><span class="chip">Redis</span>
      <span class="chip">Kafka</span><span class="chip">Nginx</span>
    </div>
  </header>

  <div class="stats">
    <div class="stat"><div class="num">{{ total }}</div><div class="lbl">Documents stockés (PostgreSQL)</div></div>
    <div class="stat"><div class="num">{{ count }}</div><div class="lbl">Événements d'upload (Redis)</div></div>
  </div>

  <div class="card">
    <form class="upload" method="post" enctype="multipart/form-data" action="/upload">
      <label class="filebtn">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>
        Choisir un fichier
        <input type="file" name="file" required onchange="var f=this.files[0];document.getElementById('fn').textContent=f?f.name:'Aucun fichier sélectionné'">
      </label>
      <span id="fn" class="fname">Aucun fichier sélectionné</span>
      <button class="btn" type="submit">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M17 8l-5-5-5 5"/><path d="M12 3v12"/></svg>
        Uploader
      </button>
    </form>
  </div>

  <div class="card">
    <h2 class="sec">Derniers documents</h2>
    {% if docs %}
    <ul class="docs">
      {% for d in docs %}
      {% set ext = (d[1].rsplit('.',1)[1]|lower) if '.' in d[1] else '' %}
      {% set st = d[3] or 'pending' %}
      <li>
        <span class="ext ext-{{ ext or 'file' }}">{{ (ext or 'FILE')|upper }}</span>
        <div class="doc-info">
          <a class="doc-name" href="/download/{{ d[1]|urlencode }}">{{ d[1] }}</a>
          <div class="doc-date">{{ d[2].strftime('%d/%m/%Y · %H:%M') if d[2] else '' }}</div>
        </div>
        <span class="status status-{{ st }}">{{ {'clean':'sain','infected':'infecté','pending':'scan…','error':'erreur'}.get(st, st) }}</span>
        <a class="dl" href="/download/{{ d[1]|urlencode }}" title="Télécharger">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/></svg>
        </a>
      </li>
      {% endfor %}
    </ul>
    {% else %}
    <div class="empty">Aucun document pour le moment. Uploadez votre premier fichier ci-dessus.</div>
    {% endif %}
  </div>

  <div class="footer">ops-platform-lab · Document Vault</div>
</div>
</body>
</html>"""

LOGIN_PAGE = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Connexion — Document Vault</title>
<style>
:root{--bg:#eef1f8;--card:#fff;--text:#141a29;--muted:#6b7280;--border:#e5e8f0;
  --accent:#4f46e5;--accent2:#7c3aed;--ring:rgba(79,70,229,.35);
  --shadow:0 1px 2px rgba(16,24,40,.05),0 12px 34px rgba(16,24,40,.12)}
@media (prefers-color-scheme:dark){:root{--bg:#0d111c;--card:#161c2b;--text:#e8ebf3;--muted:#95a0b8;
  --border:#242c3e;--shadow:0 1px 2px rgba(0,0,0,.4),0 14px 34px rgba(0,0,0,.45)}}
*{box-sizing:border-box}html,body{margin:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  background:var(--bg);color:var(--text);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.box{width:100%;max-width:380px;background:var(--card);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow);padding:32px 30px}
.logo{display:flex;align-items:center;gap:11px;font-size:1.3rem;font-weight:700;margin-bottom:6px}
.logo .ic{flex:none;width:40px;height:40px;border-radius:11px;display:flex;align-items:center;justify-content:center;color:#fff;background:linear-gradient(135deg,var(--accent),var(--accent2))}
.sub{color:var(--muted);font-size:.88rem;margin-bottom:20px}
label{display:block;font-size:.82rem;font-weight:600;margin:14px 0 6px}
input{width:100%;padding:11px 13px;border-radius:10px;border:1px solid var(--border);background:transparent;color:var(--text);font-size:.95rem}
input:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px var(--ring)}
.btn{width:100%;margin-top:20px;border:0;cursor:pointer;font-weight:600;padding:12px;border-radius:10px;
  color:#fff;background:linear-gradient(135deg,var(--accent),var(--accent2));font-size:.95rem}
.btn:hover{filter:brightness(1.06)}
.err{margin-top:14px;background:rgba(224,49,49,.12);color:#e03131;font-size:.85rem;padding:9px 12px;border-radius:9px}
</style>
</head>
<body>
<form class="box" method="post" action="/login">
  <div class="logo"><span class="ic"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg></span> Document Vault</div>
  <div class="sub">Connecte-toi pour accéder au coffre sécurisé.</div>
  <label>Utilisateur</label>
  <input name="username" autofocus required>
  <label>Mot de passe</label>
  <input name="password" type="password" required>
  <button class="btn" type="submit">Se connecter</button>
  {% if error %}<div class="err">{{ error }}</div>{% endif %}
</form>
</body>
</html>"""

@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        u = request.form.get("username", "")
        p = request.form.get("password", "")
        if u == ADMIN_USER and hmac.compare_digest(p, ADMIN_PASSWORD):
            session["user"] = u
            return redirect("/")
        error = "Identifiants invalides."
    return render_template_string(LOGIN_PAGE, error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/")
@login_required
def index():
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT id, name, created_at, scan_status FROM documents ORDER BY id DESC LIMIT 20")
    docs = cur.fetchall()
    cur.execute("SELECT COUNT(*) FROM documents")
    total = cur.fetchone()[0]
    cur.close(); conn.close()
    count = r.get("uploads") or 0
    return render_template_string(PAGE, docs=docs, count=count, total=total, user=session.get("user"))

@app.route("/upload", methods=["POST"])
@login_required
def upload():
    f = request.files["file"]
    data = f.read()
    # 1) store the file in MinIO (S3)
    minio_client().put_object(BUCKET, f.filename, io.BytesIO(data), length=len(data))
    # 2) store metadata in PostgreSQL
    conn = db(); cur = conn.cursor()
    cur.execute("INSERT INTO documents(name) VALUES (%s) RETURNING id", (f.filename,))
    doc_id = cur.fetchone()[0]
    conn.commit(); cur.close(); conn.close()
    # 3) increment the counter in Redis
    r.incr("uploads")
    # 4) publish an event to Kafka
    try:
        p = KafkaProducer(bootstrap_servers=KAFKA_BROKER,
                          value_serializer=lambda v: json.dumps(v).encode())
        p.send("document-events", {"event": "upload", "name": f.filename, "id": doc_id})
        p.flush()
    except Exception as e:
        print("kafka producer error:", e)
    return redirect("/")

@app.route("/download/<path:name>")
@login_required
def download(name):
    try:
        obj = minio_client().get_object(BUCKET, name)
        data = obj.read()
        obj.close(); obj.release_conn()
    except Exception:
        abort(404)
    safe = "".join(c for c in name if c not in '"\r\n')
    return Response(data, headers={
        "Content-Disposition": 'attachment; filename="%s"' % safe,
        "Content-Type": "application/octet-stream",
    })

@app.route("/health")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    init()
    app.run(host="0.0.0.0", port=5000)
