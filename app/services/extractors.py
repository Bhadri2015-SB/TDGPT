from app.extractors.json_extractor import flatten_json_file
from app.extractors.word_extractor import process_word_file


PROCESSOR_MAP = {
    "PDF": "extract_text_from_pdf",
    "Word": process_word_file,
    "Markdown": "extract_text_from_md",
    "PPT": "extract_text_from_ppt",
    "Excel": "extract_text_from_excel",
    "Image": "extract_text_from_image",
    "Video": "extract_text_from_video",
    "SQL": "extract_text_from_sql",
    "JSON": flatten_json_file
}