from pathlib import Path
import sqlite3
import json
from app.extractors.common_sqlite_extraction import extract_data_from_connection

def extract_sqlite_data(file_path: str, output_dir: str = "output/sqlite") -> str:
    db_path = Path(file_path)
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite file not found: {file_path}")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    output_file = output_path / f"{db_path.stem}.json"

    connection = sqlite3.connect(str(db_path))
    result = extract_data_from_connection(connection)
    connection.close()

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    return result
