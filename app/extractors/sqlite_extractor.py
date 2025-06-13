from pathlib import Path
import json
import aiofiles
import aiosqlite
from typing import Union, List, Dict, Any

from app.core.logger import app_logger
from app.extractors.common_sqlite_extraction import extract_data_from_connection
from app.utils.file_handler import change_to_processed


async def extract_sqlite_data(
    file_path: Union[str, Path],
    output_dir: Union[str, Path] = "output"
) -> List[Dict[str, Any]]:
    """
    Asynchronously extracts data from an SQLite database and writes it to a JSON file.

    Args:
        file_path (str | Path): Path to the SQLite database file.
        output_dir (str | Path): Directory to write the resulting JSON output.

    Returns:
        List[Dict[str, Any]]: A list of table metadata and data extracted from the database.
    """
    db_path = Path(file_path)
    if not db_path.exists():
        app_logger.error(f"SQLite file does not exist: {db_path}")
        raise FileNotFoundError(f"SQLite file not found: {db_path}")

    try:
        async with aiosqlite.connect(db_path) as connection:
            result = await extract_data_from_connection(connection)
        app_logger.info(f"Extracted data successfully from SQLite DB: {db_path.name}")
    except Exception as e:
        app_logger.exception(f"Failed to extract data from SQLite database: {db_path.name}")
        raise RuntimeError(f"Failed to extract data from SQLite database: {e}")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    output_file = output_path / f"{db_path.name}.json"

    try:
        async with aiofiles.open(output_file, "w", encoding="utf-8") as f:
            await f.write(json.dumps(result, indent=2, ensure_ascii=False))
        app_logger.info(f"Written JSON output for SQLite DB to: {output_file}")
    except Exception as e:
        app_logger.exception(f"Failed to write JSON output file: {output_file}")
        raise IOError(f"Failed to write JSON output file: {e}")

    await change_to_processed(str(file_path), "SQLITE")
    app_logger.info(f"Moved SQLite file to processed directory: {db_path.name}")

    return result
