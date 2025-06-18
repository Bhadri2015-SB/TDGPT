# import pytest
# from fastapi.testclient import TestClient
# from unittest.mock import AsyncMock, patch
# from app.core.security import get_current_user
# from app.main import app

# import asyncio

# client = TestClient(app)

# @pytest.fixture
# def mock_user():
#     class UserObj:
#         id = 1
#         username = "testuser"
#     return UserObj()

# def override_get_current_user(mock_user):
#     return mock_user

# def test_trigger_file_processing_success(mock_user):
#     app.dependency_overrides = {}
#     app.dependency_overrides[
       
#         get_current_user
#     ] = lambda: mock_user
#     with patch("app.tasks.file_tasks.start_processing", new_callable=AsyncMock):
#         response = client.post("/api/initiate-file-process/")
#         assert response.status_code == 200
#         data = response.json()
#         assert data["owner"] == "testuser"
#         assert data["process_status"] == "Process initiated"
#     app.dependency_overrides = {}


import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch
from app.main import app
from app.core.security import get_current_user

client = TestClient(app)

@pytest.fixture
def mock_user():
    class UserObj:
        id = 1
        username = "testuser"
    return UserObj()

def test_trigger_file_processing_success(mock_user):
    app.dependency_overrides[get_current_user] = lambda: mock_user
    with patch("app.tasks.file_tasks.start_processing", new_callable=AsyncMock):
        response = client.post("/api/initiate-file-process/")
        assert response.status_code == 200
        data = response.json()
        assert data["owner"] == "testuser"
        assert data["process_status"] == "Process initiated"
    app.dependency_overrides = {}

def test_trigger_file_processing_file_not_found(mock_user):
    app.dependency_overrides[get_current_user] = lambda: mock_user
    
    
    def mock_start_processing(*args, **kwargs):
        raise FileNotFoundError("File not found")
    
   
    def mock_create_task(coro):
        mock_start_processing()
    
    with patch("app.tasks.file_tasks.start_processing", side_effect=FileNotFoundError("File not found")), \
         patch("app.api.v1.endpoints.process_initiate.asyncio.create_task", side_effect=mock_create_task):
        response = client.post("/api/initiate-file-process/")
        assert response.status_code == 404
        assert "File not found" in response.json()["detail"]
    app.dependency_overrides = {}

def test_trigger_file_processing_generic_error(mock_user):
    app.dependency_overrides[get_current_user] = lambda: mock_user
    
   
    def mock_start_processing(*args, **kwargs):
        raise Exception("Some error")
    
    
    def mock_create_task(coro):
        mock_start_processing()
    
    with patch("app.tasks.file_tasks.start_processing", side_effect=Exception("Some error")), \
         patch("app.api.v1.endpoints.process_initiate.asyncio.create_task", side_effect=mock_create_task):
        response = client.post("/api/initiate-file-process/")
        assert response.status_code == 500
        assert "Processing error: Some error" in response.json()["detail"]
    app.dependency_overrides = {}