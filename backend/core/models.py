from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None


class ChatResponse(BaseModel):
    reply: str
    session_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: Optional[Dict[str, Any]] = None


class ProfileModel(BaseModel):
    id: Optional[int] = None
    name: str
    preferences: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None


class PreferenceModel(BaseModel):
    id: Optional[int] = None
    key: str
    value: str
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TaskModel(BaseModel):
    id: str
    status: str = "pending"
    preset: Optional[str] = None
    progress: int = Field(default=0, ge=0, le=100)
    current_step: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
