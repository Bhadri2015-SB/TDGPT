import aiosqlite
from typing import List, Dict, Any


async def extract_data_from_connection(connection: aiosqlite.Connection) -> List[Dict[str, Any]]:
    """
    Asynchronously extracts table names, column names, and row data from an SQLite database connection.

    Args:
        connection (aiosqlite.Connection): An asynchronous SQLite database connection.

    Returns:
        List[Dict[str, Any]]: A list of dictionaries containing table metadata and row data.
    """
    result = []

    try:
        async with connection.execute("SELECT name FROM sqlite_master WHERE type='table';") as cursor:
            tables = [row[0] async for row in cursor]

        for table_name in tables:
            async with connection.execute(f"PRAGMA table_info({table_name});") as cursor:
                columns = [col[1] async for col in cursor]

            async with connection.execute(f"SELECT * FROM {table_name};") as cursor:
                rows = [row async for row in cursor]

            table_data = [dict(zip(columns, row)) for row in rows]

            result.append({
                "table_name": table_name,
                "columns": columns,
                "data": table_data
            })

    except Exception as e:
        # In production, replace this print with logging
        print(f"An error occurred: {e}")
        # Optionally, re-raise or handle the exception as appropriate for your app

    return result
