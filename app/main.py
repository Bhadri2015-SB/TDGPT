

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.db.session import Base, engine


from app.api.v1.endpoints.admin import admin_file_routes


from app.api.v1.endpoints.user import bot as user_bot


import dotenv
from pinecone import Pinecone, ServerlessSpec
from app.core import config

from fastapi.staticfiles import StaticFiles

from app.vector_db import upsert_image


dotenv.load_dotenv()


app = FastAPI(
    title="BotChat API",
    description="Document Chat Bot API",
    version="1.0.0",
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

# Mount static file directories for serving images
app.mount("/output/images", StaticFiles(directory=str(config.IMAGE_OUTPUT_DIR)), name="output_images")

app.include_router(admin_file_routes.router, prefix="/admin", tags=["admin"])


app.include_router(user_bot.router, prefix="/user", tags=["user"])

@app.get("/")
def root():
    return {"status": "ok", "message": "BotChat API is running"}


@app.on_event("startup")
async def startup_event():
    print(f"[DEBUG] Using DB URL: {config.DB_URL}")
   
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    
    pinecone_api_key = config.PINECONE_API_KEY
    pc = Pinecone(api_key=pinecone_api_key)
    index_name = config.SHARED_PINECONE_INDEX

    try:
        existing_indexes = pc.list_indexes().names()
        print(f"[Startup] Available Pinecone indexes: {existing_indexes}")
        
        if index_name not in existing_indexes:
            print(f"[Startup] Index '{index_name}' not found. Attempting to create...")
            try:
                pc.create_index(
                    name=index_name,
                    dimension=384,
                    metric="cosine",
                    spec=ServerlessSpec(cloud="aws", region="us-east-1")
                )
                print(f"[Startup] Created Pinecone index: {index_name}")
            except Exception as create_error:
                print(f"[Startup] ⚠️  Could not create index '{index_name}': {create_error}")
                if "max serverless indexes" in str(create_error).lower():
                    print(f"[Startup] 💡 You have 5 indexes (limit reached). Available indexes: {existing_indexes}")
                    print(f"[Startup] 💡 Please either:")
                    print(f"[Startup]    1. Delete unused indexes, OR")
                    print(f"[Startup]    2. Change SHARED_PINECONE_INDEX to an existing index name, OR") 
                    print(f"[Startup]    3. Use namespaces within existing indexes")
                    # Don't crash - continue with available indexes
                else:
                    raise create_error
        else:
            print(f"[Startup] Pinecone index '{index_name}' already exists.")
    except Exception as pc_error:
        print(f"[Startup] ❌ Pinecone connection error: {pc_error}")
        print(f"[Startup] Application will continue but document ingestion may fail.")

@app.on_event("shutdown")
async def shutdown_event():
    await engine.dispose()


