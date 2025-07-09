import asyncio
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.security import get_current_user
from app.models.models import User
from app.vector_db.pinecone_upsert import retrival

router = APIRouter()

class QueryRequest(BaseModel):
    query: str

@router.post("/query-retriever")
async def query_retriever(request: QueryRequest, user:User = Depends(get_current_user)):
    """
    Endpoint to retrieve information based on a query.
    """
    try:
        # Call the retrieval function asynchronously
        results = await retrival(request.query, user.username)
        
        if "error" in results:
            raise HTTPException(status_code=500, detail=results["error"])
        
        return {"query": request.query, "results": results}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))