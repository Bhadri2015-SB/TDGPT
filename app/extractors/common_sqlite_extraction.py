from typing import Dict, Any, List
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


def _table_rows_from_dicts(columns: List[str], data_rows: List[Dict[str, Any]]) -> List[List[str]]:
    rows: List[List[str]] = [columns]
    for r in data_rows:
        rows.append(["" if r.get(col) is None else str(r.get(col)) for col in columns])
    return rows


def _create_table_html(rows: List[List[str]]) -> str:
    if not rows:
        return "<table></table>"
    html = "<table>\n"
    if len(rows) > 1:
        html += "<thead>\n<tr>\n"
        for cell in rows[0]:
            html += f"<th>{cell}</th>\n"
        html += "</tr>\n</thead>\n<tbody>\n"
        for row in rows[1:]:
            html += "<tr>\n"
            for cell in row:
                html += f"<td>{cell}</td>\n"
            html += "</tr>\n"
        html += "</tbody>\n"
    else:
        html += "<tr>\n"
        for cell in rows[0]:
            html += f"<td>{cell}</td>\n"
        html += "</tr>\n"
    html += "</table>"
    return html


def _create_table_markdown(rows: List[List[str]]) -> str:
    if not rows:
        return ""
    if len(rows) == 1:
        return "| " + " | ".join(rows[0]) + " |"
    md = "| " + " | ".join(rows[0]) + " |\n"
    md += "| " + " | ".join(["-" * len(cell) for cell in rows[0]]) + " |\n"
    for row in rows[1:]:
        md += "| " + " | ".join(row) + " |\n"
    return md.strip()


def _create_table_csv(rows: List[List[str]]) -> str:
    import io, csv
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator='\n')
    for row in rows:
        writer.writerow(["" if cell is None else str(cell) for cell in row])
    return buf.getvalue().replace('\r\n', '\n').rstrip("\n")


def _create_table_plain_text(rows: List[List[str]]) -> str:
    if not rows:
        return ""
    num_cols = max(len(r) for r in rows)
    col_widths = [0] * num_cols
    for r in rows:
        for i, cell in enumerate(r):
            col_widths[i] = max(col_widths[i], len(str(cell)))
    lines: List[str] = []
    for r in rows:
        cells: List[str] = []
        for i in range(num_cols):
            val = "" if i >= len(r) or r[i] is None else str(r[i])
            cells.append(val.ljust(col_widths[i]))
        lines.append("  ".join(cells).rstrip())
    return "\n".join(lines)


def format_sqlite_result_as_word_pages(result: Dict[str, Any]) -> Dict[str, Any]:
    pages: List[Dict[str, Any]] = []
    page_num = 1
    for table_name, meta in result.items():
        columns: List[str] = meta.get("columns", [])
        data_list: List[Dict[str, Any]] = meta.get("data", [])
        rows = _table_rows_from_dicts(columns, data_list)

        heading_text = table_name
        heading_item = {
            "type": "heading",
            "value": heading_text,
            "md": f"## {heading_text}",
            "bBox": {"x": 72.8, "y": 72.0, "w": 449.8, "h": 28.0},
            "lvl": 2,
        }

        table_item = {
            "type": "table",
            "rows": rows,
            "html": _create_table_html(rows),
            "md": _create_table_markdown(rows),
            "isPerfectTable": True,
            "csv": _create_table_csv(rows),
            "bBox": {
                "x": 72.8,
                "y": 72.0 + 28.0 + 10.0,
                "w": 449.8,
                "h": 20 + (len(rows) * 25),
            },
        }

        page_text = f"{heading_text}\n\n{_create_table_plain_text(rows)}"
        md_content = f"## {heading_text}\n\n{_create_table_markdown(rows)}\n\n{page_num}\n"

        page = {
            "page": page_num,
            "text": f"{page_text}\n\n{page_num}",
            "md": md_content,
            "images": [],
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
            "noTextContent": False,
            "pageHeaderMarkdown": heading_text,
            "pageFooterMarkdown": f"\n{page_num}\n",
            "confidence": 1,
        }

        pages.append(page)
        page_num += 1

    return {"pages": pages}
