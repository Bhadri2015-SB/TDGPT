# import os
# import pytest
# import pytest_asyncio
# import httpx
# from sqlalchemy.future import select
# from fastapi.testclient import TestClient

# from app.main import app
# from app.db.session import get_db
# from app.models.models import User
# from app.core.security import hash_password

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
from app.main import app

client = TestClient(app)

@pytest.fixture
def mock_user():
    class UserObj:
        id = 1
    return UserObj()

def test_login_success(mock_user):
    with patch('app.api.v1.endpoints.user_route.authenticate_user', new_callable=AsyncMock, return_value=mock_user), \
         patch('app.api.v1.endpoints.user_route.create_access_token', return_value="mocked.token"):
        response = client.post(
            "/login",
            data={
                "email": "testuser@example.com",
                "password": "testpassword"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["access_token"] == "mocked.token"
        assert data["token_type"] == "bearer"
        assert "access_token=mocked.token" in response.headers.get("set-cookie", "")

def test_login_invalid_credentials():
    with patch('app.api.v1.endpoints.user_route.authenticate_user', new_callable=AsyncMock, return_value=None):
        response = client.post(
            "/login",
            data={
                "email": "wrong@example.com",
                "password": "wrongpass"
            }
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid email or password"