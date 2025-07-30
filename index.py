import asyncio
from app.vector_db.pinecone_upsert import retrival

result = asyncio.run(retrival("What is machine learning?", index_name="vv"))
print(result)
