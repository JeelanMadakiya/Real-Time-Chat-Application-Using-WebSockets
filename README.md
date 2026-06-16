# Real-Time Chat Application Using WebSockets

A scalable real-time chat application built with Python, FastAPI, WebSockets, Redis, and SQLite.

## Features

- User registration and login with JWT authentication
- Real-time private messaging
- Real-time group rooms
- Message history
- Online/offline presence
- Typing indicators
- Read receipts
- Room create, join, leave, and member list APIs
- Redis pub/sub message bus for multiple FastAPI workers
- SQLite persistence for users, rooms, memberships, and messages
- Simple browser UI included

## Project Structure

```text
realtime-chat-app/
  app/
    main.py
    config.py
    database.py
    models.py
    auth.py
    schemas.py
    connection_manager.py
    redis_bus.py
    static/
      index.html
      styles.css
      app.js
  requirements.txt
  .env.example
  README.md
```

## Installation

1. Create a virtual environment:

```bash
python -m venv .venv
```

2. Activate it.

Windows:

```bash
.venv\Scripts\activate
```

macOS/Linux:

```bash
source .venv/bin/activate
```

3. Install all required libraries:

```bash
pip install -r requirements.txt
```

4. Copy environment settings:

```bash
copy .env.example .env
```

On macOS/Linux:

```bash
cp .env.example .env
```

5. Start Redis.

With Docker:

```bash
docker run --name chat-redis -p 6379:6379 redis:7
```

Or use a local Redis installation.

6. Run the app:

```bash
uvicorn app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000
```

## WebSocket Message Format

Connect to:

```text
ws://127.0.0.1:8000/ws?token=YOUR_JWT_TOKEN
```

Send private message:

```json
{
  "type": "private_message",
  "to": "alice",
  "content": "Hello Alice"
}
```

Send group message:

```json
{
  "type": "group_message",
  "room_id": 1,
  "content": "Hello team"
}
```

Typing indicator:

```json
{
  "type": "typing",
  "room_id": 1,
  "is_typing": true
}
```

Read receipt:

```json
{
  "type": "read_receipt",
  "message_id": 10
}
```

## REST API Overview

- `POST /auth/register`
- `POST /auth/login`
- `GET /users`
- `POST /rooms`
- `GET /rooms`
- `POST /rooms/{room_id}/join`
- `POST /rooms/{room_id}/leave`
- `GET /rooms/{room_id}/messages`
- `GET /private/{username}/messages`

## Scaling Notes

Run multiple app workers behind a reverse proxy and keep Redis shared:

```bash
uvicorn app.main:app --workers 4
```

Redis pub/sub broadcasts events between workers, while SQLite stores chat history. For high production traffic, replace SQLite with PostgreSQL and Redis pub/sub with Redis Streams, RabbitMQ, Kafka, or another durable queue.
