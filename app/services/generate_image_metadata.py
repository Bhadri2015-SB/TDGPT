# import os
# import json
# import base64
# from PIL import Image
# import aiofiles
# import pytesseract
# from app.services.image_caption import describe_image
# from app.core.config import OUTPUT_DIRECTORY, GROQ_API_KEY, GROQ_MODEL
# from groq import Groq
# import asyncio
# from app.core.groq_setup import groq_client, GROQ_MODEL

# def encode_image_base64(image_path: str) -> str:
#     with open(image_path, "rb") as img_file:
#         ext = image_path.split('.')[-1].lower()
#         encoded = base64.b64encode(img_file.read()).decode("utf-8")
#         return f"data:image/{ext};base64,{encoded}"

# async def generate_full_image_data_async():
    
#     OUTPUT_JSON_DIR = OUTPUT_DIRECTORY
#     IMG_VISION_DIR = os.path.join(OUTPUT_DIRECTORY, "images", "img_vision")
#     os.makedirs(IMG_VISION_DIR, exist_ok=True)

#     files = [f for f in os.listdir(OUTPUT_JSON_DIR) if f.endswith("_output.json")]

#     for file_name in files:
#         file_path = os.path.join(OUTPUT_JSON_DIR, file_name)

#         async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
#             content = await f.read()
#             data = json.loads(content)

#         content_key = "slides" if "slides" in data else "pages" if "pages" in data else None
#         if not content_key:
#             continue

#         for block in data[content_key]:
#             number = block.get("slide_number") or block.get("page_number")
#             images = block.get("images", [])

#             for idx, img_path in enumerate(images, start=1):
#                 if not os.path.exists(img_path):
#                     print(f" Skipping missing image: {img_path}")
#                     continue

#                 try:
#                     print(f" Processing {img_path}")

                   
#                     base64_image = encode_image_base64(img_path)

#                     ocr_text = pytesseract.image_to_string(Image.open(img_path)).strip()

                  
#                     image_description = await describe_image(img_path, groq_client, GROQ_MODEL)

                 
#                     output_data = {
#                         "page_or_slide": number,
#                         "image_base64": base64_image,
#                         "ocr_text": ocr_text if ocr_text else "No readable text found.",
#                         "image_description": image_description
#                     }

#                     out_name = f"{os.path.splitext(file_name)[0]}_{content_key}{number}_img{idx}_vision.json"
#                     out_path = os.path.join(IMG_VISION_DIR, out_name)

#                     async with aiofiles.open(out_path, "w", encoding="utf-8") as out_f:
#                         await out_f.write(json.dumps(output_data, indent=2, ensure_ascii=False))

#                 except Exception as e:
#                     print(f" Error processing {img_path}: {e}")


# if __name__ == "__main__":
#     asyncio.run(generate_full_image_data_async())
