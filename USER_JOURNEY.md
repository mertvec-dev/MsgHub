# Путь пользователя в MsgHub (бэкенд)

Цепочка: **регистрация / вход → комнаты → WebSocket → сообщения**.

---

## 1. Регистрация — `POST /auth/register`

1. Роутер `app/backend/routers/auth.py` принимает тело, Pydantic-схема валидирует поля.
2. `auth_service.register`:
   - проверка сложности пароля;
   - проверка уникальности nickname / username / email;
   - создание записи **`User`** в PostgreSQL с хешем пароля;
   - создание **сессии** в таблице **`sessions`** (refresh-токен, срок жизни);
   - кэш сессии в **Redis** (быстрая проверка при refresh).
3. Генерация **JWT**: **access** (короткий) и **refresh** (длинный), в payload access — `user_id`.
4. Ответ — пара токенов; клиент сохраняет их и дальше шлёт `Authorization: Bearer <access>` для HTTP API.

После успешной регистрации пользователь уже с токенами; отдельный логин не обязателен, но обычно следующий сеанс начинается с входа.

---

## 2. Вход — `POST /auth/login`

Для уже существующего аккаунта:

1. Тело: username + password.
2. `auth_service.login`: поиск **`User`**, проверка пароля (bcrypt), создание новой **сессии** (БД + Redis), выдача новой пары **access + refresh**.
3. В сессию пишутся IP и User-Agent (список устройств: `GET /auth/sessions`).

### Обновление access без пароля

Когда access истёк: **`POST /auth/refresh`** с refresh-токеном в теле → `auth_service.refresh` проверяет сессию в БД/Redis и возвращает новую пару токенов.

---

## 3. Комнаты (HTTP, с токеном)

Все запросы с заголовком **`Authorization: Bearer <access>`** → зависимость `get_current_user` возвращает **`user_id`**.

1. **`GET /rooms/my`** — список комнат, где пользователь есть в **`room_members`**.
2. **Групповая комната:** `POST /rooms/create` — `room_service.create_room`: создаётся **`Room`**, добавляются **`RoomMember`** (владелец + приглашённые). Онлайн-пользователям уходит уведомление через **WebSocket** и **Redis Pub/Sub** (`action: new_room`).
3. **Личный чат:** `POST /rooms/direct/{target_user_id}` — в сервисе проверяется дружба **ACCEPTED**, затем ищется существующая direct-комната или создаётся новая. Собеседнику уходит то же уведомление.

Пока пользователь только вызывает REST, real-time доставка сообщений в UI идёт через следующий шаг — WebSocket.

---

## 4. WebSocket — подключение к real-time

1. Клиент открывает **`/ws`** (в твоей схеме токен в заголовке при upgrade не используется).
2. `await websocket.accept()` — первое сообщение: JSON `{ "action": "auth", "token": "<access>" }`.
3. `verify_token` → `manager.connect(websocket, user_id)` — сокет сохраняется локально, в Redis фиксируется онлайн.
4. Сервер отвечает `{ "action": "authenticated", "user_id": ... }`.
5. Клиент шлёт `{ "action": "join_room", "room_id": N }` → `manager.set_user_room(user_id, room_id)` — без этого broadcast по комнате не знает, куда слать события.

---

## 5. Сообщения

### Отправка — `POST /messages/send`

Параметры: **`room_id`**, **`content`** (как в роутере).

1. `messages_service.send_message`: проверка членства в комнате → шифрование контента (Fernet) → запись **`Message`** в БД → обновление метаданных комнаты.
2. Роутер формирует payload с `action: new_message`, вызывает **`pubsub.publish_message`** (другие инстансы) и **`manager.broadcast_to_room`** (подключённые клиенты в этой комнате на текущем процессе).

### История — `GET /messages/{room_id}`

Cursor-пагинация; при просмотре обновляется логика прочитанного и рассылается `messages_read` при необходимости.

---

## Сводка

```
register или login  →  access + refresh в клиенте
        ↓
GET /rooms/my, POST /rooms/create или /rooms/direct/…  (HTTP + Bearer)
        ↓
WebSocket /ws  →  auth  →  authenticated  →  join_room
        ↓
POST /messages/send  →  БД  →  Redis (инстансы)  +  WebSocket (broadcast в комнате)
```

---

## Связанные файлы (ориентир)

| Этап        | Роутер / точка входа      | Сервис              |
|------------|---------------------------|---------------------|
| Регистрация / логин / refresh | `routers/auth.py`   | `services/auth_service.py` |
| Комнаты    | `routers/rooms.py`        | `services/rooms_service.py` |
| Сообщения  | `routers/messages.py`     | `services/messages_service.py` |
| WS         | `main.py` (`/ws`)         | `websocket.py` (`ConnectionManager`) |
| Межсервер  | —                         | `services/pubsub.py` |
