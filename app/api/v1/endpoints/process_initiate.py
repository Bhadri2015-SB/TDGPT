import asyncio
from fastapi import APIRouter, Depends, HTTPException, Form
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.models import User
from sqlalchemy.ext.asyncio import AsyncSession
from app.tasks.file_tasks import start_processing
# from app.services.process_owner_files_async import process_and_store_files


router = APIRouter()

@router.post("/initiate-file-process/")
async def trigger_file_processing(user:User = Depends(get_current_user)):
    
    try:
        
        username = user.username
        user_id = user.id

      
        asyncio.create_task(start_processing(username, user_id))

        return {"owner": username, "process_status": "Process initiated"}

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Processing error: " + str(e))
    
# @router.post("/vector-store-process/")
# async def vector_store_process(
#     user: User = Depends(get_current_user),
#     db: AsyncSession = Depends(get_db),
 
# ):
#     """
#     Endpoint to process files and store them in the vector store.
    
#     Args:
#         user (User): The current user.
#         db (AsyncSession): The database session.
#         owner (str): The directory name corresponding to the owner.
#         user_id (str): The user's ID.
    
#     Returns:
#         dict: Results of the file processing and storage.
#     """
#     return await process_and_store_files()


    

    

