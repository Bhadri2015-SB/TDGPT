from fastapi import UploadFile
from pathlib import Path
from app.core.config import FILE_TYPE_MAP, UPLOAD_ROOT

def get_file_category(extension: str) -> str:
    for category, extensions in FILE_TYPE_MAP.items():
        if extension in extensions:
            return category
    return "Others"

def save_file(owner: str, file: UploadFile) -> str:
    extension = Path(file.filename).suffix.lower()
    category = get_file_category(extension)

    owner_dir = UPLOAD_ROOT / owner / category
    owner_dir.mkdir(parents=True, exist_ok=True)

    file_path = owner_dir / file.filename
    with open(file_path, "wb") as buffer:
        buffer.write(file.file.read())

    return str(file_path)
