from typing import List, Optional, Union
from datetime import datetime
import uuid

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import get_db
from app.models.models import UploadBatch, User
from app.core.security import hash_password, verify_password


# -------------------- Upload Batch Functions --------------------

async def create_upload_batch(
    user_id: str,
    file_names: List[str],
    total_size: int,
    db: AsyncSession
) -> Optional[UploadBatch]:
    """
    Create a new upload batch record.

    Args:
        db (AsyncSession): Database session.
        user_id (str): User's UUID.
        file_names (List[str]): List of file names uploaded.
        total_size (int): Total size of files in bytes.

    Returns:
        Optional[UploadBatch]: Created batch or None if failed.
    """
    try:
        batch = UploadBatch(
            user_id=user_id,
            file_names=file_names,
            total_files=len(file_names),
            total_size=total_size,
            status="unprocessed",
            upload_time=datetime.utcnow(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(batch)
        await db.commit()
        await db.refresh(batch)
        return batch

    except SQLAlchemyError:
        await db.rollback()
        return None


async def mark_batch_as_processed(
    db: AsyncSession,
    user_id: str,
) -> Optional[UploadBatch]:
    """
    Mark an existing batch as processed.

    Args:
        db (AsyncSession): Database session.
        batch_id (str): Batch UUID.

    Returns:
        Optional[UploadBatch]: Updated batch or None.
    """
    try:
        result = await db.execute(
            select(UploadBatch).where(
                UploadBatch.user_id == user_id,
                UploadBatch.is_deleted == False
            )
        )
        batch = result.scalars().first()

        if not batch:
            return None

        batch.status = "processed"
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