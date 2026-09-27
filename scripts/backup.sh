#!/usr/bin/env bash
# Nightly backup of the two stores that hold user data:
#   - PostgreSQL: document metadata and scan verdicts (pg_dump, custom format)
#   - MinIO:      the uploaded files themselves (mc mirror of the bucket)
# A metadata dump without the files, or the files without the metadata, cannot
# restore the vault: both are taken in the same run, into the same folder.
# Run by scripts/vault-backup.timer. Restore procedure: docs/RUNBOOK.md §5.
set -euo pipefail

REPO_DIR="${REPO_DIR:-/home/cedric/ops-platform-lab}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/vault}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"

cd "$REPO_DIR"
STAMP=$(date +%F_%H%M)
DEST="$BACKUP_ROOT/$STAMP"
mkdir -p "$DEST"
echo "$(date -Is) backup started -> $DEST"

# 1) PostgreSQL. -T: no TTY, otherwise the dump is corrupted by line endings.
docker compose exec -T postgres pg_dump -U vault -Fc vault > "$DEST/postgres.dump"
# Check the dump is readable, not just present: a 0-byte or truncated file
# fails here tonight instead of on the day it is needed.
docker compose exec -T postgres pg_restore --list < "$DEST/postgres.dump" > /dev/null
echo "$(date -Is) postgres dump ok ($(du -h "$DEST/postgres.dump" | cut -f1))"

# 2) MinIO. The server image ships the mc client: mirror the bucket to a
# temporary folder inside the container, copy it out, clean up.
docker compose exec -T minio sh -c '
  mc alias set local http://localhost:9000 "$MINIO_ROOT_USER" "$(cat /run/secrets/minio_password)" >/dev/null &&
  rm -rf /tmp/vault-backup &&
  mc mirror --quiet local/documents /tmp/vault-backup'
docker compose cp minio:/tmp/vault-backup "$DEST/minio"
docker compose exec -T minio rm -rf /tmp/vault-backup
echo "$(date -Is) minio mirror ok ($(find "$DEST/minio" -type f | wc -l) objects)"

# 3) Retention: drop runs older than RETENTION_DAYS (only dated folders).
find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -name '20*' \
  -mtime +"$RETENTION_DAYS" -exec rm -rf {} +

echo "$(date -Is) backup done"
