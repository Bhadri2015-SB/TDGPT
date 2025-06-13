from fastapi import FastAPI
from app.api.v1.endpoints import file_process, process_initiate, dev, user_route
from app.db.session import Base, engine 
from app.core.logger import app_logger  # ✅ Import the logger


app = FastAPI()
app_logger.info("Initializing FastAPI app...")


app.include_router(file_process.router, prefix="/api")
app_logger.info("Router registered: file_process (/api)")

app.include_router(process_initiate.router, prefix="/api")
app_logger.info("Router registered: process_initiate (/api)")

app.include_router(dev.router, prefix="/api")
app_logger.info("Router registered: dev (/api)")

app.include_router(user_route.router)
app_logger.info("Router registered: user_route (no prefix)")


@app.on_event("startup")
async def startup_event():
    app_logger.info("Startup event triggered.")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        app_logger.info("Database tables created successfully.")
    except Exception as e:
        app_logger.exception(f"Error during DB setup: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    app_logger.info("Shutdown event triggered.")
    try:
        await engine.dispose()
        app_logger.info("Database engine disposed successfully.")
    except Exception as e:
        app_logger.exception(f"Error during DB shutdown: {e}")
