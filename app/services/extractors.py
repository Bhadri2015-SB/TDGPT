from app.extractors.json_extractor import flatten_json_file
from app.extractors.sql_script_extractor import extract_sql_from_script
from app.extractors.sqlite_extractor import extract_sqlite_data
from app.extractors.word_extractor import process_word_file
from app.extractors.pdf_extractor import extract_pdf_content
from app.extractors.markdown_extractor import extract_markdown_content
from app.extractors.ppt_extractor import extract_ppt_content
from app.extractors.excel_extractor import extract_excel_content
from app.services.image_caption import extract_text_from_image  


PROCESSOR_MAP = {
    "PDF": extract_pdf_content,
    "Word": process_word_file,
    "Markdown": extract_markdown_content,
    "PPT": extract_ppt_content,
    "Excel": extract_excel_content,
    "Image": extract_text_from_image,  
    "Video": None,  
    "SQLITE": extract_sqlite_data,
    "SQL_SCRIPT": extract_sql_from_script,
    "JSON": flatten_json_file,
}
