from pathlib import Path
import json
import aiofiles
import aiosqlite
from typing import Union, List, Dict

from app.core.logger import app_logger
from app.extractors.common_sqlite_extraction import extract_data_from_connection
from app.utils.file_handler import change_to_processed


async def extract_sql_from_script(
    file_path: Union[str, Path],
    output_dir: Union[str, Path] = "output"
) -> List[Dict]:
    """
    Executes an SQL script file in-memory using SQLite and extracts the resulting data.

    Args:
        file_path (str | Path): Path to the .sql file.
        output_dir (str | Path): Directory to store the resulting JSON file.

    Returns:
        List[Dict]: Extracted table data from the executed script.
    """
    sql_path = Path(file_path)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    output_file = output_path / f"{sql_path.name}.json"

    if not sql_path.exists():
        app_logger.error(f"SQL script file does not exist: {sql_path}")
        raise FileNotFoundError(f"SQL script not found at: {sql_path}")

    try:
        with sql_path.open("r", encoding="utf-8") as f:
            sql_script = f.read()
        app_logger.info(f"Read SQL script successfully: {sql_path.name}")
    except Exception as e:
        app_logger.exception(f"Error reading SQL script file '{sql_path}': {e}")
        raise IOError(f"Error reading SQL script file '{sql_path}': {e}")

    
    try:
        async with aiosqlite.connect(":memory:") as connection:
            await connection.executescript(sql_script)
            result = await extract_data_from_connection(connection)
        app_logger.info(f"Executed SQL script and extracted data successfully: {sql_path.name}")
    except Exception as e:
        app_logger.exception(f"SQL script execution or extraction failed for '{sql_path}': {e}")
        raise RuntimeError(f"SQL script execution or extraction failed: {e}")

    
    try:
        async with aiofiles.open(output_file, "w", encoding="utf-8") as f:
            await f.write(json.dumps(result, indent=2, ensure_ascii=False))
        app_logger.info(f"Saved extracted SQL result to JSON: {output_file}")
    except Exception as e:
        app_logger.exception(f"Failed to write output JSON file '{output_file}': {e}")
        raise IOError(f"Failed to write output JSON file to '{output_file}': {e}")

    await change_to_processed(str(sql_path), "SQL_SCRIPT")
    app_logger.info(f"Moved SQL script to processed folder: {sql_path.name}")

    return result
