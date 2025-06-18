from fastapi import FastAPI

from app.api.v1.endpoints import file_process, process_initiate, dev, user_route, auth
from app.db.session import Base, engine 

app = FastAPI()

app.include_router(file_process.router, prefix="/api")
app.include_router(process_initiate.router, prefix="/api")
app.include_router(user_route.router)
app.include_router(auth.router) 

@app.on_event("startup")
async def startup_event():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

@app.on_event("shutdown")
async def shutdown_event():
    await engine.dispose()
