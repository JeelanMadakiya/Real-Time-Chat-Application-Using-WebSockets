from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session
from typing import Optional

from app.auth import (
    create_access_token,
    get_current_user,
    get_user_from_token,
    hash_password,
    verify_password,
)
from app.config import get_settings
from app.connection_manager import manager
from app.database import SessionLocal, get_db, init_db
from app.models import Message, Room, RoomMember, User
from app.redis_bus import redis_bus
from app.schemas import (
    LoginRequest,
    MessageResponse,
    RegisterRequest,
    RoomCreate,
    RoomResponse,
    TokenResponse,
    UserResponse,
)


settings = get_settings()
app = FastAPI(title=settings.app_name)

origins = ["*"] if settings.cors_origins == "*" else [x.strip() for x in settings.cors_origins.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.on_event("startup")
async def startup() -> None:
    init_db()
    await redis_bus.connect()
    redis_bus.listener_task = None
    if redis_bus.available:
        import asyncio

        redis_bus.listener_task = asyncio.create_task(redis_bus.listen(deliver_event))


@app.on_event("shutdown")
async def shutdown() -> None:
    await redis_bus.close()


@app.get("/")
def index() -> FileResponse:
    return FileResponse("app/static/index.html")


@app.post("/auth/register", response_model=TokenResponse)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    existing = db.query(User).filter(User.username == payload.username).first()
    if existing:
        raise HTTPException(status_code=409, detail="Username already exists")

    user = User(username=payload.username, password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    token = create_access_token(user.username)
    return TokenResponse(access_token=token, username=user.username)


@app.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_access_token(user.username)
    return TokenResponse(access_token=token, username=user.username)


@app.get("/users", response_model=list[UserResponse])
def users(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[User]:
    return db.query(User).filter(User.id != current_user.id).order_by(User.username).all()


@app.post("/rooms", response_model=RoomResponse)
def create_room(
    payload: RoomCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Room:
    existing = db.query(Room).filter(Room.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Room name already exists")
    room = Room(name=payload.name, description=payload.description, created_by_id=current_user.id)
    db.add(room)
    db.flush()
    db.add(RoomMember(room_id=room.id, user_id=current_user.id))
    db.commit()
    db.refresh(room)
    return room


@app.get("/rooms", response_model=list[RoomResponse])
def list_rooms(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Room]:
    return db.query(Room).order_by(Room.name).all()


@app.post("/rooms/{room_id}/join")
def join_room(room_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    existing = db.query(RoomMember).filter_by(room_id=room_id, user_id=current_user.id).first()
    if not existing:
        db.add(RoomMember(room_id=room_id, user_id=current_user.id))
        db.commit()
    return {"status": "joined", "room_id": room_id}


@app.post("/rooms/{room_id}/leave")
def leave_room(room_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    membership = db.query(RoomMember).filter_by(room_id=room_id, user_id=current_user.id).first()
    if membership:
        db.delete(membership)
        db.commit()
    return {"status": "left", "room_id": room_id}


@app.get("/rooms/{room_id}/messages")
def room_messages(
    room_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    ensure_room_member(db, room_id, current_user.id)
    messages = db.query(Message).filter(Message.room_id == room_id).order_by(Message.created_at.desc()).limit(50).all()[::-1]
    return [serialize_history_message(db, message) for message in messages]


@app.get("/private/{username}/messages")
def private_messages(
    username: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    other = db.query(User).filter(User.username == username).first()
    if not other:
        raise HTTPException(status_code=404, detail="User not found")
    messages = (
        db.query(Message)
        .filter(
            or_(
                and_(Message.sender_id == current_user.id, Message.recipient_id == other.id),
                and_(Message.sender_id == other.id, Message.recipient_id == current_user.id),
            )
        )
        .order_by(Message.created_at.desc())
        .limit(50)
        .all()[::-1]
    )
    return [serialize_history_message(db, message) for message in messages]


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str) -> None:
    db = SessionLocal()
    user = None
    try:
        user = get_user_from_token(token, db)
        await manager.connect(user.username, websocket)
        set_user_online(db, user, True)
        await publish_or_deliver({"type": "presence", "username": user.username, "is_online": True})

        while True:
            payload = await websocket.receive_json()
            event_type = payload.get("type")
            if event_type == "private_message":
                await handle_private_message(db, user, payload)
            elif event_type == "group_message":
                await handle_group_message(db, user, payload)
            elif event_type == "typing":
                await handle_typing(db, user, payload)
            elif event_type == "read_receipt":
                await handle_read_receipt(db, user, payload)
            else:
                await websocket.send_json({"type": "error", "message": "Unknown event type"})
    except WebSocketDisconnect:
        pass
    except HTTPException:
        await websocket.close(code=1008)
    finally:
        if user is not None:
            manager.disconnect(user.username, websocket)
            set_user_online(db, user, manager.is_online(user.username))
            if not manager.is_online(user.username):
                await publish_or_deliver({"type": "presence", "username": user.username, "is_online": False})
        db.close()


async def handle_private_message(db: Session, sender: User, payload: dict) -> None:
    recipient = db.query(User).filter(User.username == payload.get("to")).first()
    content = str(payload.get("content", "")).strip()
    if not recipient or not content:
        await manager.send_to_user(sender.username, {"type": "error", "message": "Invalid recipient or content"})
        return
    message = Message(sender_id=sender.id, recipient_id=recipient.id, content=content)
    db.add(message)
    db.commit()
    db.refresh(message)
    event = serialize_message("private_message", message, sender.username, recipient.username)
    await publish_or_deliver(event)


async def handle_group_message(db: Session, sender: User, payload: dict) -> None:
    room_id = int(payload.get("room_id"))
    ensure_room_member(db, room_id, sender.id)
    content = str(payload.get("content", "")).strip()
    if not content:
        return
    message = Message(sender_id=sender.id, room_id=room_id, content=content)
    db.add(message)
    db.commit()
    db.refresh(message)
    members = room_usernames(db, room_id)
    event = serialize_message("group_message", message, sender.username, None)
    event["members"] = members
    await publish_or_deliver(event)


async def handle_typing(db: Session, sender: User, payload: dict) -> None:
    event = {
        "type": "typing",
        "from": sender.username,
        "room_id": payload.get("room_id"),
        "to": payload.get("to"),
        "is_typing": bool(payload.get("is_typing")),
    }
    if event["room_id"]:
        event["members"] = room_usernames(db, int(event["room_id"]))
    await publish_or_deliver(event)


async def handle_read_receipt(db: Session, reader: User, payload: dict) -> None:
    message = db.query(Message).filter(Message.id == payload.get("message_id")).first()
    if not message:
        return
    if message.recipient_id == reader.id:
        message.is_read = True
        db.commit()
        sender = db.query(User).filter(User.id == message.sender_id).first()
        if sender:
            await publish_or_deliver({"type": "read_receipt", "message_id": message.id, "to": sender.username})


async def publish_or_deliver(event: dict) -> None:
    if redis_bus.available:
        await redis_bus.publish(event)
    else:
        await deliver_event(event)


async def deliver_event(event: dict) -> None:
    event_type = event.get("type")
    if event_type == "private_message":
        await manager.broadcast_users([event["from"], event["to"]], event)
    elif event_type == "group_message":
        await manager.broadcast_users(event.get("members", []), event)
    elif event_type == "typing":
        if event.get("room_id"):
            await manager.broadcast_users(event.get("members", []), event)
        elif event.get("to"):
            await manager.send_to_user(event["to"], event)
    elif event_type == "read_receipt":
        await manager.send_to_user(event["to"], event)
    elif event_type == "presence":
        await manager.broadcast_users(list(manager.active_connections.keys()), event)


def serialize_message(
    event_type: str,
    message: Message,
    sender_name: str,
    recipient_name: Optional[str],
) -> dict:
    return {
        "type": event_type,
        "id": message.id,
        "from": sender_name,
        "to": recipient_name,
        "room_id": message.room_id,
        "content": message.content,
        "is_read": message.is_read,
        "created_at": message.created_at.isoformat(),
    }


def serialize_history_message(db: Session, message: Message) -> dict:
    sender = db.query(User).filter(User.id == message.sender_id).first()
    recipient = db.query(User).filter(User.id == message.recipient_id).first() if message.recipient_id else None
    return {
        "id": message.id,
        "from": sender.username if sender else "unknown",
        "to": recipient.username if recipient else None,
        "sender_id": message.sender_id,
        "recipient_id": message.recipient_id,
        "room_id": message.room_id,
        "content": message.content,
        "is_read": message.is_read,
        "created_at": message.created_at.isoformat(),
    }


def ensure_room_member(db: Session, room_id: int, user_id: int) -> None:
    membership = db.query(RoomMember).filter_by(room_id=room_id, user_id=user_id).first()
    if not membership:
        raise HTTPException(status_code=403, detail="Join this room before using it")


def room_usernames(db: Session, room_id: int) -> list[str]:
    return [
        row.username
        for row in db.query(User.username).join(RoomMember, RoomMember.user_id == User.id).filter(RoomMember.room_id == room_id)
    ]


def set_user_online(db: Session, user: User, is_online: bool) -> None:
    user.is_online = is_online
    user.last_seen = datetime.utcnow()
    db.commit()
