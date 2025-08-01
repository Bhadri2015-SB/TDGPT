

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.db.session import Base, engine


from app.api.v1.endpoints.admin import (
    admin_file_routes, 
    admin_route as admin_routes,  
    retriever as admin_retriever,
    auth as admin_auth,  
)


from app.api.v1.endpoints.user import (
    chat as user_chat,
    user_auth as user_auth,  
)


import dotenv
from pinecone import Pinecone, ServerlessSpec
from app.core import config

dotenv.load_dotenv()


app = FastAPI(
    title="TDGPT API",
    description="TroCare Document GPT API",
    version="2.0.0",
    openapi_tags=[
        {"name": "admin"},
        {"name": "user"},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)




app.include_router(admin_file_routes.router, prefix="/admin", tags=["admin"])
app.include_router(admin_auth.router, prefix="/admin/auth", tags=["admin"])
app.include_router(admin_routes.router, prefix="/admin", tags=["admin"])
app.include_router(admin_retriever.router, prefix="/admin/retriever", tags=["admin"])

app.include_router(user_chat.router, prefix="/user", tags=["user"])
app.include_router(user_auth.router, prefix="/user/auth", tags=["user"])

@app.get("/")
def root():
    return {"status": "ok", "message": "TDGPT API is running"}


@app.on_event("startup")
async def startup_event():
    print(f"[DEBUG] Using DB URL: {config.DB_URL}")
   
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    
    pinecone_api_key = config.PINECONE_API_KEY
    pc = Pinecone(api_key=pinecone_api_key)
    index_name = "maindocs"   

    if index_name not in pc.list_indexes().names():
        pc.create_index(
            name=index_name,
            dimension=384,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1")
        )
        print(f"[Startup] Created Pinecone index: {index_name}")
    else:
        print(f"[Startup] Pinecone index '{index_name}' already exists.")

@app.on_event("shutdown")
async def shutdown_event():
    await engine.dispose()


