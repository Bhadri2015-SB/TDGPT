"""
Database operations shared across admin + user flows.

Admin Upload Lifecycle:
- create_upload_record()
- make_processing()
- update_db_statuses()  <-- called after extraction & embedding phases
- mark_file_as_processed()

Document Lifecycle:
- create_document_record()
- update_document_processing_status()
- create_document_records_for_existing_uploads()  (migration helper)

User Auth utilities remain (create_user, authenticate_user, etc.).

NOTE: Many functions previously used user_id; all admin upload functions now use admin_id.
"""

import hashlib
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Admin, UploadRecord, User
from app.core.security import hash_password, verify_password



async def create_upload_record(
    admin_id: str,
    file_name: str,
    file_size: int,
    path: str,
    db: AsyncSession,
) -> Union[str, None]:
    file_type = os.path.basename(os.path.dirname(path))  # category folder
    now = datetime.utcnow()

    record = UploadRecord(
        admin_id=admin_id,
        file_name=file_name,
        file_type=file_type,
        file_size=file_size,
        status="unprocessed",
        message="process not initiated",
        upload_time=now,
        created_at=now,
        updated_at=now,
    )
    try:
        db.add(record)
        await db.commit()
        return "record saved successfully"
    except SQLAlchemyError:
        await db.rollback()
        return None


async def make_processing(db: AsyncSession, admin_id: str):
    """
    Flip all unprocessed UploadRecords(admin_id) -> processing.
    """
    try:
        result = await db.execute(
            select(UploadRecord).where(
                UploadRecord.admin_id == admin_id,
                UploadRecord.status == "unprocessed",
                UploadRecord.is_deleted == False,
            )
        )
        records = result.scalars().all()
        if not records:
            return "no unprocessed files found"

        now = datetime.utcnow()
        for record in records:
            record.status = "processing"
            record.message = "process initiated"
            record.updated_at = now

        await db.commit()
        return "processing started for unprocessed files"
    except SQLAlchemyError as e:
        await db.rollback()
        return e


async def mark_file_as_processed(
    db: AsyncSession,
    admin_id: str,
    file_name: str,
    status: str,
    message: str,
    time_taken_to_process: Optional[int] = None,
) -> Optional[UploadRecord]:
    """
    Update UploadRecord row after extraction/embedding.
    """
    try:
        result = await db.execute(
            select(UploadRecord).where(
                UploadRecord.admin_id == admin_id,
                UploadRecord.file_name == file_name,
                UploadRecord.is_deleted == False,
            )
        )
        record = result.scalars().first()
        if not record:
            return None

        record.status = status
        record.message = message
        record.updated_at = datetime.utcnow()
        if time_taken_to_process is not None:
            record.processed_time = datetime.utcnow()
            record.time_taken_to_process = time_taken_to_process

        await db.commit()
        await db.refresh(record)
        return record
    except SQLAlchemyError as e:
        await db.rollback()
        return e


async def get_file_list(admin_id: str, db: AsyncSession) -> List[UploadRecord]:
    """
    All non-deleted UploadRecords for admin.
    """
    try:
        result = await db.execute(
            select(UploadRecord).where(
                UploadRecord.admin_id == admin_id,
                UploadRecord.is_deleted == False,
            )
        )
        return result.scalars().all()
    except SQLAlchemyError:
        return []


async def is_existing_file(db: AsyncSession, admin_id: str, file_name: str) -> bool:
    try:
        result = await db.execute(
            select(UploadRecord).where(
                UploadRecord.admin_id == admin_id,
                UploadRecord.file_name == file_name,
                UploadRecord.is_deleted == False,
            )
        )
        return result.scalars().first() is not None
    except SQLAlchemyError:
        return False


async def update_db_statuses(
    db: AsyncSession,
    results: List[Dict[str, Any]],
    default_admin_id: Optional[str] = None,
) -> None:
    """
    Batch update UploadRecord statuses after extraction/embedding.
    Accepts dicts that may contain legacy 'user_id' or current 'admin_id'.
    """
    for result in results:
        if not isinstance(result, dict):
            continue

        admin_id = result.get("admin_id") or result.get("user_id") or default_admin_id
        if not admin_id:
            # Skip if we cannot resolve owner
            continue

        await mark_file_as_processed(
            db=db,
            admin_id=admin_id,
            file_name=result.get("file_name", ""),
            status=result.get("status", "unknown"),
            message=result.get("message", ""),
            time_taken_to_process=result.get("time_taken_to_process"),
        )



async def create_user(
    db: AsyncSession,
    username: str,
    email: str,
    password: str,
) -> Union[User, str, None]:
    try:
        result = await db.execute(
            select(User).where((User.username == username) | (User.email == email))
        )
        existing_user = result.scalars().first()
        if existing_user:
            raise HTTPException(status_code=400, detail="User already exists")

        hashed_pw = await hash_password(password)
        now = datetime.utcnow()
        user = User(
            username=username,
            email=email,
            password_hash=hashed_pw,
            created_at=now,
            updated_at=now,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")


async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalars().first()
