import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock
from io import BytesIO
from app.main import app
from app.core.security import get_current_user
from app.db.session import get_db

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def mock_user():
    user = MagicMock()
    user.id = 1
    user.username = "testuser"
    return user

@pytest.fixture
def mock_db():
    return AsyncMock()

@pytest.fixture(autouse=True)
def clean_overrides():
    yield 
    app.dependency_overrides.clear()

def test_upload_files_success(client, mock_user, mock_db):
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("app.api.v1.endpoints.file_process.save_file", new_callable=AsyncMock) as mock_save, \
         patch("app.api.v1.endpoints.file_process.get_file_size", new_callable=AsyncMock) as mock_size, \
         patch("app.api.v1.endpoints.file_process.create_upload_record", new_callable=AsyncMock) as mock_record:

        mock_save.return_value = "/uploads/testuser/test_file.txt"
        mock_size.return_value = 1024
        mock_record.return_value = "success"

        test_file = ("test_file.txt", BytesIO(b"test content"), "text/plain")
        response = client.post("/api/upload/", files={"files": test_file})

        assert response.status_code == 200
        data = response.json()
        assert data["owner"] == "testuser"
        assert len(data["saved_files"]) == 1
        assert len(data["records"]) == 1
        assert data["records"][0]["file_name"] == "test_file.txt"
        assert data["records"][0]["file_size"] == 1024
        assert data["records"][0]["upload_status"] == "success"

def test_upload_multiple_files_success(client, mock_user, mock_db):
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("app.api.v1.endpoints.file_process.save_file", new_callable=AsyncMock) as mock_save, \
         patch("app.api.v1.endpoints.file_process.get_file_size", new_callable=AsyncMock) as mock_size, \
         patch("app.api.v1.endpoints.file_process.create_upload_record", new_callable=AsyncMock) as mock_record:

        mock_save.side_effect = ["/uploads/testuser/file1.txt", "/uploads/testuser/file2.txt"]
        mock_size.side_effect = [1024, 2048]
        mock_record.side_effect = ["success", "success"]

        files = [
            ("files", ("file1.txt", BytesIO(b"content1"), "text/plain")),
            ("files", ("file2.txt", BytesIO(b"content2"), "text/plain"))
        ]
        response = client.post("/api/upload/", files=files)

        assert response.status_code == 200
        data = response.json()
        assert data["owner"] == "testuser"
        assert len(data["saved_files"]) == 2
        assert len(data["records"]) == 2
        assert data["records"][0]["file_name"] == "file1.txt"
        assert data["records"][1]["file_name"] == "file2.txt"

def test_upload_files_save_error(client, mock_user, mock_db):
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("app.api.v1.endpoints.file_process.save_file", new_callable=AsyncMock) as mock_save, \
         patch("app.api.v1.endpoints.file_process.get_file_size", new_callable=AsyncMock) as mock_size, \
         patch("app.api.v1.endpoints.file_process.create_upload_record", new_callable=AsyncMock) as mock_record:

        mock_save.side_effect = Exception("Save error")
        test_file = ("test_file.txt", BytesIO(b"test content"), "text/plain")

        response = client.post("/api/upload/", files={"files": test_file})
        assert response.status_code == 500

def test_upload_files_database_error(client, mock_user, mock_db):
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("app.api.v1.endpoints.file_process.save_file", new_callable=AsyncMock) as mock_save, \
         patch("app.api.v1.endpoints.file_process.get_file_size", new_callable=AsyncMock) as mock_size, \
         patch("app.api.v1.endpoints.file_process.create_upload_record", new_callable=AsyncMock) as mock_record:

        mock_save.return_value = "/uploads/testuser/test_file.txt"
        mock_size.return_value = 1024
        mock_record.side_effect = Exception("Database error")

        test_file = ("test_file.txt", BytesIO(b"test content"), "text/plain")
        response = client.post("/api/upload/", files={"files": test_file})
        assert response.status_code == 500

def test_upload_files_no_files(client, mock_user, mock_db):
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    response = client.post("/api/upload/")
    assert response.status_code == 422

def test_upload_files_unauthorized(client):
    test_file = ("test_file.txt", BytesIO(b"test content"), "text/plain")
    response = client.post("/api/upload/", files={"files": test_file})
    assert response.status_code == 401

def test_list_files_success(client, mock_user, mock_db):
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    mock_file_list = [
        {"id": 1, "file_name": "file1.txt", "file_size": 1024, "uploaded_at": "2023-01-01T00:00:00"},
        {"id": 2, "file_name": "file2.txt", "file_size": 2048, "uploaded_at": "2023-01-02T00:00:00"}
    ]

    with patch("app.api.v1.endpoints.file_process.get_file_list", new_callable=AsyncMock) as mock_get_files:
        mock_get_files.return_value = mock_file_list

        response = client.get("/api/files-status/")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["file_name"] == "file1.txt"
        assert data[1]["file_name"] == "file2.txt"


def test_list_files_empty(client, mock_user, mock_db):
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("app.api.v1.endpoints.file_process.get_file_list", new_callable=AsyncMock) as mock_get_files:
        mock_get_files.return_value = []

        response = client.get("/api/files-status/")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 0

def test_list_files_database_error(client, mock_user, mock_db):
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("app.api.v1.endpoints.file_process.get_file_list", new_callable=AsyncMock) as mock_get_files:
        mock_get_files.side_effect = Exception("Database error")

        response = client.get("/api/files-status/")
        assert response.status_code == 500
        data = response.json()
        assert "Database error" in data["detail"]

def test_list_files_unauthorized(client):
    response = client.get("/api/files-status/")
    assert response.status_code == 401

def test_upload_different_file_types(client, mock_user, mock_db):
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("app.api.v1.endpoints.file_process.save_file", new_callable=AsyncMock) as mock_save, \
         patch("app.api.v1.endpoints.file_process.get_file_size", new_callable=AsyncMock) as mock_size, \
         patch("app.api.v1.endpoints.file_process.create_upload_record", new_callable=AsyncMock) as mock_record:

        mock_save.return_value = "/uploads/testuser/test.pdf"
        mock_size.return_value = 2048
        mock_record.return_value = "success"

        pdf_file = ("test.pdf", BytesIO(b"PDF content"), "application/pdf")
        response = client.post("/api/upload/", files={"files": pdf_file})
        assert response.status_code == 200
        data = response.json()
        assert data["records"][0]["file_name"] == "test.pdf"

def test_upload_large_file(client, mock_user, mock_db):
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("app.api.v1.endpoints.file_process.save_file", new_callable=AsyncMock) as mock_save, \
         patch("app.api.v1.endpoints.file_process.get_file_size", new_callable=AsyncMock) as mock_size, \
         patch("app.api.v1.endpoints.file_process.create_upload_record", new_callable=AsyncMock) as mock_record:

        mock_save.return_value = "/uploads/testuser/large.txt"
        mock_size.return_value = 10485760
        mock_record.return_value = "success"

        large_content = b"x" * 1024
        large_file = ("large.txt", BytesIO(large_content), "text/plain")
        response = client.post("/api/upload/", files={"files": large_file})
        assert response.status_code == 200
        data = response.json()
        assert data["records"][0]["file_size"] == 10485760

def test_upload_empty_file(client, mock_user, mock_db):
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("app.api.v1.endpoints.file_process.save_file", new_callable=AsyncMock) as mock_save, \
         patch("app.api.v1.endpoints.file_process.get_file_size", new_callable=AsyncMock) as mock_size, \
         patch("app.api.v1.endpoints.file_process.create_upload_record", new_callable=AsyncMock) as mock_record:

        mock_save.return_value = "/uploads/testuser/empty.txt"
        mock_size.return_value = 0
        mock_record.return_value = "success"

        empty_file = ("empty.txt", BytesIO(b""), "text/plain")
        response = client.post("/api/upload/", files={"files": empty_file})
        assert response.status_code == 200
        data = response.json()
        assert data["records"][0]["file_size"] == 0

def test_upload_with_special_characters_filename(client, mock_user, mock_db):
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("app.api.v1.endpoints.file_process.save_file", new_callable=AsyncMock) as mock_save, \
         patch("app.api.v1.endpoints.file_process.get_file_size", new_callable=AsyncMock) as mock_size, \
         patch("app.api.v1.endpoints.file_process.create_upload_record", new_callable=AsyncMock) as mock_record:

        mock_save.return_value = "/uploads/testuser/special-file_name.txt"
        mock_size.return_value = 1024
        mock_record.return_value = "success"

        special_file = ("special-file_name.txt", BytesIO(b"content"), "text/plain")
        response = client.post("/api/upload/", files={"files": special_file})
        assert response.status_code == 200
        data = response.json()
        assert data["records"][0]["file_name"] == "special-file_name.txt"

def test_upload_file_with_unicode_name(client, mock_user, mock_db):
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("app.api.v1.endpoints.file_process.save_file", new_callable=AsyncMock) as mock_save, \
         patch("app.api.v1.endpoints.file_process.get_file_size", new_callable=AsyncMock) as mock_size, \
         patch("app.api.v1.endpoints.file_process.create_upload_record", new_callable=AsyncMock) as mock_record:

        mock_save.return_value = "/uploads/testuser/unicode_file.txt"
        mock_size.return_value = 512
        mock_record.return_value = "success"

        unicode_file = ("файл.txt", BytesIO(b"unicode content"), "text/plain")
        response = client.post("/api/upload/", files={"files": unicode_file})
        assert response.status_code == 200
        data = response.json()
        assert data["records"][0]["file_name"] == "файл.txt"

def test_upload_file_missing_content_type(client, mock_user, mock_db):
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("app.api.v1.endpoints.file_process.save_file", new_callable=AsyncMock) as mock_save, \
         patch("app.api.v1.endpoints.file_process.get_file_size", new_callable=AsyncMock) as mock_size, \
         patch("app.api.v1.endpoints.file_process.create_upload_record", new_callable=AsyncMock) as mock_record:

        mock_save.return_value = "/uploads/testuser/no_type.txt"
        mock_size.return_value = 256
        mock_record.return_value = "success"

        file_without_type = ("no_type.txt", BytesIO(b"content"), "application/octet-stream")
        response = client.post("/api/upload/", files={"files": file_without_type})
        assert response.status_code == 200
        data = response.json()
        assert data["records"][0]["file_name"] == "no_type.txt"

def test_list_files_with_complex_data(client, mock_user, mock_db):
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db

    mock_file_list = [
        {
            "id": 1, 
            "file_name": "document.pdf", 
            "file_size": 5242880,
            "uploaded_at": "2023-12-01T10:30:00",
            "file_type": "application/pdf"
        },
        {
            "id": 2, 
            "file_name": "image.jpg", 
            "file_size": 1048576,
            "uploaded_at": "2023-12-02T14:15:00",
            "file_type": "image/jpeg"
        }
    ]

    with patch("app.api.v1.endpoints.file_process.get_file_list", new_callable=AsyncMock) as mock_get_files:
        mock_get_files.return_value = mock_file_list

        response = client.get("/api/files-status/")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["file_size"] == 5242880
        assert data[1]["file_size"] == 1048576