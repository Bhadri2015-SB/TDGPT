from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.models import User
from app.core.security import hash_password, verify_password
import random
import string
from app.utils.email_utils import send_email


async def create_user(db: AsyncSession, username: str, phone_number: str, password: str):
    """
    Create a new user after checking if username or phone_number already exists.
    """

    phone_res = await db.execute(select(User).where(User.phone_number == phone_number))
    existing_by_phone = phone_res.scalar_one_or_none()
    if existing_by_phone:
    
        if existing_by_phone.username != username and username:
            existing_by_phone.username = username
            await db.commit()
            await db.refresh(existing_by_phone)
        return existing_by_phone


    uname_check = await db.execute(select(User).where(User.username == username))
    uname_exists = uname_check.scalar_one_or_none()
    if uname_exists:
        username = f"{username}-{''.join(random.choices(string.ascii_lowercase+string.digits, k=4))}"

    hashed_password = await hash_password(password)
    new_user = User(
        username=username,
        phone_number=phone_number,
        password_hash=hashed_password
    )

    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)  
    return new_user



async def reset_user_password(db: AsyncSession, phone_number: str, new_password: str):
    """
    Reset password if OTP is verified.
    """
    result = await db.execute(select(User).where(User.phone_number == phone_number))
    user = result.scalar_one_or_none()
    if not user:
        return False

    user.password_hash = await hash_password(new_password)
    user.reset_otp = None 
    await db.commit()
    return True
