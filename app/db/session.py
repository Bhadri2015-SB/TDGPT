from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

import dotenv, os

# Replace with your MySQL details

dotenv.load_dotenv()

URL_DATABASE = os.getenv("URL_DATABASE")

engine = create_async_engine(URL_DATABASE, echo=True)  

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





