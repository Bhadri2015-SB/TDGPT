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


async def authenticate_user(
    db: AsyncSession,
    email: str,
    password: str,
) -> Optional[User]:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalars().first()
    if not user:
        return None
    if not await verify_password(password, user.password_hash):
        return None
    return user


async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalars().first()


async def update_user_password(
    db: AsyncSession,
    email: str,
    new_password: str,
) -> Optional[User]:
    res = await db.execute(select(User).where(User.email == email))
    user = res.scalars().first()
    if not user:
        return "user not found"
    if not user.allow_password_reset:
        raise HTTPException(status_code=400, detail="OTP not verified")

    user.password_hash = await hash_password(new_password)
    user.updated_at = datetime.utcnow()
    user.reset_otp = None
    user.allow_password_reset = False

    try:
        await db.commit()
        await db.refresh(user)
        return user
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")


async def update_user_otp(db: AsyncSession, user_id: str, otp: str) -> Optional[User]:
    res = await db.execute(select(User).where(User.id == user_id))
    user = res.scalars().first()
    if not user:
        return None

    user.reset_otp = otp
    user.updated_at = datetime.utcnow()
    try:
        await db.commit()
        await db.refresh(user)
        return user
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")


async def verify_user_otp(db: AsyncSession, email: str, otp: str) -> bool:
    res = await db.execute(select(User).where(User.email == email))
    user = res.scalars().first()
    if not user:
        return False
    if user.reset_otp == otp:
        user.allow_password_reset = True
        user.updated_at = datetime.utcnow()
        try:
            await db.commit()
            await db.refresh(user)
            return True
        except SQLAlchemyError as e:
            await db.rollback()
            raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")
    return False


async def create_bot_session(db: AsyncSession, session_token: str) -> Optional[str]:
    """
    Create a new bot session record.
    """
    try:
        from app.models.models import BotSession
        
        session_id = str(uuid.uuid4())
        bot_session = BotSession(
            id=session_id,
            session_token=session_token,
            state="ask_name"
        )
        db.add(bot_session)
        await db.commit()
        return session_id
    except SQLAlchemyError as e:
        await db.rollback()
        print(f"Error creating bot session: {e}")
        return None


async def update_bot_session(
    db: AsyncSession,
    session_token: str,
    state: Optional[str] = None,
    collected_name: Optional[str] = None,
    collected_email: Optional[str] = None,
    user_id: Optional[int] = None,
) -> bool:
    """
    Update a bot session record.
    """
    try:
        from app.models.models import BotSession
        
        res = await db.execute(select(BotSession).where(BotSession.session_token == session_token))
        session = res.scalar_one_or_none()
        if not session:
            return False

        if state is not None:
            session.state = state
        if collected_name is not None:
            session.collected_name = collected_name
        if collected_email is not None:
            session.collected_email = collected_email
        if user_id is not None:
            session.user_id = user_id
        
        session.updated_at = datetime.utcnow()
        await db.commit()
        return True
    except SQLAlchemyError as e:
        await db.rollback()
        print(f"Error updating bot session: {e}")
        return False
