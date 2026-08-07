#!/usr/bin/env bash
# Pull-based continuous deployment.
# Fetch origin/main; if it moved, redeploy the stack. Run periodically
# (see scripts/vault-deploy.timer). Secrets and TLS certs are git-ignored,
# so `git reset --hard` never touches them.
set -euo pipefail

REPO_DIR="${REPO_DIR:-/home/cedric/ops-platform-lab}"
cd "$REPO_DIR"

git fetch --quiet origin main
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
  echo "$(date -Is) up to date (${LOCAL:0:7})"
  exit 0
fi

echo "$(date -Is) new revision ${REMOTE:0:7} — deploying"

# What changed in this revision? Needed below: `docker compose up -d` compares
# the *service definition*, not the contents of the files it mounts, so a new
# prometheus.yml or nginx.conf would otherwise be deployed to disk and never
# read by the running process.
CHANGED=$(git diff --name-only "$LOCAL" "$REMOTE")

git reset --hard origin/main
docker compose up -d --build

changed() { grep -qE "$1" <<<"$CHANGED"; }

# Prometheus: hot reload of the config and the alert rules, no scrape dropped.
# Requires --web.enable-lifecycle (set in docker-compose.yml).
if changed '^monitoring/(prometheus|alerts)\.yml$'; then
  echo "$(date -Is) prometheus config changed — reloading"
  curl -fsS -X POST http://localhost:9090/-/reload \
    && echo "$(date -Is) prometheus reloaded" \
    || echo "$(date -Is) WARNING: prometheus reload failed"
fi

# Nginx: hot reload, not a single client connection is dropped.
if changed '^nginx/'; then
  echo "$(date -Is) nginx config changed — reloading"
  docker compose exec -T nginx nginx -s reload \
    && echo "$(date -Is) nginx reloaded" \
    || echo "$(date -Is) WARNING: nginx reload failed"
fi

# Grafana provisions datasources at startup only — no hot reload available.
# (Dashboards are re-scanned every 30s, so they need nothing.)
if changed '^monitoring/grafana/provisioning/'; then
  echo "$(date -Is) grafana provisioning changed — restarting"
  docker compose restart grafana \
    && echo "$(date -Is) grafana restarted" \
    || echo "$(date -Is) WARNING: grafana restart failed"
fi

# Promtail and Alertmanager read their config at startup and expose no reload
# endpoint here, so they are restarted.
if changed '^monitoring/promtail-config\.yml$'; then
  echo "$(date -Is) promtail config changed — restarting"
  docker compose restart promtail || echo "$(date -Is) WARNING: promtail restart failed"
fi
if changed '^monitoring/alertmanager\.yml$'; then
  echo "$(date -Is) alertmanager config changed — restarting"
  docker compose restart alertmanager || echo "$(date -Is) WARNING: alertmanager restart failed"
fi

echo "$(date -Is) deploy done"
