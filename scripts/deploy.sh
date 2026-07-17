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
git reset --hard origin/main
docker compose up -d --build
echo "$(date -Is) deploy done"
