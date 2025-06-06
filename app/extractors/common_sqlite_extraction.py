import sqlite3
from typing import List

def extract_data_from_connection(connection: sqlite3.Connection) -> List[dict]:
    cursor = connection.cursor()
    result = []

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

    return result
