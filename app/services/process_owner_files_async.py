import asyncio
from pathlib import Path
from app.utils.file_handler import get_file_category
from extractors import PROCESSOR_MAP
from utils import UPLOAD_ROOT

async def process_file(file_path: Path, category: str):
    try:
        processor = PROCESSOR_MAP.get(category)
        if processor:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, processor, str(file_path))
            return {"file": file_path.name, "output": result}
        else:
            return {"file": file_path.name, "error": f"No processor for category {category}"}
    except Exception as e:
        return {"file": file_path.name, "error": str(e)}

async def process_owner_files_async(owner: str):
    owner_dir = UPLOAD_ROOT / owner
    if not owner_dir.exists():
        raise FileNotFoundError("Owner directory not found")

    tasks = []
    for category_folder in owner_dir.iterdir():
        if not category_folder.is_dir():
            continue
        category = category_folder.name
        for file_path in category_folder.glob("*"):
            if file_path.is_file():
                tasks.append(process_file(file_path, category))

    results = await asyncio.gather(*tasks)
    grouped = {}
    for item in results:
        ext = Path(item["file"]).suffix.lower()
        cat = get_file_category(ext)
        grouped.setdefault(cat, []).append(item)
    return grouped

