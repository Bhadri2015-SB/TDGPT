from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.models import User
from app.core.security import hash_password, verify_password
import random
import string
from app.utils.email_utils import send_email


async def create_user(db: AsyncSession, username: str, email: str, password: str):
    """
    Create a new user after checking if username or email already exists.
    """
    # If a user with this email exists, update the username and return user
    email_res = await db.execute(select(User).where(User.email == email))
    existing_by_email = email_res.scalar_one_or_none()
    if existing_by_email:
        # update display name if different
        if existing_by_email.username != username and username:
            existing_by_email.username = username
            await db.commit()
            await db.refresh(existing_by_email)
        return existing_by_email

    # If username is taken by some other email, append suffix to avoid uniqueness conflict
    uname_check = await db.execute(select(User).where(User.username == username))
    uname_exists = uname_check.scalar_one_or_none()
    if uname_exists:
        username = f"{username}-{''.join(random.choices(string.ascii_lowercase+string.digits, k=4))}"

    hashed_password = await hash_password(password)
    new_user = User(
        username=username,
        email=email,
        password_hash=hashed_password
    )

    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)  
    return new_user



async def authenticate_user(db: AsyncSession, username: str, password: str):
    """
    Authenticate user by verifying password.
    """
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user and await verify_password(password, user.password_hash):
        return user
    return None



async def send_otp_to_email(db: AsyncSession, email: str):
    """
    Generate and send OTP to user's email for password reset.
    """
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        return False

    otp = ''.join(random.choices(string.digits, k=6))
    user.reset_otp = otp
    await db.commit()

    # Send the OTP via email
    await send_email(email, "Your OTP Code", f"Your OTP code is {otp}")
    return True



async def verify_otp_code(db: AsyncSession, email: str, otp: str):
    """
    Verify OTP code for a given email.
    """
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    return user and user.reset_otp == otp



async def reset_user_password(db: AsyncSession, email: str, new_password: str):
    """
    Reset password if OTP is verified.
    """
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        return False

    user.password_hash = await hash_password(new_password)
    user.reset_otp = None 
    await db.commit()
    return True
