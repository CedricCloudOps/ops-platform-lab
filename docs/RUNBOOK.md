# Operations Runbook — Document Vault

Day-to-day operations guide for the Document Vault platform. Audience: the on-call
/ operations engineer. For a first-time install see [GUIDE.md](GUIDE.md); for the
Docker-vs-Kubernetes caveat see
[docker-compose-vs-kubernetes.md](docker-compose-vs-kubernetes.md).

---

## 1. Overview

A containerized document vault: a Flask app behind Nginx (HTTPS), backed by
PostgreSQL, Redis, MinIO and Kafka, with a worker that antivirus-scans every
upload (ClamAV). Observability = Prometheus + Grafana + Loki + Alertmanager.

| Layer | Services |
|-------|----------|
| Edge | nginx (80/443, TLS) |
| App | app (Flask), worker (Kafka consumer + ClamAV) |
| Data | postgres, redis, minio |
| Events | kafka, clamav |
| Observability | prometheus, alertmanager, grafana, loki, promtail, node-exporter, cadvisor, postgres-exporter, redis-exporter |

---

## 2. Access & URLs

Run all `docker compose` commands from the project directory (`~/ops-platform-lab`).

| What | URL / command |
|------|---------------|
| Application | `https://<HOST_IP>/` (redirects to `/login`) |
| Grafana | `http://<HOST_IP>:3000` |
| Prometheus | `http://<HOST_IP>:9090` (`/targets`, `/alerts`) |
| Alertmanager | `http://<HOST_IP>:9093` |
| MinIO console | `http://<HOST_IP>:9001` |
| Health endpoint | `curl -k https://<HOST_IP>/health` |

Secrets live in `secrets/*.txt` (git-ignored). TLS certs in `nginx/certs/` (git-ignored).

---

## 3. Start / stop / status

```bash
docker compose up -d          # start the whole stack
docker compose ps             # status of every container
docker compose down           # stop and remove containers (volumes/data are kept)
docker compose restart nginx  # restart a single service
```

> ClamAV takes ~2 minutes to load its virus database on first start (`health: starting`).

---

## 4. Health checks (daily / on alert)

```bash
docker compose ps                         # everything "Up" / "healthy"?
curl -k -s -o /dev/null -w "%{http_code}\n" https://localhost/    # expect 302
```
- **Grafana** → dashboards: host (Node Exporter), containers (Docker), PostgreSQL, Redis, Prometheus.
- **Prometheus** → `/targets` (all UP) and `/alerts` (all green/inactive).
- **Logs** → Grafana → Explore → Loki, e.g. `{container=~"ops-platform-lab-.*"} |= "error"`.

---

## 5. Backup & restore

```bash
# Backup PostgreSQL (the -T is required when redirecting to a file)
docker compose exec -T postgres pg_dump -U vault vault > backup_$(date +%F).sql

# Restore
cat backup_YYYY-MM-DD.sql | docker compose exec -T postgres psql -U vault -d vault
```
- MinIO objects live in the `miniodata` volume; mirror the bucket off-site for real backups.
- **Recommended:** schedule the backup with `cron` and verify a restore periodically (a backup you never restore is not a backup).

---

## 6. Common tasks

```bash
# Scale the app (Nginx load-balances across replicas)
docker compose up -d --scale app=3

# Tail a service's logs
docker compose logs -f worker           # watch antivirus scan results
docker compose logs --tail 50 app

# Query the database
docker compose exec postgres psql -U vault -d vault -c \
  "SELECT scan_status, COUNT(*) FROM documents GROUP BY scan_status;"

# Rotate a secret: edit secrets/<name>.txt, then
docker compose up -d <service>
```

### Verifying the antivirus pipeline

The **EICAR test string** is the industry-standard way to check that a scanner is
live — it is not malware, but every antivirus flags it by design. It is
deliberately **not committed** to this repository: shipping it would trigger
antivirus alerts for anyone cloning the project. Generate it locally instead:

```bash
# Generate the EICAR test file (harmless, detected by every AV engine)
printf '%s' 'X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*' > /tmp/eicar.com

# Upload it through the app, then watch the worker scan it
docker compose logs -f worker

# The verdict is written back to PostgreSQL
docker compose exec postgres psql -U vault -d vault -c \
  "SELECT name, scan_status FROM documents ORDER BY id DESC LIMIT 5;"
```

Expected result: the document is stored, the worker consumes the Kafka event,
ClamAV returns `FOUND`, and `scan_status` flips to **infected**. Upload any
ordinary file to confirm the `clean` path. Delete `/tmp/eicar.com` afterwards.

---

## 7. Troubleshooting (known incidents)

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| **502 Bad Gateway** (nginx) | app not ready, or stale upstream IP | wait 30s; `docker compose restart nginx` (nginx now re-resolves via `resolver 127.0.0.11`) |
| **404 page not found** (plain text) on external IP, but `localhost` works | k3s Traefik hijacking port 80 via leftover iptables | `sudo /usr/local/bin/k3s-killall.sh && sudo systemctl restart docker && docker compose up -d` |
| **Build fails**: `lookup registry-1.docker.io ... i/o timeout` | host DNS (VMware NAT) unreliable | set DNS in netplan (`dhcp4-overrides: use-dns: false` + `nameservers: [8.8.8.8, 1.1.1.1]`) |
| Alert **HostDiskAlmostFull** | root filesystem full | `df -h`; `docker system prune -f`; extend LVM: `lvextend -l +100%FREE ... && resize2fs ...` |
| A container in **Restarting** | crash at startup | `docker compose logs <svc>` — read the error first (missing secret, port conflict, OOM...) |
| systemd deploy `203/EXEC` | script not executable | `chmod +x scripts/deploy.sh` |

General method: **container status → logs → ports → resources → network.**

---

## 8. Incident response process

1. **Detect** — an alert fires (Alertmanager) or a user reports.
2. **Qualify** — impact, severity, scope.
3. **Restore first** — bring the service back (mitigate), even temporarily.
4. **Root cause** — diagnose calmly (logs, metrics).
5. **Fix** — permanent correction.
6. **Document** — write an incident report (symptom, impact, root cause, fix, prevention).
7. **Communicate** — inform stakeholders.

> Priority: **restore service first, understand later.**

---

## 9. Deployment (CI/CD)

- **CI** — every push runs GitHub Actions: build image + Trivy scan + `docker compose config` + `terraform validate`.
- **CD** — a systemd timer on the host runs `scripts/deploy.sh` every 2 min: if `origin/main` moved, it pulls and runs `docker compose up -d --build` (pull-based GitOps).

```bash
# CD status / logs
systemctl status vault-deploy.timer
journalctl -u vault-deploy.service -n 20 --no-pager
```

---

## 10. Escalation

| Level | Contact |
|-------|---------|
| L1 — on-call ops | _<name / phone>_ |
| L2 — platform owner | _<name>_ |
| L3 — vendor / project manager | _<name>_ |

Keep this list current; a runbook without contacts fails at 3 a.m.
