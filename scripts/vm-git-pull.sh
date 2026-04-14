#!/usr/bin/env bash
# Безопасный pull на сервере, когда правили docker-compose.yml / nginx.conf/nginx.conf.
# Делает бэкап, откатывает эти файлы к последнему коммиту, тянет origin/main.
# Правки ВМ лучше хранить в docker-compose.override.yml (см. docker-compose.override.example.yml).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="${HOME}/MsgHub-vm-backups"
mkdir -p "$BACKUP_DIR"

backup() {
  local f="$1"
  if [[ -f "$f" ]]; then
    cp "$f" "${BACKUP_DIR}/$(basename "$f").${STAMP}.bak"
    echo "Сохранено: ${BACKUP_DIR}/$(basename "$f").${STAMP}.bak"
  fi
}

backup "docker-compose.yml"
backup "nginx.conf/nginx.conf"

git restore docker-compose.yml nginx.conf/nginx.conf
echo "==> git pull"
git pull

echo
echo "Готово. Если нужны были правки ВМ (443, SSL, порты) — сравните с бэкапом:"
echo "  diff ${BACKUP_DIR}/nginx.conf.${STAMP}.bak nginx.conf/nginx.conf"
echo "  diff ${BACKUP_DIR}/docker-compose.yml.${STAMP}.bak docker-compose.yml"
echo "Перенесите отличия в docker-compose.override.yml (в .gitignore) или вручную в новые файлы из репозитория."
