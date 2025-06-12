from typing import Dict, Any
import aiosqlite

async def extract_data_from_connection(connection: aiosqlite.Connection) -> Dict[str, Any]:
    """
    Asynchronously extracts table names, column names, and row data from an SQLite database connection.

    Args:
        connection (aiosqlite.Connection): An asynchronous SQLite database connection.

    Returns:
        Dict[str, Any]: A dictionary where each key is a table name, and each value contains column metadata and table rows.
    """
    result = {}

    try:
        async with connection.execute("SELECT name FROM sqlite_master WHERE type='table';") as cursor:
            tables = [row[0] async for row in cursor]

        for table_name in tables:
            async with connection.execute(f'PRAGMA table_info("{table_name}");') as cursor:
                columns = [col[1] async for col in cursor]

            async with connection.execute(f'SELECT * FROM "{table_name}";') as cursor:
                rows = [row async for row in cursor]

            table_data = [dict(zip(columns, row)) for row in rows]

            result[table_name] = {
                "columns": columns,
                "data": table_data
            }

    except Exception as e:
        print(f"An error occurred: {e}")
        # Optionally re-raise or handle differently

    return result
