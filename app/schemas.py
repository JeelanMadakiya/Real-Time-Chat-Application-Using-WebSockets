from datetime import datetime

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=128)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


class UserResponse(BaseModel):
    id: int
    username: str
    is_online: bool
    last_seen: datetime

    model_config = {"from_attributes": True}


class RoomCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str | None = Field(default=None, max_length=255)


class RoomResponse(BaseModel):
    id: int
    name: str
    description: str | None
    created_by_id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    id: int
    sender_id: int
    recipient_id: int | None
    room_id: int | None
    content: str
    is_read: bool
    created_at: datetime

    model_config = {"from_attributes": True}
