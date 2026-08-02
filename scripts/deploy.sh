#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${ENCOUNTER_RUNTIME_DIR:-/opt/encounter-table-api}"
STATIC_DIR="${ENCOUNTER_STATIC_DIR:-/var/www/bronze-brawl-encounter-table}"
SERVICE="${ENCOUNTER_SERVICE:-encounter-table-api.service}"
BRANCH="${DEPLOY_BRANCH:-main}"

cd "$APP_DIR"

echo "[deploy] Updating checkout to origin/${BRANCH}"
git fetch --prune origin "$BRANCH"
git checkout -B "$BRANCH" "origin/$BRANCH"
git reset --hard "origin/$BRANCH"

echo "[deploy] Installing API runtime files"
install -d -m 0755 "$RUNTIME_DIR" "$RUNTIME_DIR/data/games"
install -m 0644 api/app.py "$RUNTIME_DIR/app.py"
rsync -a --delete --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r data/games/ "$RUNTIME_DIR/data/games/"

echo "[deploy] Installing static frontend"
install -d -m 0755 "$STATIC_DIR"
rsync -a --delete --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r web/ "$STATIC_DIR/"

# Keep the persistent production data and its backups outside the repository.
echo "[deploy] Restarting API service"
systemctl restart "$SERVICE"
for _ in $(seq 1 20); do
  if systemctl is-active --quiet "$SERVICE" && curl -fsS http://127.0.0.1:9132/encounters >/dev/null; then
    echo "[deploy] API health check passed"
    exit 0
  fi
  sleep 2
done

echo "[deploy] API health check failed"
systemctl status "$SERVICE" --no-pager -l || true
exit 1
