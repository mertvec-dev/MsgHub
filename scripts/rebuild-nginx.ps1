# Пересборка фронта в образе nginx (аналог scripts/rebuild-nginx.sh для Windows).
# Запуск из корня репозитория: .\scripts\rebuild-nginx.ps1
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot ".."))

Write-Host "==> Сборка Dockerfile.nginx (CACHEBUST сбрасывает кэш слоя npm run build)..."
$env:GIT_REVISION = (git rev-parse --short HEAD 2>$null)
if (-not $env:GIT_REVISION) { $env:GIT_REVISION = "unknown" }
$env:CACHEBUST = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds().ToString()
docker compose build nginx --no-cache
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> Перезапуск контейнера nginx с новым образом..."
docker compose up -d --force-recreate nginx
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> Готово. Проверка:"
docker compose ps nginx
Write-Host "Откройте сайт с Ctrl+F5 или в режиме инкогнито."
