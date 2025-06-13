from fastapi import UploadFile
from pathlib import Path
from app.core.config import FILE_TYPE_MAP, UPLOAD_ROOT, PROCESSED_ROOT
from app.core.logger import app_logger  
import shutil


async def get_file_category(extension: str) -> str:
    for category, extensions in FILE_TYPE_MAP.items():
        if extension in extensions:
            app_logger.debug(f"Extension '{extension}' matched category '{category}'")
            return category
    app_logger.warning(f"Extension '{extension}' did not match any category. Using 'Others'.")
    return "Others"


async def save_file(owner: str, file: UploadFile) -> str:
    extension = Path(file.filename).suffix.lower()
    category = await get_file_category(extension)

    owner_dir = UPLOAD_ROOT / owner / category
    owner_dir.mkdir(parents=True, exist_ok=True)

    file_path = owner_dir / file.filename

    try:
        with open(file_path, "wb") as buffer:
            buffer.write(await file.read())
        app_logger.info(f"Saved file '{file.filename}' to '{file_path}'")
    except Exception as e:
        app_logger.exception(f"Failed to save file '{file.filename}': {e}")
        raise

    return str(file_path)


async def change_to_processed(file_path: str, category: str) -> str:
    original_path = Path(file_path)
    if not original_path.exists():
        app_logger.error(f"File '{file_path}' does not exist.")
        raise FileNotFoundError(f"File {file_path} does not exist.")

    owner = original_path.parent.parent.name
    processed_dir = PROCESSED_ROOT / owner / category
    processed_dir.mkdir(parents=True, exist_ok=True)

    new_file_path = processed_dir / original_path.name

    try:
        shutil.move(str(original_path), str(new_file_path))
        app_logger.info(f"Moved file from '{original_path}' to '{new_file_path}'")
    except Exception as e:
        app_logger.exception(f"Failed to move file '{original_path}': {e}")
        raise

    return str(new_file_path)


async def remove_old_folder(owner_dir: Path) -> None:
    try:
        for category_folder in owner_dir.iterdir():
            if category_folder.is_dir() and not any(category_folder.iterdir()):
                category_folder.rmdir()
                app_logger.debug(f"Removed empty category folder: {category_folder}")

        if not any(owner_dir.iterdir()):
            owner_dir.rmdir()
            app_logger.info(f"Removed empty owner folder: {owner_dir}")
    except Exception as e:
        app_logger.warning(f"Error during folder cleanup in '{owner_dir}': {e}")


async def get_file_size(file: UploadFile) -> int:
    try:
        file.file.seek(0, 2)  
        size = file.file.tell()
        file.file.seek(0)     
        app_logger.debug(f"Size of file '{file.filename}' is {size} bytes.")
        return size
    except Exception as e:
        app_logger.exception(f"Failed to get file size for '{file.filename}': {e}")
        raise
