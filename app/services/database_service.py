from typing import List, Optional, Union
from datetime import datetime
import uuid

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import get_db
from app.models.models import UploadRecord, User
from app.core.security import hash_password, verify_password


# -------------------- Upload Batch Functions --------------------

async def create_upload_record(
    user_id: str,
    file_name: str,
    file_size: int,
    db: AsyncSession
) -> Optional[UploadRecord]:
    try:
        record = UploadRecord(
            user_id=user_id,
            file_name=file_name,
            file_size=file_size,
            status="unprocessed",
            message="process not initiated",
            upload_time=datetime.utcnow(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        return "record saved successfully"
    except SQLAlchemyError as e:
        await db.rollback()
        print(f"Error saving upload record: {e}")
        return f"Error saving upload record: {e}"



async def mark_file_as_processed(
    db: AsyncSession,
    user_id: str,
    file_name: str,
    status: str,
    message: str,
    time_taken_to_process: int = None,
) -> Optional[UploadRecord]:

    try:
        result = await db.execute(
            select(UploadRecord).where(
                UploadRecord.user_id == user_id,
                UploadRecord.file_name == file_name,
                UploadRecord.is_deleted == False
            )
        )
        batch = result.scalars().first()

        if not batch:
            return None

        batch.status = status
        batch.message = message
        if time_taken_to_process is not None:
            batch.processed_time = datetime.utcnow()
        batch.time_taken_to_process = time_taken_to_process
        batch.updated_at = datetime.utcnow()

        await db.commit()
        await db.refresh(batch)
        return batch

    except SQLAlchemyError:
        await db.rollback()
        return None

# -------------------- User Functions --------------------

async def create_user(
    db: AsyncSession,
    username: str,
    email: str,
    password: str
) -> Union[User, str, None]:
    """
    Create a new user.

    Args:
        db (AsyncSession): DB session.
        username (str): Desired username.
        email (str): Unique email.
        password (str): Plain password.

    Returns:
        Union[User, str, None]: User object, error message, or None.
    """
    try:
        result = await db.execute(
            select(User).where((User.username == username) | (User.email == email))
        )
        existing_user = result.scalars().first()

        if existing_user:
            return "user already exists"

        hashed_pw = await hash_password(password)

        new_user = User(
            username=username,
            email=email,
            password_hash=hashed_pw,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)
        return new_user

    except SQLAlchemyError as e:
        print(f"Error creating user: {e}")
        await db.rollback()
        return None


async def authenticate_user(
    db: AsyncSession,
    email: str,
    password: str
) -> Optional[User]:
    """
    Validate user credentials.

    Args:
        db (AsyncSession): DB session.
        email (str): User email.
        password (str): Plain password.

    Returns:
        Optional[User]: Authenticated user or None.
    """
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalars().first()

    if not user:
        return None

    if not await verify_password(password, user.password_hash):
        return None

    return user