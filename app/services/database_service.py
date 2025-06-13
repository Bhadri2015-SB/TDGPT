from pathlib import Path
from typing import List, Optional, Union, Dict
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import get_db
from app.models.models import UploadRecord, User
from app.core.security import hash_password, verify_password
from app.core.logger import app_logger  

# -------------------- Upload Record Operations --------------------

async def create_upload_record(
    user_id: str,
    file_name: str,
    file_size: int,
    path: str,
    db: AsyncSession
) -> Union[str, None]:
    file_type = Path(path).parent.name
    now = datetime.utcnow()

    record = UploadRecord(
        user_id=user_id,
        file_name=file_name,
        file_type=file_type,
        file_size=file_size,
        status="unprocessed",
        message="process not initiated",
        upload_time=now,
        created_at=now,
        updated_at=now
    )

    try:
        db.add(record)
        await db.commit()
        app_logger.info(f"Upload record created for user_id={user_id}, file={file_name}")
        return "record saved successfully"
    except SQLAlchemyError as e:
        await db.rollback()
        app_logger.exception(f"Failed to create upload record for user_id={user_id}, file={file_name}: {e}")
        return None


async def mark_file_as_processed(
    db: AsyncSession,
    user_id: str,
    file_name: str,
    status: str,
    message: str,
    time_taken_to_process: Optional[int] = None,
) -> Optional[UploadRecord]:
    try:
        result = await db.execute(
            select(UploadRecord).where(
                UploadRecord.user_id == user_id,
                UploadRecord.file_name == file_name,
                UploadRecord.is_deleted == False
            )
        )
        record = result.scalars().first()

        if not record:
            app_logger.warning(f"No upload record found to update for user_id={user_id}, file={file_name}")
            return None

        record.status = status
        record.message = message
        record.updated_at = datetime.utcnow()
        if time_taken_to_process is not None:
            record.processed_time = datetime.utcnow()
            record.time_taken_to_process = time_taken_to_process

        await db.commit()
        await db.refresh(record)
        app_logger.info(f"Upload record updated for user_id={user_id}, file={file_name}, status={status}")
        return record
    except SQLAlchemyError as e:
        await db.rollback()
        app_logger.exception(f"Error updating upload record for user_id={user_id}, file={file_name}: {e}")
        return None


async def get_file_list(
    user_id: str,
    db: AsyncSession
) -> List[UploadRecord]:
    try:
        result = await db.execute(
            select(UploadRecord).where(
                UploadRecord.user_id == user_id,
                UploadRecord.is_deleted == False
            )
        )
        files = result.scalars().all()
        app_logger.info(f"Fetched {len(files)} files for user_id={user_id}")
        return files
    except SQLAlchemyError as e:
        app_logger.exception(f"Error fetching file list for user_id={user_id}: {e}")
        return []


async def update_db_statuses(
    db: AsyncSession,
    results: List[Dict]
) -> None:
    for result in results:
        await mark_file_as_processed(
            db=db,
            user_id=result["user_id"],
            file_name=result["file_name"],
            status=result["status"],
            message=result["message"],
            time_taken_to_process=result.get("time_taken_to_process")
        )

# -------------------- User Management --------------------

async def create_user(
    db: AsyncSession,
    username: str,
    email: str,
    password: str
) -> Union[User, str, None]:
    try:
        result = await db.execute(
            select(User).where((User.username == username) | (User.email == email))
        )
        existing_user = result.scalars().first()

        if existing_user:
            app_logger.warning(f"User already exists: {email}")
            return "user already exists"

        hashed_pw = await hash_password(password)
        now = datetime.utcnow()

        user = User(
            username=username,
            email=email,
            password_hash=hashed_pw,
            created_at=now,
            updated_at=now
        )

        db.add(user)
        await db.commit()
        await db.refresh(user)
        app_logger.info(f"User created: {email}")
        return user

    except SQLAlchemyError as e:
        await db.rollback()
        app_logger.exception(f"Error creating user {email}: {e}")
        return None


async def authenticate_user(
    db: AsyncSession,
    email: str,
    password: str
) -> Optional[User]:
    try:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalars().first()

        if not user:
            app_logger.warning(f"Authentication failed: User not found - {email}")
            return None

        if not await verify_password(password, user.password_hash):
            app_logger.warning(f"Authentication failed: Incorrect password - {email}")
            return None

        app_logger.info(f"User authenticated: {email}")
        return user
    except SQLAlchemyError as e:
        app_logger.exception(f"Error during authentication for {email}: {e}")
        return None
