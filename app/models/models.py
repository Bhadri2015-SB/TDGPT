from datetime import date, datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, Text, Float, Boolean, Date
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import relationship, declarative_base
from app.db.session import Base

from datetime import datetime
import uuid


def generate_uuid():
    return str(uuid.uuid4())

class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    username = Column(String(150), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False) 
    reset_otp = Column(String(255), nullable=True)  # For storing OTP
    allow_password_reset = Column(Boolean, default=False)  # Flag to allow password reset 

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    upload_records = relationship("UploadRecord", back_populates="user", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="user", cascade="all, delete-orphan")


class UploadRecord(Base):
    __tablename__ = "upload_records"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    file_name = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)  
    file_size = Column(Integer, nullable=False)  # in bytes
    status = Column(String(50), default="unprocessed", nullable=False)
    message = Column(Text, nullable=True)  # For storing any error messages or additional info
    is_deleted = Column(Boolean, default=False)

    upload_time = Column(DateTime(timezone=True), default=datetime.utcnow)
    processed_time = Column(DateTime(timezone=True), default=None)
    time_taken_to_process = Column(Integer, default=None)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="upload_records")
    documents = relationship("Document", back_populates="upload_record")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=True)  # Optional conversation title
    is_active = Column(Boolean, default=True)
    is_deleted = Column(Boolean, default=False)
    
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    conversation_id = Column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    
    role = Column(String(20), nullable=False)  # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    tokens_used = Column(Integer, nullable=True)
    response_time = Column(Integer, nullable=True)  # in milliseconds
    model_used = Column(String(100), nullable=True)
    context_sources = Column(JSON, nullable=True)
    similarity_scores = Column(JSON, nullable=True)
    is_deleted = Column(Boolean, default=False)
    context_used = Column(Boolean, default=False)  # For assistant messages
    
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="messages")


class Document(Base):
    __tablename__ = "documents"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    upload_record_id = Column(String(36), ForeignKey("upload_records.id", ondelete="SET NULL"), nullable=True)
    
    original_filename = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)
    file_size = Column(Integer, nullable=False)  # File size in bytes
    file_hash = Column(String(64), nullable=True)  # Content hash for deduplication
    
    pinecone_index_name = Column(String(255), nullable=True)  # Index name in Pinecone or any vector DB
    total_chunks = Column(Integer, nullable=True)  # Total number of text chunks created for embeddings
    embedding_model = Column(String(100), nullable=True)  # Embedding model used (e.g., OpenAI-ada, etc.)
    
    processing_status = Column(String(50), nullable=False, default="pending")  # pending | processing | completed | failed
    processing_error = Column(Text, nullable=True)  # Error details if processing fails
    processing_started_at = Column(DateTime(timezone=True), nullable=True)  # Timestamp when processing started
    processing_completed_at = Column(DateTime(timezone=True), nullable=True)  # Timestamp when processing completed
    
    is_public = Column(Boolean, default=False)  # If True, document is shareable publicly
    is_deleted = Column(Boolean, default=False)  # Soft delete flag
    
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="documents")
    upload_record = relationship("UploadRecord", back_populates="documents")
