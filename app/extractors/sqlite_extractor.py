import sqlite3
import json
from pathlib import Path

def extract_sqlite_data(file_path: str, output_dir: str = "output/sqlite") -> str:
    db_path = Path(file_path)
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite file not found: {file_path}")

    # Create output directory if it doesn't exist
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Output JSON file name
    output_file = output_path / f"{db_path.stem}.json"

    connection = sqlite3.connect(str(db_path))
    cursor = connection.cursor()

    result = []

    # Get all table names
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]

    for table_name in tables:
        # Get column names
        cursor.execute(f"PRAGMA table_info({table_name});")
        columns = [col[1] for col in cursor.fetchall()]

        # Get data rows
        cursor.execute(f"SELECT * FROM {table_name};")
        rows = cursor.fetchall()

        # Combine columns with row values
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

    # Write to output JSON file
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    return result
