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


async def extract_sql_from_script(
    file_path: Union[str, Path],
    output_dir: Union[str, Path] = "output"
) -> Dict[str, Any]:
    """
    Execute an SQL script in-memory and return Word-style JSON output.

    Args:
        file_path (str | Path): Path to the .sql file.
        output_dir (str | Path): Directory to store the resulting JSON file.

    Returns:
        Dict[str, Any]: Word-extractor-like JSON: {"pages": [...]}.
    """
    sql_path = Path(file_path)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    output_file = output_path / f"{sql_path.name}.json"

    if not sql_path.exists():
        raise FileNotFoundError(f"SQL script not found at: {sql_path}")

    try:
        with sql_path.open("r", encoding="utf-8") as f:
            sql_script = f.read()
    except Exception as e:
        raise IOError(f"Error reading SQL script file '{sql_path}': {e}")

    # Execute in in-memory SQLite DB
    try:
        async with aiosqlite.connect(":memory:") as connection:
            await connection.executescript(sql_script)
            raw_result = await extract_data_from_connection(connection)
    except Exception as e:
        raise RuntimeError(f"SQL script execution or extraction failed: {e}")

    print("end of sql script extractor")

    formatted = format_sqlite_result_as_word_pages(raw_result)

    # Save result to output file
    try:
        async with aiofiles.open(output_file, "w", encoding="utf-8") as f:
            await f.write(json.dumps(formatted, indent=2, ensure_ascii=False))
    except Exception as e:
        raise IOError(f"Failed to write output JSON file to '{output_file}': {e}")

    await change_to_processed(str(sql_path), "SQL_SCRIPT")
    return formatted
