from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.endpoints import file_process, process_initiate, retriever, user_route, auth
from app.db.session import Base, get_engine 

@asynccontextmanager
async def lifespan(app: FastAPI):
    # STARTUP logic
    engine = get_engine()
    app.state.engine = engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield

    # SHUTDOWN logic
    await app.state.engine.dispose()


app = FastAPI(lifespan=lifespan)  # 👈 important!

# Routers
app.include_router(file_process.router, prefix="/api")
app.include_router(process_initiate.router, prefix="/api")
app.include_router(user_route.router)
app.include_router(auth.router)
app.include_router(retriever.router)

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
