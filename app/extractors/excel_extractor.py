import json
import os
from typing import List, Optional
import aiofiles
import pandas as pd

from app.utils.file_handler import change_to_processed


try:
    import fitz  
except Exception:
    fitz = None  

try:
    import win32com.client  
except Exception:
    win32com = None  


def _create_table_html(rows: List[List[str]]) -> str:
    if not rows:
        return "<table></table>"
    html = ["<table>"]
    if len(rows) > 1:
        html.append("<thead>\n<tr>")
        html.extend([f"<th>{cell}</th>" for cell in rows[0]])
        html.append("</tr>\n</thead>")
        html.append("<tbody>")
        for r in rows[1:]:
            html.append("<tr>")
            html.extend([f"<td>{cell}</td>" for cell in r])
            html.append("</tr>")
        html.append("</tbody>")
    else:
        html.append("<tr>")
        html.extend([f"<td>{cell}</td>" for cell in rows[0]])
        html.append("</tr>")
    html.append("</table>")
    return "\n".join(html)


def _create_table_markdown(rows: List[List[str]]) -> str:
    if not rows:
        return ""
    if len(rows) == 1:
        return "| " + " | ".join(rows[0]) + " |"
    md = "| " + " | ".join(rows[0]) + " |\n"
    md += "| " + " | ".join(["-" * max(1, len(c)) for c in rows[0]]) + " |\n"
    for r in rows[1:]:
        md += "| " + " | ".join(r) + " |\n"
    return md.strip()


def _create_table_csv(rows: List[List[str]]) -> str:
    import io, csv
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator='\n')
    for r in rows:
        writer.writerow(["" if c is None else str(c) for c in r])
    return buf.getvalue().replace('\r\n', '\n').rstrip("\n")


def _create_table_plain_text(rows: List[List[str]]) -> str:
    if not rows:
        return ""
    num_cols = max(len(r) for r in rows)
    widths = [0] * num_cols
    for r in rows:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], len(str(c)))
    lines = []
    for r in rows:
        cells = []
        for i in range(num_cols):
            val = "" if i >= len(r) or r[i] is None else str(r[i])
            cells.append(val.ljust(widths[i]))
        lines.append("  ".join(cells).rstrip())
    return "\n".join(lines)


def _page_from_sheet(sheet_name: str, df: pd.DataFrame, page_number: int) -> dict:
    df2 = df.fillna("").astype(str)
    headers = list(map(str, df2.columns.tolist()))
    rows: List[List[str]] = [headers]
    for _, row in df2.iterrows():
        rows.append([str(row.get(h, "")) for h in headers])

    table_item = {
        "type": "table",
        "rows": rows,
        "html": _create_table_html(rows),
        "md": _create_table_markdown(rows),
        "isPerfectTable": True,
        "csv": _create_table_csv(rows),
        "bBox": {"x": 72.8, "y": 72.0, "w": 449.8, "h": 20 + (len(rows) * 25)},
    }

    heading_item = {
        "type": "heading",
        "value": f"Sheet: {sheet_name}",
        "md": f"## Sheet: {sheet_name}",
        "bBox": {"x": 72.8, "y": 40.0, "w": 449.8, "h": 28},
        "lvl": 2,
    }

    text_block = _create_table_plain_text(rows)
    text_with_page = f"{text_block}\n\n{page_number}"
    md_full = _create_table_markdown(rows)
    md_with_page = f"{md_full}\n\n{page_number}\n"

    page_images = [{
        "name": f"page_{page_number}.jpg",
        "height": 841.889763779528,
        "width": 595.303937007874,
        "x": 0,
        "y": 0,
        "original_width": 2263,
        "original_height": 3200,
        "type": "full_page_screenshot",
    }]

    return {
        "page": page_number,
        "text": text_with_page,
        "md": md_with_page,
        "images": page_images,
        "charts": [],
        "items": [heading_item, table_item],
        "status": "OK",
        "originalOrientationAngle": 0,
        "links": [],
        "width": 595.303937007874,
        "height": 841.889763779528,
        "triggeredAutoMode": False,
        "parsingMode": "premium",
        "structuredData": None,
        "noStructuredContent": False,
        "noTextContent": len(text_block.strip()) == 0,
        "pageHeaderMarkdown": f"Sheet: {sheet_name}",
        "pageFooterMarkdown": f"\n{page_number}\n",
        "confidence": 1,
    }


async def extract_excel_content(file_path, *_):
    try:
        ext = os.path.splitext(file_path)[1].lower()
        if ext in [".xlsx", ".xls"]:
            sheets = pd.read_excel(file_path, sheet_name=None, engine="openpyxl")
        elif ext == ".csv":
            df = pd.read_csv(file_path)
            sheets = {"Sheet1": df}
        else:
            return {"error": f"Unsupported tabular file format: {ext}"}
    except Exception as e:
        return {"error": str(e)}

    pages: List[dict] = []
    page_no = 1
    for sheet_name, df in sheets.items():
        pages.append(_page_from_sheet(sheet_name, df, page_no))
        page_no += 1

    result = {"pages": pages}

    base = os.path.splitext(os.path.basename(file_path))[0]
    out_ext = ext.replace('.', '')
    output_path = os.path.join("output", f"{base}.{out_ext}.json")
    os.makedirs("output", exist_ok=True)
    try:
        async with aiofiles.open(output_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        raise IOError(f"Failed to write JSON output file: {e}")

   
    try:
        if win32com is not None and fitz is not None and os.name == 'nt':
           
            img_root = os.path.join("output", "images")
            os.makedirs(img_root, exist_ok=True)

           
            pdf_dir = os.path.join("output", "tmp_pdf")
            os.makedirs(pdf_dir, exist_ok=True)
            pdf_path = os.path.join(pdf_dir, f"{base}.pdf")

            try:
                excel = win32com.client.Dispatch('Excel.Application')
                excel.Visible = False
                wb = excel.Workbooks.Open(os.path.abspath(file_path))
             
                wb.ExportAsFixedFormat(0, os.path.abspath(pdf_path))
                wb.Close(SaveChanges=False)
                excel.Quit()
            except Exception:
              
                pdf_path = None  

            
            if pdf_path and os.path.exists(pdf_path):
                try:
                    with fitz.open(pdf_path) as pdf_doc: 
                        for i, page in enumerate(pdf_doc, start=1):
                            try:
                                pix = page.get_pixmap(dpi=150)
                                img_name = f"page_{i}.jpg"
                                img_path = os.path.join(img_root, img_name)
                                pix.save(img_path)
                            except Exception:
                               
                                continue
                except Exception:
                    pass
    except Exception:
        
        pass

    await change_to_processed(str(file_path), "Excel" if ext in [".xlsx", ".xls"] else "CSV")
    return result
