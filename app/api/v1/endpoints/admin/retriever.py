import asyncio
from fastapi import APIRouter, Depends, HTTPException, Form
from pydantic import BaseModel

from app.vector_db.pinecone_upsert import retrival  

router = APIRouter()

@router.post("/query-retriever")
async def query_retriever(
    query: str = Form(..., description="Enter your query"),
    admin_name: str = Form(..., description="Admin name for document context")
):
   
    if not admin_name:
        raise HTTPException(
            status_code=400,
            detail="Admin context required for query retrieval. Provide admin_name."
        )

    
    try:
        response = await retrival(query, admin_name)
        return {"admin_name": admin_name, "query": query, "response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Retriever error: {str(e)}")
