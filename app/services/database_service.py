from pathlib import Path
from typing import List, Optional, Union, Dict
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import get_db
from app.models.models import UploadRecord, User
from app.core.security import hash_password, verify_password

# -------------------- Upload Record Operations --------------------

async def create_upload_record(
    user_id: str,
    file_name: str,
    file_size: int,
    path: str,
    db: AsyncSession
) -> Union[str, None]:
    """
    Create a new upload record in the database.

    Args:
        user_id (str): User ID.
        file_name (str): Name of the uploaded file.
        file_size (int): Size of the file in bytes.
        path (str): File storage path.
        db (AsyncSession): Async DB session.

    Returns:
        Union[str, None]: Success message or None on error.
    """
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
        return "record saved successfully"
    except SQLAlchemyError:
        await db.rollback()
        return None
    
async def make_processing(
    db: AsyncSession,
    user_id: str
    ):

    try:
        result = await db.execute(
            select(UploadRecord).where(
                UploadRecord.user_id == user_id,
                UploadRecord.status == "unprocessed",
                UploadRecord.is_deleted == False
            )
        )
        records = result.scalars().all()

        if not records:
            return "no unprocessed files found"

        for record in records:
            record.status = "processing"
            record.message = "process initiated"
            record.updated_at = datetime.utcnow()

        await db.commit()
        return "processing started for unprocessed files"
    except SQLAlchemyError as e:
        await db.rollback()
        return e


async def mark_file_as_processed(
    db: AsyncSession,
    user_id: str,
    file_name: str,
    status: str,
    message: str,
    time_taken_to_process: Optional[int] = None,
) -> Optional[UploadRecord]:
    """
    Update status of a processed file.

    Args:
        db (AsyncSession): Database session.
        user_id (str): ID of the user.
        file_name (str): Name of the processed file.
        status (str): New processing status.
        message (str): Processing result message.
        time_taken_to_process (Optional[int]): Time taken in seconds.

    Returns:
        Optional[UploadRecord]: Updated record or None if not found.
    """
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


async def get_file_list(
    user_id: str,
    db: AsyncSession
) -> List[UploadRecord]:
    """
    Get all non-deleted upload records for a user.

    Args:
        user_id (str): User ID.
        db (AsyncSession): DB session.

    Returns:
        List[UploadRecord]: Upload records list.
    """
    try:
        result = await db.execute(
            select(UploadRecord).where(
                UploadRecord.user_id == user_id,
                UploadRecord.is_deleted == False
            )
        )
        return result.scalars().all()
    except SQLAlchemyError:
        return []
    
async def is_existing_file(
    db: AsyncSession,
    user_id: str,
    file_name: str) -> bool:
    """Check if a file already exists for a user."""
    try:
        result = await db.execute(
            select(UploadRecord).where(
                UploadRecord.user_id == user_id,
                UploadRecord.file_name == file_name,
                UploadRecord.is_deleted == False
            )
        )
        return result.scalars().first() is not None
    except SQLAlchemyError:
        return False


async def update_db_statuses(
    db: AsyncSession,
    results: List[Dict]
) -> None:
    """
    Batch update upload record statuses after processing.

    Args:
        db (AsyncSession): DB session.
        results (List[Dict]): Each dict must contain user_id, file_name, status, message, and optional time_taken_to_process.
    """
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
    """
    Create a new user account.

    Args:
        db (AsyncSession): DB session.
        username (str): Username.
        email (str): Email (unique).
        password (str): Plaintext password.

    Returns:
        Union[User, str, None]: Created user, error message if exists, or None on DB error.
    """
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
            updated_at=now
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
    password: str
) -> Optional[User]:
    """
    Authenticate user using email and password.

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

async def get_user_by_email(
    db: AsyncSession,
    email: str
) -> Optional[User]:
    """
    Get user by email.

    Args:
        db (AsyncSession): DB session.
        email (str): User email.

    Returns:
        Optional[User]: User object or None if not found.
    """
    result = await db.execute(select(User).where(User.email == email))
    return result.scalars().first()

async def update_user_password(
    db: AsyncSession,
    email: str,
    new_password: str
) -> Optional[User]:
    """
    Update user's password.

    Args:
        db (AsyncSession): DB session.
        user_id (str): User ID.
        new_password (str): New plaintext password.

    Returns:
        Optional[User]: Updated user object or None if not found.
    """
    user = await db.execute(
        select(User).where(User.email == email)
    )
    
    user = user.scalars().first()

    if not user:
        return "user not found"

    if not user.allow_password_reset:
        raise HTTPException(status_code=400, detail="OTP not verified")

    user.password_hash = await hash_password(new_password)
    user.updated_at = datetime.utcnow()
    user.reset_otp = None  # Clear OTP after password reset
    user.allow_password_reset = False  # Reset the flag after password reset
    try:
        await db.commit()
        await db.refresh(user)
        return user
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")
    
async def update_user_otp(
    db: AsyncSession,
    user_id: str,
    otp: str
) -> Optional[User]:
    """
    Update user's OTP.

    Args:
        db (AsyncSession): DB session.
        user_id (str): User ID.
        otp (str): New OTP.

    Returns:
        Optional[User]: Updated user object or None if not found.
    """
    user = await db.execute(
        select(User).where(User.id == user_id)
    )
    # print(user)
    user = user.scalars().first()
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
    
async def verify_user_otp(
    db: AsyncSession,
    email: str,
    otp: str
) -> bool:
    """
    Verify user's OTP.

    Args:
        db (AsyncSession): DB session.
        user_id (str): User ID.
        otp (str): OTP to verify.

    Returns:
        bool: True if OTP matches, False otherwise.
    """
    user = await db.execute(
        select(User).where(User.email == email)
    )

    user = user.scalars().first()
    
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