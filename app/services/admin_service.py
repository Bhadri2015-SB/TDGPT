from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException
from app.models.models import Admin
from app.core.security import hash_password, verify_password
from datetime import datetime

async def create_admin(db: AsyncSession, admin_name: str, email: str, password: str):
    result = await db.execute(select(Admin).where((Admin.admin_name == admin_name) | (Admin.email == email)))
    existing_admin = result.scalars().first()
    if existing_admin:
        raise HTTPException(status_code=400, detail="Admin already exists")
    hashed_pw = await hash_password(password)
    now = datetime.utcnow()
    admin = Admin(
        admin_name=admin_name,
        email=email,
        password_hash=hashed_pw,
        created_at=now,
        updated_at=now
    )
    db.add(admin)
    await db.commit()
    await db.refresh(admin)
    return admin

async def authenticate_admin(db: AsyncSession, email: str, password: str):
    result = await db.execute(select(Admin).where(Admin.email == email))
    admin = result.scalars().first()
    if not admin:
        return None
    if not await verify_password(password, admin.password_hash):
        return None
    return admin

async def get_admin_by_email(db: AsyncSession, email: str):
    result = await db.execute(select(Admin).where(Admin.email == email))
    return result.scalars().first()
