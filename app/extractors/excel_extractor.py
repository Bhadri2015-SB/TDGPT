import os
import pandas as pd

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

    return {
        "metadata": {
            "file_name": os.path.basename(file_path),
            "file_type": "excel",
            "file_size": f"{os.path.getsize(file_path)/1024:.2f} KB",
            "sheet_count": len(sheets)
        },
        "rows_extracted": len(content),
        "content": content,
        "summary": "Excel extraction complete."
    }
