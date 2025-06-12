from fastapi import UploadFile
from pathlib import Path
from app.core.config import FILE_TYPE_MAP, UPLOAD_ROOT, PROCESSED_ROOT
import shutil


async def get_file_category(extension: str) -> str:
    """
    Determines the file category based on its extension.

    Args:
        extension (str): File extension (e.g., '.pdf').

    Returns:
        str: Category name (e.g., 'pdf', 'image').
    """
    for category, extensions in FILE_TYPE_MAP.items():
        if extension in extensions:
            return category
    return "Others"


async def save_file(owner: str, file: UploadFile) -> str:
    """
    Saves an uploaded file under the structured path: UPLOAD_ROOT/owner/category/filename

    Args:
        owner (str): Username or identifier of the file owner.
        file (UploadFile): Uploaded file object.

    Returns:
        str: Full path where the file was saved.
    """
    extension = Path(file.filename).suffix.lower()
    category = await get_file_category(extension)

    owner_dir = UPLOAD_ROOT / owner / category
    owner_dir.mkdir(parents=True, exist_ok=True)

    file_path = owner_dir / file.filename

    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())

    return str(file_path)


async def change_to_processed(file_path: str, category: str) -> str:
    """
    Moves a processed file to the processed directory.

    Args:
        file_path (str): Original path of the file.
        category (str): Category folder name.

    Returns:
        str: New file path in the processed directory.
    """
    original_path = Path(file_path)
    if not original_path.exists():
        raise FileNotFoundError(f"File {file_path} does not exist.")

    owner = original_path.parent.parent.name
    processed_dir = PROCESSED_ROOT / owner / category
    processed_dir.mkdir(parents=True, exist_ok=True)

    new_file_path = processed_dir / original_path.name
    shutil.move(str(original_path), str(new_file_path))

    return str(new_file_path)


async def remove_old_folder(owner_dir: Path) -> None:
    """
    Removes empty category folders and the owner folder if completely empty.

    Args:
        owner_dir (Path): Directory of the owner (e.g., UPLOAD_ROOT/owner).
    """
    for category_folder in owner_dir.iterdir():
        if category_folder.is_dir() and not any(category_folder.iterdir()):
            try:
                category_folder.rmdir()
            except Exception:
                pass  # Silently ignore cleanup issues

    if not any(owner_dir.iterdir()):
        try:
            owner_dir.rmdir()
        except Exception:
            pass  # Silently ignore cleanup issues


async def get_file_size(file: UploadFile) -> int:
    """
    Gets the size of an UploadFile in bytes.

    Args:
        file (UploadFile): File to measure.

    Returns:
        int: Size in bytes.
    """
    file.file.seek(0, 2)  # Seek to end
    size = file.file.tell()
    file.file.seek(0)     # Reset to start
    return size
