from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Float,
)
from sqlalchemy.orm import relationship

from app.db.session import Base

from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.sql import func


def generate_uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    username = Column(String(150), nullable=False, unique=True)
    email = Column(String(255), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship to bot sessions
    bot_sessions = relationship("BotSession", back_populates="user", cascade="all, delete-orphan")


class Admin(Base):
    __tablename__ = "admins"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    admin_name = Column(String(150), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship to upload records
    upload_records = relationship("UploadRecord", back_populates="admin", cascade="all, delete-orphan")


class UploadRecord(Base):
    __tablename__ = "upload_records"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    admin_id = Column(String(36), ForeignKey("admins.id"), nullable=False)

    file_name = Column(String(255), nullable=False)
    file_type = Column(String(50))
    file_size = Column(Integer)
    status = Column(String(50), default="unprocessed")
    message = Column(Text)
    is_deleted = Column(Boolean, default=False)

    upload_time = Column(DateTime, default=datetime.utcnow)
    processed_time = Column(DateTime)
    time_taken_to_process = Column(Float)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship to admin
    admin = relationship("Admin", back_populates="upload_records")


class BotSession(Base):
    __tablename__ = "bot_sessions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    session_token = Column(String(255), unique=True, index=True, nullable=False)
    state = Column(String(50), nullable=False, default="ask_name")

    collected_name = Column(String(150), nullable=True)
    collected_email = Column(String(255), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationship to user
    user = relationship("User", back_populates="bot_sessions")

