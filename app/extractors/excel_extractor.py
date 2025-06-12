import json
from pathlib import Path
from typing import Any, Dict

import aiofiles
import pandas as pd

from app.utils.file_handler import change_to_processed


async def extract_excel_content(file_path: str, *_) -> Dict[str, Any]:
    """
    Extracts content from an Excel file and writes it as a JSON file.

    Args:
        file_path (str): Path to the Excel file.

    Returns:
        dict: Extraction result including metadata, content, and status message.
    """
    file = Path(file_path)
    try:
        sheets = pd.read_excel(file_path, sheet_name=None)
    except Exception as e:
        return {
            "file_name": file.name,
            "file_type": "excel",
            "status": "error",
            "message": f"Failed to read Excel file: {e}"
        }

    content = []
    for sheet_name, df in sheets.items():
        df = df.fillna("").astype(str)
        for idx, row in df.iterrows():
            row_data = row.to_dict()
            if any(cell.strip() for cell in row_data.values()):
                content.append({
                    "sheet": sheet_name,
                    "row_number": idx + 1,
                    "row_data": row_data
                })

    result = {
        "metadata": {
            "file_name": file.name,
            "file_type": "excel",
            "file_size": f"{file.stat().st_size / 1024:.2f} KB",
            "sheet_count": len(sheets)
        },
        "rows_extracted": len(content),
        "content": content,
        "summary": "Excel extraction complete."
        # "total_time_taken": "0"  # Placeholder; to be optionally updated by caller
    }

    output_path = Path("output") / f"{file.name}.json"
    try:
        async with aiofiles.open(output_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        return {
            "file_name": file.name,
            "file_type": "excel",
            "status": "error",
            "message": f"Failed to write JSON output: {e}"
        }

    await change_to_processed(str(file), "Excel")
    return result
