import asyncio
from fastapi import APIRouter, Depends, HTTPException, Form, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.core.security import get_current_user
from app.models.models import User
from app.schemas.response_model import QueryRequest
from app.vector_db.pinecone_upsert import retrival

router = APIRouter()

@router.post("/query-retriever")
async def query_retriever(
    query: str = Form(..., description="Enter your query"),
    user: User = Depends(get_current_user)
):
    """
    Endpoint to retrieve information based on a query.
    """
    try:
        # Call the retrieval function asynchronously
        results = await retrival(query, user.username)
        
        # Check if results is a dictionary with an error
        if isinstance(results, dict) and "error" in results:
            raise HTTPException(status_code=500, detail=results["error"])
        
        return {"query": query, "results": results}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))