from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.v1.endpoints import file_process, process_initiate, retriever, user_route, auth, chat, admin
from app.db.session import Base, engine

app = FastAPI(title="TDGPT API", description="TroCare Document GPT API", version="1.0.0")

app.include_router(file_process.router, prefix="/upload")
app.include_router(process_initiate.router, prefix="/process")
app.include_router(user_route.router)
app.include_router(auth.router, prefix="/auth")
app.include_router(retriever.router)
app.include_router(chat.router)
app.include_router(admin.router, prefix="/admin")

@app.get("/")
async def root():
    """
    Root endpoint - API status and available endpoints
    """
    return {
        "message": "TDGPT API is running",
        "version": "1.0.0",
        "status": "active",
        "endpoints": {
            "docs": "/docs",
            "redoc": "/redoc",
            "auth": "/auth/token",
            "register": "/register",
            "login": "/login",
            "upload": "/upload/upload/",
            "process": "/process/initiate/",
            "chat": "/chat/",
            "admin": "/admin/"
        }
    }

@app.get("/health")
async def health_check():
    """
    Health check endpoint
    """
    return {"status": "healthy", "message": "API is running properly"}

@app.on_event("startup")
async def startup_event():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

@app.on_event("shutdown")
async def shutdown_event():
    await engine.dispose()
