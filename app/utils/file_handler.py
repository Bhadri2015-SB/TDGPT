from fastapi import UploadFile
from pathlib import Path
from app.core.config import FILE_TYPE_MAP, UPLOAD_ROOT, PROCESSED_ROOT

async def get_file_category(extension: str) -> str:
    for category, extensions in FILE_TYPE_MAP.items():
        if extension in extensions:
            return category
    return "Others"

async def save_file(owner: str, file: UploadFile) -> str:
    extension = Path(file.filename).suffix.lower()
    category = await get_file_category(extension)

    owner_dir = UPLOAD_ROOT / owner / category
    owner_dir.mkdir(parents=True, exist_ok=True)

    file_path = owner_dir / file.filename
    with open(file_path, "wb") as buffer:
        buffer.write(file.file.read())

    return str(file_path)

async def change_to_processed(owner: str, file_path: str, category: str) -> str:

    processed_dir = PROCESSED_ROOT / owner / category
    processed_dir.mkdir(parents=True, exist_ok=True)

    file_name = Path(file_path).name
    new_file_path = processed_dir / file_name

    if not Path(file_path).exists():
        raise FileNotFoundError(f"File {file_path} does not exist.")

    Path(file_path).rename(new_file_path)
    return str(new_file_path)

async def remove_old_folder(owner_dir):
    for category_folder in owner_dir.iterdir():
        if category_folder.is_dir() and not any(category_folder.iterdir()):
            try:
                category_folder.rmdir()
            except Exception as e:
                print(f"Failed to remove folder {category_folder}: {e}")

    # 🧹 Remove the owner directory if it's now empty
    if not any(owner_dir.iterdir()):
        try:
            owner_dir.rmdir()
        except Exception as e:
            print(f"Failed to remove owner directory {owner_dir}: {e}")


async def get_file_size(file: UploadFile) -> int:
    file.file.seek(0, 2)  # Move to end of file
    size = file.file.tell()
    file.file.seek(0)     # Reset to beginning
    return size

