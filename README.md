# ops-platform-lab — Document Vault

A hands-on lab to **deploy and operate** a small *Document Vault* service with a
full production-style operations stack, on a single cloud VM (Vultr / GCP).
Built to practice and prove the skills of a **System & Software Operations Engineer**.

**Author:** Cedric Severin DJIGUIMDE

## Stack covered (matches the job description)
| Layer | Tech |
|-------|------|
| OS | Ubuntu (hardened) |
| Containers | Docker & Docker Compose |
| App | Flask (Python) |
| Database | PostgreSQL |
| Cache / counters | Redis |
| Object storage (S3) | MinIO |
| Event bus | Apache Kafka (+ a worker consumer) |
| Reverse proxy / LB / TLS | Nginx |
| Monitoring | Prometheus + Grafana |
| Orchestration | Kubernetes (k3s) — Phase 5 |
| Automation / CI | Ansible + GitHub Actions — Phase 6 |

## Architecture
```
User → Nginx (reverse proxy + load balancing + TLS)
          → Flask app (xN replicas)
               → PostgreSQL   (metadata)
               → Redis        (upload counter / cache)
               → MinIO        (file storage, S3)
               → Kafka        → Worker (consumes "upload" events)
Monitoring: Prometheus scrapes metrics → Grafana dashboards
```

## Quickstart (Docker Compose)
```bash
cp .env.example .env         # set your passwords
docker compose up -d --build
# App (via Nginx):     http://SERVER_IP
# MinIO console:       http://SERVER_IP:9001
docker compose ps
```

## Full lab guide
Follow **[docs/GUIDE.md](docs/GUIDE.md)** — step by step, Phase 0 → Phase 6.
