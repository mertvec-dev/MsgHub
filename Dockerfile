FROM python:3.11-slim

WORKDIR /app

# 1. Копируем зависимости (они теперь в app/backend)
COPY app/backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. Копируем ВЕСЬ проект (и app, и database, и .env)
COPY . .

# 3. Запуск с задержкой 5 сек (ждем, пока PostgreSQL проснется)
CMD sleep 5 && uvicorn app.backend.main:app --host 0.0.0.0 --port 8000