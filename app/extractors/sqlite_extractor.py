from pathlib import Path
import json
import aiofiles
import aiosqlite
from typing import Union, Dict, Any

from app.extractors.common_sqlite_extraction import (
    extract_data_from_connection,
    format_sqlite_result_as_word_pages,
)
from app.utils.file_handler import change_to_processed


async def extract_sqlite_data(
    file_path: Union[str, Path],
    output_dir: Union[str, Path] = "output"
) -> Dict[str, Any]:
    """
    Extract data from an SQLite database and write a Word-style JSON structure.

    Args:
        file_path (str | Path): Path to the SQLite database file.
        output_dir (str | Path): Directory to write the resulting JSON output.

    Returns:
        Dict[str, Any]: Word-extractor-like JSON: {"pages": [...]}.
    """
    db_path = Path(file_path)
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite file not found: {db_path}")

    try:
        async with aiosqlite.connect(db_path) as connection:
            raw_result = await extract_data_from_connection(connection)
    except Exception as e:
        raise RuntimeError(f"Failed to extract data from SQLite database: {e}")

    print("end of sqlite extractor")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    output_file = output_path / f"{db_path.name}.json"

    formatted = format_sqlite_result_as_word_pages(raw_result)

    try:
        async with aiofiles.open(output_file, "w", encoding="utf-8") as f:
            await f.write(json.dumps(formatted, indent=2, ensure_ascii=False))
    except Exception as e:
        raise IOError(f"Failed to write JSON output file: {e}")

    await change_to_processed(str(file_path), "SQLITE")

    return formatted
