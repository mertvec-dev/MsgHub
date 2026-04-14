#!/usr/bin/env bash
# Пересборка фронта в образе nginx (обход «No services to build» у docker compose).
# Запуск из корня репозитория: bash scripts/rebuild-nginx.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Сборка Dockerfile.nginx (CACHEBUST сбрасывает кэш слоя npm run build)..."
export GIT_REVISION="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
export CACHEBUST="$(date +%s)"
docker compose build nginx --no-cache

echo "==> Перезапуск контейнера nginx с новым образом..."
docker compose up -d --force-recreate nginx

echo "==> Готово. Проверка:"
docker compose ps nginx
echo "Откройте сайт с Ctrl+F5 или в режиме инкогнито."
