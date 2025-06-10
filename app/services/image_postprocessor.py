# import os
# import json
# import asyncio
# import aiofiles
# from PIL import Image
# import pytesseract
# from app.services.image_caption import describe_image
 

# IMG_VISION_DIR = os.path.join("output", "images", "img_vision")
# IMG_SUMMARY_DIR = os.path.join("output", "images", "img_summary")

# os.makedirs(IMG_VISION_DIR, exist_ok=True)
# os.makedirs(IMG_SUMMARY_DIR, exist_ok=True)


# async def ocr_image(img_path):
   
#     def ocr_sync():
#         img = Image.open(img_path).convert("RGB")
#         return pytesseract.image_to_string(img).strip()

#     return await asyncio.to_thread(ocr_sync)


# async def save_json_async(data, path):
#     async with aiofiles.open(path, "w", encoding="utf-8") as f:
#         await f.write(json.dumps(data, indent=2, ensure_ascii=False))


# async def process_image(item_number, idx, img_path, file_basename, content_type, groq_client, model):
#     img_path = img_path.replace("\\", "/")
#     if not os.path.exists(img_path):
#         print(f"Image not found: {img_path}")
#         return

#     try:
#         ocr_text = await ocr_image(img_path)

#         if ocr_text:
#             summary_out = {
#                 "page_or_slide": item_number,
#                 "image_path": img_path,
#                 "ocr_text": ocr_text
#             }
#             out_path = os.path.join(
#                 IMG_SUMMARY_DIR, f"{file_basename}_{content_type}{item_number}_img{idx}_summary.json")
#             await save_json_async(summary_out, out_path)
#         else:
       
#             description = await describe_image(img_path, groq_client, model)
#             vision_out = {
#                 "page_or_slide": item_number,
#                 "image_path": img_path,
#                 "description": description
#             }
#             out_path = os.path.join(
#                 IMG_VISION_DIR, f"{file_basename}_{content_type}{item_number}_img{idx}_vision.json")
#             await save_json_async(vision_out, out_path)

#     except Exception as e:
#         print(f"Error processing image {img_path}: {e}")


# async def process_images_from_output_json(output_json_path, groq_client, model):
#     async with aiofiles.open(output_json_path, "r", encoding="utf-8") as f:
#         contents = await f.read()
#         data = json.loads(contents)

#     file_basename = os.path.splitext(os.path.basename(output_json_path))[0]
#     items = data.get("slides") or data.get("pages")
#     content_type = "slide" if "slides" in data else "page"

#     tasks = []
#     for item in items:
#         number = item.get("slide_number") or item.get("page_number")
#         image_paths = item.get("images", [])

#         for idx, img_path in enumerate(image_paths, start=1):
#             tasks.append(process_image(number, idx, img_path, file_basename, content_type, groq_client, model))

#     await asyncio.gather(*tasks)
