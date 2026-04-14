#!/usr/bin/env bash
# Пересборка фронта в образе nginx (обход «No services to build» у docker compose).
# Запуск из корня репозитория: bash scripts/rebuild-nginx.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Сборка Dockerfile.nginx (CACHEBUST сбрасывает кэш слоя npm run build)..."
docker build \
  -f Dockerfile.nginx \
  -t msghub-nginx:latest \
  --build-arg "CACHEBUST=$(date +%s)" \
  .

echo "==> Перезапуск контейнера nginx с новым образом..."
docker compose up -d --force-recreate nginx

echo "==> Готово. Проверка:"
docker compose ps nginx
echo "Откройте сайт с Ctrl+F5 или в режиме инкогнито."
