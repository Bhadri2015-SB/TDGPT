from pathlib import Path
import sqlite3
import json
from app.extractors.common_sqlite_extraction import extract_data_from_connection

def extract_sql_from_script(file_path: str, output_dir: str = "output/sql_script") -> str:
    sql_path = Path(file_path)
    if not sql_path.exists():
        raise FileNotFoundError(f"SQL file not found: {file_path}")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    output_file = output_path / f"{sql_path.stem}.json"

    with open(sql_path, "r", encoding="utf-8") as f:
        sql_script = f.read()

    connection = sqlite3.connect(":memory:")
    cursor = connection.cursor()

    try:
        cursor.executescript(sql_script)
    except Exception as e:
        connection.close()
        raise ValueError(f"SQL script execution failed: {e}")

    result = extract_data_from_connection(connection)
    connection.close()

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    return result
