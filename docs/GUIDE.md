# Deployment & Operations Guide

This guide describes how to deploy and operate the **Document Vault** platform:
first on a single Linux host with Docker Compose, then on a Kubernetes cluster.

## Prerequisites

- A Linux host running **Ubuntu 24.04 LTS**.
- **4 GB RAM** minimum (8 GB recommended once Kafka and Kubernetes are added).
- SSH access to the host and a user with `sudo` privileges.

---

## 1. Server hardening

Apply a baseline security configuration before deploying any workload.

```bash
# System updates
sudo apt update && sudo apt -y upgrade

# SSH hardening: in /etc/ssh/sshd_config set
#   PermitRootLogin no
#   PasswordAuthentication no        (key-based authentication only)
sudo systemctl restart ssh

# Host firewall
sudo apt install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw enable

# Brute-force protection
sudo apt install -y fail2ban
sudo systemctl enable --now fail2ban
```

**Verification:** `sudo ufw status` reports `active`; `systemctl status fail2ban`
reports `active (running)`; SSH login works with a key and rejects passwords.

---

## 2. Install Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"   # log out / back in for the group to apply
```

**Verification:** `docker --version`, `docker compose version`, and
`docker run hello-world` all succeed without `sudo`.

---

## 3. Deploy the stack (Docker Compose)

```bash
git clone https://github.com/CedricCloudOps/ops-platform-lab.git
cd ops-platform-lab
cp .env.example .env      # set strong passwords
docker compose up -d --build
docker compose ps
```

**Verification:**
- Application (through Nginx): `http://HOST_IP`
- MinIO console: `http://HOST_IP:9001`
- Worker consuming Kafka events: `docker compose logs worker`

---

## 4. Components

| Component | Role | Quick check |
|-----------|------|-------------|
| PostgreSQL | Document metadata | `docker compose exec postgres psql -U vault -d vault -c 'SELECT * FROM documents;'` |
| Redis | Upload counter / cache | `docker compose exec redis redis-cli GET uploads` |
| MinIO | S3-compatible file storage | Web console on port `9001` |
| Kafka | Event bus | `docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --list --bootstrap-server localhost:9092` |
| Nginx | Reverse proxy / load balancing | `docker compose up -d --scale app=3` distributes traffic across replicas |

---

## 5. Monitoring (Prometheus + Grafana)

Add a `monitoring/prometheus.yml` scrape configuration and two services to the
compose file:

```yaml
  prometheus:
    image: prom/prometheus
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro
    ports: ["9090:9090"]
    restart: unless-stopped
  grafana:
    image: grafana/grafana
    ports: ["3000:3000"]
    restart: unless-stopped
```

Prometheus collects the metrics; Grafana visualizes them
(add Prometheus as a data source at `http://prometheus:9090`).

---

## 6. Backup & security

```bash
# PostgreSQL logical backup
docker compose exec -T postgres pg_dump -U vault vault > backup_$(date +%F).sql

# Restore (validate the backup)
cat backup_YYYY-MM-DD.sql | docker compose exec -T postgres psql -U vault -d vault
```

Additional hardening: schedule the backup with `cron`, mirror the MinIO bucket
off-site, and terminate TLS at Nginx (Let's Encrypt in production).

---

## 7. Kubernetes (k3s)

> **Important — do not run k3s and the Docker Compose stack at the same time.**
> They are two independent orchestrators and both fight for port 80 (Nginx vs
> Traefik). Stopping k3s does **not** remove its iptables rules, so it keeps
> hijacking the external IP. See
> **[Docker Compose vs Kubernetes](docker-compose-vs-kubernetes.md)** for the
> full explanation and the troubleshooting commands.

```bash
curl -sfL https://get.k3s.io | sh -
sudo k3s kubectl get nodes
```

Deploy, scale and roll back a workload:

```bash
kubectl apply -f k8s/app-deployment.yaml
kubectl get pods,svc
kubectl scale deployment/web --replicas=5
kubectl rollout status deployment/web
kubectl rollout undo deployment/web
```

The stack is progressively migrated from Compose to Kubernetes manifests under
`k8s/` (Deployments, Services, ConfigMaps, PersistentVolumeClaims, Ingress).

---

## 8. Automation & CI/CD

- **Ansible** — provision the host (updates, hardening, Docker) declaratively.
- **GitHub Actions** — build the application image on every push:

```yaml
name: build
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker build -t vault-app ./app
```
