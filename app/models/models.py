from datetime import date, datetime
from sqlalchemy import JSON, Boolean, Integer,String,Date,ForeignKey,DateTime,Column,Text
from sqlalchemy.orm import relationship, declarative_base
from app.db.session import Base

from sqlalchemy import Column, String, DateTime,  ForeignKey, Integer, Text, JSON
from sqlalchemy.orm import relationship
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

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    upload_batches = relationship("UploadBatch", back_populates="user")


class UploadBatch(Base):
    __tablename__ = "upload_batches"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    file_name = Column(String(255), nullable=False)  # list of file names #change
    file_size = Column(Integer, nullable=False)  # in bytes
    status = Column(String(50), default="unprocessed", nullable=False)
    is_deleted = Column(Boolean, default=False)

    upload_time = Column(DateTime(timezone=True), default=datetime.utcnow)
    processed_time = Column(DateTime(timezone=True), default=None)
    time_taken_to_process=Column(Integer, default=None)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="upload_batches")