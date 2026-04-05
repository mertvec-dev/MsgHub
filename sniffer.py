"""
🔍 MsgHub Sniffer — инструмент для чтения сообщений из БД
Запускается ВНУТРИ контейнера backend или с хоста

Использование:
    python sniffer.py           — показать сообщения
    python sniffer.py --users   — показать пользователей
    python sniffer.py --rooms   — показать комнаты
    python sniffer.py --all     — показать всё
"""

import asyncio
import asyncpg
import argparse
import os
from datetime import datetime

# Настройки подключения
# Если запускаем из контейнера — используем имя сервиса 'db'
# Если с хоста — localhost
DB_HOST = os.getenv("SNIFFER_DB_HOST", "db")  # По умолчанию 'db' для контейнера
DB_CONFIG = {
    "user": "postgres",
    "password": "8132",
    "database": "msghub",
    "host": DB_HOST,
    "port": 5432
}


async def sniff_messages(limit: int = 50):
    """Получает последние N сообщений из БД"""
    conn = await asyncpg.connect(**DB_CONFIG)
    
    print("=" * 80)
    print("🔍 MSGHUB SNIFFER — Чтение сообщений из базы данных")
    print("=" * 80)
    print()
    
    # Получаем сообщения с информацией об отправителе и комнате
    messages = await conn.fetch("""
        SELECT 
            m.id,
            m.content,
            m.encrypted_content,
            m.is_edited,
            m.edited_at,
            m.created_at,
            u.nickname as sender_nickname,
            u.username as sender_username,
            r.name as room_name,
            r.type as room_type
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        JOIN rooms r ON m.room_id = r.id
        ORDER BY m.created_at DESC
        LIMIT $1
    """, limit)
    
    if not messages:
        print("⚠️  Сообщений не найдено")
        await conn.close()
        return
    
    print(f"📨 Найдено сообщений: {len(messages)}\n")
    
    for i, msg in enumerate(messages, 1):
        print(f"{'─' * 80}")
        print(f"📌 Сообщение #{msg['id']}")
        print(f"👤 Отправитель: {msg['sender_nickname']} (@{msg['sender_username']})")
        print(f"💬 Комната: {msg['room_name'] or 'Личка'} ({msg['room_type']})")
        print(f"📅 Время: {msg['created_at'].strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"✏️  Редактировалось: {'Да' if msg['is_edited'] else 'Нет'}")
        print()
        print(f"📝 ТЕКСТ (открытый вид):")
        print(f"   {msg['content']}")
        print()
        print(f"🔐 ЗАШИФРОВАННОЕ (в БД):")
        encrypted_preview = msg['encrypted_content'][:60] + "..." if len(msg['encrypted_content']) > 60 else msg['encrypted_content']
        print(f"   {encrypted_preview}")
        print()
    
    print("=" * 80)
    print("✅ Конец вывода")
    
    await conn.close()


async def sniff_users():
    """Показать всех зарегистрированных пользователей"""
    conn = await asyncpg.connect(**DB_CONFIG)
    
    print("=" * 80)
    print("👥 СПИСОК ПОЛЬЗОВАТЕЛЕЙ")
    print("=" * 80)
    print()
    
    users = await conn.fetch("SELECT id, nickname, username, email, created_at FROM users ORDER BY id")
    
    for user in users:
        print(f"ID: {user['id']} | Ник: {user['nickname']} | Username: @{user['username']} | Email: {user['email'] or 'нет'}")
    
    print()
    await conn.close()


async def sniff_rooms():
    """Показать все комнаты"""
    conn = await asyncpg.connect(**DB_CONFIG)
    
    print("=" * 80)
    print("🏠 СПИСОК КОМНАТ")
    print("=" * 80)
    print()
    
    rooms = await conn.fetch("""
        SELECT r.id, r.name, r.type, r.created_at, 
               COUNT(rm.user_id) as members_count
        FROM rooms r
        LEFT JOIN room_members rm ON r.id = rm.room_id
        GROUP BY r.id
        ORDER BY r.id
    """)
    
    for room in rooms:
        print(f"ID: {room['id']} | Название: {room['name'] or 'Личка'} | Тип: {room['type']} | Участников: {room['members_count']}")
    
    print()
    await conn.close()


def main():
    parser = argparse.ArgumentParser(description="🔍 MsgHub Sniffer — чтение сообщений из БД")
    parser.add_argument("--users", action="store_true", help="Показать пользователей")
    parser.add_argument("--rooms", action="store_true", help="Показать комнаты")
    parser.add_argument("--all", action="store_true", help="Показать всё")
    
    args = parser.parse_args()
    
    if args.all:
        asyncio.run(sniff_users())
        asyncio.run(sniff_rooms())
        asyncio.run(sniff_messages())
    elif args.users:
        asyncio.run(sniff_users())
    elif args.rooms:
        asyncio.run(sniff_rooms())
    else:
        asyncio.run(sniff_messages())


if __name__ == "__main__":
    main()
