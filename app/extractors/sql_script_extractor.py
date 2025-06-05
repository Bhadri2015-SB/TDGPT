import sqlite3
import json
from pathlib import Path

def extract_sql_from_script(file_path: str, output_dir: str = "output/sql_script") -> str:
    sql_path = Path(file_path)
    if not sql_path.exists():
        raise FileNotFoundError(f"SQL file not found: {file_path}")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    output_file = output_path / f"{sql_path.stem}.json"

    # Read SQL commands
    with open(sql_path, "r", encoding="utf-8") as f:
        sql_script = f.read()

    # Create in-memory SQLite DB
    connection = sqlite3.connect(":memory:")
    cursor = connection.cursor()

    try:
        cursor.executescript(sql_script)
    except Exception as e:
        raise ValueError(f"SQL script execution failed: {e}")

    result = []

    # Get all table names
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]

    for table_name in tables:
        cursor.execute(f"PRAGMA table_info({table_name});")
        columns = [col[1] for col in cursor.fetchall()]

        cursor.execute(f"SELECT * FROM {table_name};")
        rows = cursor.fetchall()

        table_data = [
            dict(zip(columns, row))
            for row in rows
        ]

        result.append({
            "table_name": table_name,
            "columns": columns,
            "data": table_data
        })

    connection.close()

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    return result
