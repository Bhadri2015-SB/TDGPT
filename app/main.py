from fastapi import FastAPI
from app.api import upload

app = FastAPI()

app.include_router(upload.router, prefix="/api")


























# from app.services.pdf_extractor import process_pdf
# import time
# import os
# import json
# import asyncio

# from app.services.github_file_extraction import get_repo_files
# from app.services.web_data_extraction import PageExtractor, WebsiteCrawler

# async def main(path):
# 	start_time = time.time()
# 	result = await process_pdf(path)
# 	result["overall_time_taken"] = f"{time.time() - start_time:.2f} seconds"
# 	print(result)
# 	OUTPUT_DIR = "output/pdf_extraction"
# 	os.makedirs(OUTPUT_DIR, exist_ok=True)

# 	json_path = os.path.join(OUTPUT_DIR, "output" + ".json")
# 	with open(json_path, "w", encoding="utf-8") as f:
# 		json.dump(result, f, indent=2, ensure_ascii=False)

# # asyncio.run(main("C:/Users/bhadr/Documents/Troudz_poc/TDGPT/Data_collection/small/MIPS_Assembly_Language_small_163.pdf"))

# async def extract_files(repo_url: str):
# 	try:
# 		return await get_repo_files(repo_url)
# 	except Exception as e:
# 		print(f"Error extracting files: {e}")
# 		return {"error": str(e)}
	
# # print(asyncio.run(extract_files("https://github.com/Bhadri2015-SB/Day-4")))


# BASE_URL = "https://andrewssamraj.com"
# def web_crawl():
#     crawler = WebsiteCrawler(BASE_URL)
#     urls = crawler.crawl()

#     results = []
#     for url in urls:
#         extractor = PageExtractor(url)
#         page_data = extractor.extract()
#         results.append(page_data)

#     os.makedirs("output", exist_ok=True)
#     with open("output/web_extraction/result.json", "w", encoding="utf-8") as f:
#         json.dump(results, f, indent=2, ensure_ascii=False)

#     print(f"✅ Extraction complete. {len(results)} pages saved to output/result.json")

# web_crawl()