import json
import os
import aiofiles
import pandas as pd

from app.utils.file_handler import change_to_processed
# from app.core.logger import #app_logger  


async def extract_excel_content(file_path, *_):
    try:
        ext = os.path.splitext(file_path)[1].lower()
        #app_logger.info(f"Starting tabular file extraction: {file_path} (Extension: {ext})")

        if ext in [".xlsx", ".xls"]:
            #app_logger.debug("Reading Excel file using openpyxl...")
            sheets = pd.read_excel(file_path, sheet_name=None, engine="openpyxl")
        elif ext == ".csv":
            #app_logger.debug("Reading CSV file...")
            df = pd.read_csv(file_path)
            sheets = {"Sheet1": df}
        else:
            msg = f"Unsupported tabular file format: {ext}"
            #app_logger.error(msg)
            return {"error": msg}

    except Exception as e:
        #app_logger.exception(f"Failed to read the tabular file: {file_path}")
        return {"error": str(e)}

    content = []
    for sheet, df in sheets.items():
        #app_logger.info(f"Processing sheet: {sheet} with {len(df)} rows")
        df = df.fillna("").astype(str)

        for idx, row in df.iterrows():
            row_data = row.to_dict()
            if any(cell.strip() for cell in row_data.values()):
                content.append({
                    "sheet": sheet,
                    "row_number": idx + 1,
                    "row_data": row_data
                })

    file_name = os.path.basename(file_path)
    result = {
        "metadata": {
            "file_name": file_name,
            "file_type": "excel" if ext in [".xlsx", ".xls"] else "csv",
            "file_size": f"{os.path.getsize(file_path)/1024:.2f} KB",
            "sheet_count": len(sheets)
        },
        "rows_extracted": len(content),
        "content": content,
        "summary": "Tabular extraction complete."
    }

    try:
        output_path = f"output/{file_name}.json"
        #app_logger.info(f"Writing extracted data to {output_path}")
        async with aiofiles.open(output_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        #app_logger.exception("Failed to write the JSON output file")
        raise IOError(f"Failed to write JSON output file: {e}")

    await change_to_processed(str(file_path), "Excel" if ext in [".xlsx", ".xls"] else "CSV")
    #app_logger.info(f"File processed and moved: {file_path}")
    return result
