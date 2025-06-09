import os
import json
import asyncio
import aiofiles
from app.core.config import BASE_DIRECTORY, SUBFOLDERS, OUTPUT_DIRECTORY, GROQ_API_KEY, GROQ_MODEL
from app.extractors.pdf_extractor import extract_pdf_content
from app.extractors.excel_extractor import extract_excel_content
from app.extractors.ppt_extractor import extract_ppt_content
from app.extractors.markdown_extractor import extract_markdown_content

from groq import Groq

def ensure_output_structure():
    os.makedirs(OUTPUT_DIRECTORY, exist_ok=True)
    os.makedirs(os.path.join(OUTPUT_DIRECTORY, "images", "img_summary"), exist_ok=True)
    os.makedirs(os.path.join(OUTPUT_DIRECTORY, "images", "img_vision"), exist_ok=True)

async def write_json_async(path, data):
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(json.dumps(data, indent=2, ensure_ascii=False))

async def gather_files():
    pdfs, mds, excels, ppts = [], [], [], []
    for subfolder in SUBFOLDERS:
        path = os.path.join(BASE_DIRECTORY, subfolder)
        for root, _, files in os.walk(path):
            for file in files:
                full = os.path.join(root, file)
                if file.lower().endswith(".pdf"): pdfs.append(full)
                elif file.lower().endswith(".md"): mds.append(full)
                elif file.lower().endswith(".xlsx"): excels.append(full)
                elif file.lower().endswith(".pptx"): ppts.append(full)
    return pdfs, mds, excels, ppts

async def main():
    ensure_output_structure()
    groq_client = Groq(api_key=GROQ_API_KEY)
    pdfs, mds, excels, ppts = await gather_files()

    tasks = []
    for f in pdfs:
        out = os.path.join(OUTPUT_DIRECTORY, os.path.basename(f).replace(".pdf", "_output.json"))
        tasks.append(write_json_async(out, await extract_pdf_content(f, groq_client, GROQ_MODEL)))
    for f in mds:
        out = os.path.join(OUTPUT_DIRECTORY, os.path.basename(f).replace(".md", "_output.json"))
        tasks.append(write_json_async(out, await extract_markdown_content(f)))
    for f in excels:
        out = os.path.join(OUTPUT_DIRECTORY, os.path.basename(f).replace(".xlsx", "_output.json"))
        tasks.append(write_json_async(out, await extract_excel_content(f)))
    for f in ppts:
        out = os.path.join(OUTPUT_DIRECTORY, os.path.basename(f).replace(".pptx", "_output.json"))
        tasks.append(write_json_async(out, await extract_ppt_content(f, groq_client, GROQ_MODEL)))

    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
