from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from app.core import config


DATABASE_URL = config.DB_URL  


engine = create_async_engine(DATABASE_URL, echo=True, future=True)


SessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False
)

Base = declarative_base()


async def get_db():
    async with SessionLocal() as db:
        yield db






