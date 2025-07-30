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
from sqlalchemy.dialects.mysql import JSON  

from app.db.session import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())



class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    username = Column(String(150), nullable=False, unique=True)
    email = Column(String(255), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)

    reset_otp = Column(String(255), nullable=True)
    allow_password_reset = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    conversations = relationship(
        "Conversation",
        back_populates="user",
        cascade="all, delete-orphan",
    )



class Admin(Base):
    __tablename__ = "admins"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    admin_name = Column(String(150), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)

    reset_otp = Column(String(255), nullable=True)
    allow_password_reset = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    upload_records = relationship("UploadRecord", back_populates="admin", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="admin", cascade="all, delete-orphan")



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

    admin = relationship("Admin", back_populates="upload_records")
    documents = relationship("Document", back_populates="upload_record")



class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    title = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    is_deleted = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)

    role = Column(String(20), nullable=False)  # user|assistant
    content = Column(Text, nullable=False)
    tokens_used = Column(Integer)
    response_time = Column(Integer)  # ms
    model_used = Column(String(100))
    context_sources = Column(JSON)
    similarity_scores = Column(JSON)
    is_deleted = Column(Boolean, default=False)
    context_used = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="messages")



class Document(Base):
    __tablename__ = "documents"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    admin_id = Column(String(36), ForeignKey("admins.id", ondelete="CASCADE"), nullable=False)
    upload_record_id = Column(String(36), ForeignKey("upload_records.id", ondelete="SET NULL"), nullable=True)

    original_filename = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)
    file_size = Column(Integer, nullable=False)
    file_hash = Column(String(64))

    pinecone_index_name = Column(String(255))
    total_chunks = Column(Integer)
    embedding_model = Column(String(100))

    processing_status = Column(String(50), nullable=False, default="pending")
    processing_error = Column(Text)
    processing_started_at = Column(DateTime)
    processing_completed_at = Column(DateTime)

    is_public = Column(Boolean, default=False)
    is_deleted = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    admin = relationship("Admin", back_populates="documents")
    upload_record = relationship("UploadRecord", back_populates="documents")
