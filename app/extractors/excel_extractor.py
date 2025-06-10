import json
import os
import aiofiles
import pandas as pd

from app.utils.file_handler import change_to_processed

async def extract_excel_content(file_path, *_):
    try:
        sheets = pd.read_excel(file_path, sheet_name=None)
    except Exception as e:
        return {"error": str(e)}

    content = []
    for sheet, df in sheets.items():
        df = df.fillna("").astype(str)
        for idx, row in df.iterrows():
            row_data = row.to_dict()
            if any(cell.strip() for cell in row_data.values()):
                content.append({"sheet": sheet, "row_number": idx + 1, "row_data": row_data})


    file_name = os.path.basename(file_path)
    result = {
        "metadata": {
            "file_name": file_name,
            "file_type": "excel",
            "file_size": f"{os.path.getsize(file_path)/1024:.2f} KB",
            "sheet_count": len(sheets)
        },
        "rows_extracted": len(content),
        "content": content,
        "summary": "Excel extraction complete."
    }
    print("end of excel extractor")
    try:
        async with aiofiles.open(f"output/{file_name}.json", "w", encoding="utf-8") as f:
            await f.write(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        raise IOError(f"Failed to write JSON output file: {e}")
    await change_to_processed(str(file_path), "Excel")
    return result
