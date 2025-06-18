# import pytest
# from fastapi.testclient import TestClient
# from app.main import app
# import asyncio
# import sys

# if sys.platform.startswith("win"):
#     asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# @pytest.fixture(scope="module")
# def client():
#     with TestClient(app) as c:
#         yield c

# @pytest.fixture
# def test_user_credentials():
#     return {"username": "testuser", "password": "testpass"}

# @pytest.fixture
# def get_token(client, test_user_credentials):
#     def _get_token():
#         response = client.post("/token", data=test_user_credentials)
#         assert response.status_code == 200
#         return response.json()["access_token"]
#     return _get_token



import pytest
from fastapi.testclient import TestClient
from app.main import app
import asyncio
import sys


if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c

@pytest.fixture
def test_user_credentials():
    return {"username": "testuser", "password": "testpass"}

@pytest.fixture
def get_token(client, test_user_credentials):
    def _get_token():
        response = client.post("/token", data=test_user_credentials)
        assert response.status_code == 200
        return response.json()["access_token"]
    return _get_token

@pytest.fixture(autouse=True)
def cleanup_app_state():
    """Clean up FastAPI app state after each test"""
    yield
   
    app.dependency_overrides.clear()

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    if sys.platform.startswith("win"):
        loop = asyncio.ProactorEventLoop()
    else:
        loop = asyncio.new_event_loop()
    
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()

# Mock user fixture for dependency injection testing
@pytest.fixture
def mock_user():
    class UserObj:
        id = 1
        username = "testuser"
        email = "testuser@example.com"
    return UserObj()


@pytest.fixture
def mock_db():
    from unittest.mock import MagicMock
    return MagicMock()


@pytest.fixture
def auth_headers(get_token):
    def _auth_headers():
        token = get_token()
        return {"Authorization": f"Bearer {token}"}
    return _auth_headers