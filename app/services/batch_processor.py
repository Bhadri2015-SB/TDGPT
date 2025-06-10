#not used

import os
import asyncio
from groq import Groq

from app.core.config import GROQ_API_KEY, GROQ_MODEL, OUTPUT_DIRECTORY, BASE_DIRECTORY, SUBFOLDERS
from app.extractors.process_files import ensure_output_structure
from app.extractors.pdf_extractor import process_pdf_file
from app.extractors.excel_extractor import process_excel_file
from app.extractors.ppt_extractor import process_ppt_file
from app.extractors.markdown_extractor import process_md_file
from app.core.groq_setup import groq_client, GROQ_MODEL


async def gather_files():
    pdf_files, md_files, excel_files, ppt_files = [], [], [], []
    for subfolder in SUBFOLDERS:
        folder_path = os.path.join(BASE_DIRECTORY, subfolder)
        print(f"Scanning: {folder_path}")
        for root, _, files in os.walk(folder_path):
            for file in files:
                file_path = os.path.join(root, file)
                if file.lower().endswith(".pdf"):
                    pdf_files.append(file_path)
                elif file.lower().endswith(".md"):
                    md_files.append(file_path)
                elif file.lower().endswith(".xlsx"):
                    excel_files.append(file_path)
                elif file.lower().endswith(".pptx"):
                    ppt_files.append(file_path)
    return pdf_files, md_files, excel_files, ppt_files


async def main():
    ensure_output_structure(OUTPUT_DIRECTORY)
    

    pdf_files, md_files, excel_files, ppt_files = await gather_files()

    tasks = []
    tasks.extend(process_pdf_file(pdf, groq_client, GROQ_MODEL, OUTPUT_DIRECTORY) for pdf in pdf_files)
    tasks.extend(process_md_file(md, groq_client, GROQ_MODEL, OUTPUT_DIRECTORY) for md in md_files)
    tasks.extend(process_excel_file(excel, groq_client, GROQ_MODEL, OUTPUT_DIRECTORY) for excel in excel_files)
    tasks.extend(process_ppt_file(ppt, groq_client, GROQ_MODEL, OUTPUT_DIRECTORY) for ppt in ppt_files)

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
