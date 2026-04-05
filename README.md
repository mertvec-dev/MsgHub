# MsgHub

Мессенджер с личными и групповыми чатами: REST API, WebSocket для событий в реальном времени, JWT (access + refresh), PostgreSQL, Redis.

## Возможности

- Регистрация и вход, сессии (список активных сессий в API)
- Друзья: заявки, принятие, блокировка
- Комнаты: личные (direct) и группы, приглашения, кик, бан, выход
- Сообщения: отправка, редактирование, удаление, непрочитанные, курсорная подгрузка истории
- Фронтенд: React (Vite), авто-обновление access-токена при 401 (`refresh`)

## Стек

| Слой | Технологии |
|------|------------|
| Backend | Python 3.11+, FastAPI, Uvicorn, SQLModel, asyncpg, Redis |
| Frontend | React, TypeScript, Vite, axios |
| Инфраструктура | Docker Compose: PostgreSQL 15, Redis 7 |

Подробнее о потоках данных и роли Redis — [ARCHITECTURE.md](./ARCHITECTURE.md).

## Требования

- [Docker](https://www.docker.com/) и Docker Compose (для бэкенда и БД)
- [Node.js](https://nodejs.org/) 18+ (для фронтенда в режиме разработки)

## Быстрый старт

### 1. Переменные окружения

```bash
cp .env.example .env
```

Отредактируй `.env`: задай пароли и при необходимости `DATABASE_URL` / `REDIS_URL` (для Compose см. комментарии в `.env.example`).

При первом запуске бэкенд может дописать `SECRET_KEY` в `.env`, если его не было.

### 2. Запуск бэкенда и сервисов

Из корня репозитория:

```bash
docker compose up --build
```

- API: <http://localhost:8000>
- Интерактивная документация OpenAPI: <http://localhost:8000/docs>
- Проверка: `GET /` → `{"status":"ok",...}`

### 3. Фронтенд (разработка)

Фронт в Compose по умолчанию не поднимается; удобнее на хосте:

```bash
cd app/frontend
npm install
npm run dev
```

Приложение: <http://localhost:5173>. В `app/frontend` при необходимости задай `VITE_WS_URL` (по умолчанию `ws://localhost:8000/ws`).

Убедись, что в `.env` бэкенда `ALLOWED_ORIGINS` содержит origin фронта (например `http://localhost:5173`).

### Сборка фронтенда

```bash
cd app/frontend
npm run build
```

Статика в `app/frontend/dist/` — её можно отдавать через nginx или встроить в отдельный контейнер.

## Переменные окружения (бэкенд)

| Переменная | Описание |
|------------|----------|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DB_NAME` | Учётные данные БД (для сервиса `db` в Compose) |
| `DATABASE_URL` | SQLAlchemy async URL, например `postgresql+asyncpg://USER:PASS@db:5432/DB_NAME` в Docker |
| `REDIS_URL` | Например `redis://redis:6379/0` в Docker |
| `SECRET_KEY` | Секрет подписи JWT (не коммитить реальное значение) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Срок жизни access (по умолчанию 30) |
| `REFRESH_TOKEN_EXPIRE_DAYS` / `SESSION_EXPIRE_DAYS` | Срок refresh и сессии в БД |
| `ALLOWED_ORIGINS` | CORS: через запятую, без пробелов лишних |
| `LOG_LEVEL` | `INFO`, `DEBUG`, … |
| `RATE_LIMIT_*` | Лимиты slowapi (логин, сообщения, остальное) |

Полный список полей — `app/backend/config.py` (класс `Settings`).

## Структура репозитория (кратко)

```
app/backend/     # FastAPI: роутеры, сервисы, схемы, WebSocket, pub/sub
app/frontend/    # React SPA
database/        # Подключение к БД, Redis-клиент, модели SQLModel
Dockerfile       # Образ бэкенда
docker-compose.yml
```

## Документация API

После запуска бэкенда: **Swagger UI** — <http://localhost:8000/docs>, **OpenAPI JSON** — <http://localhost:8000/openapi.json>.
