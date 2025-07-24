from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

import dotenv, os

from app.core import config

# Replace with your MySQL details

dotenv.load_dotenv()

URL_DATABASE = config.URL_DATABASE

engine = create_async_engine(URL_DATABASE, echo=True)  

def get_engine():
    return engine

SessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False
)

Base = declarative_base()

async def get_db():
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()





