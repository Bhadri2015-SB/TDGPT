from app.extractors.pdf_extractor import extract_pdf_content



PROCESSOR_MAP = {
    "PDF": extract_pdf_content,
}
