from pathlib import Path
import json
import aiosqlite
from typing import Union
from app.extractors.common_sqlite_extraction import extract_data_from_connection


async def extract_sql_from_script(
    file_path: Union[str, Path],
    output_dir: Union[str, Path] = "output/sql_script"
) -> list:
    """
    Asynchronously extracts data from an SQL script and saves it as a JSON file.

    Args:
        file_path (str | Path): Path to the .sql script file.
        output_dir (str | Path): Directory to store the output .json file.

    Returns:
        list: Extracted database data from the executed script.
    """
    sql_path = Path(file_path)
    if not sql_path.exists():
        raise FileNotFoundError(f"SQL file not found: {file_path}")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    output_file = output_path / f"{sql_path.stem}.json"

    # Read SQL script (sync is fine here unless you're processing very large files)
    try:
        with open(sql_path, "r", encoding="utf-8") as f:
            sql_script = f.read()
    except Exception as e:
        raise IOError(f"Failed to read SQL script file: {e}")

    # Create in-memory SQLite DB
    async with aiosqlite.connect(":memory:") as connection:
        try:
            await connection.executescript(sql_script)
        except Exception as e:
            raise ValueError(f"SQL script execution failed: {e}")

        result = await extract_data_from_connection(connection)

    # Save to JSON
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
    except Exception as e:
        raise IOError(f"Failed to write JSON output: {e}")

    return result
