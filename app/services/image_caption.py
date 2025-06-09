import os
import json
import asyncio
import aiofiles
from PIL import Image
import torch
from transformers import VisionEncoderDecoderModel, ViTImageProcessor, AutoTokenizer

caption_model = VisionEncoderDecoderModel.from_pretrained("nlpconnect/vit-gpt2-image-captioning")
feature_extractor = ViTImageProcessor.from_pretrained("nlpconnect/vit-gpt2-image-captioning")
tokenizer = AutoTokenizer.from_pretrained("nlpconnect/vit-gpt2-image-captioning")

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
caption_model.to(device)

async def describe_image(image_path):
    loop = asyncio.get_running_loop()
    try:
 
        image = await loop.run_in_executor(None, lambda: Image.open(image_path).convert("RGB"))
        pixel_values = feature_extractor(images=image, return_tensors="pt").pixel_values.to(device)

        
        output_ids = await loop.run_in_executor(None, lambda: caption_model.generate(pixel_values, max_length=64, num_beams=1))
        description = tokenizer.decode(output_ids[0], skip_special_tokens=True)
        return description
    except Exception as e:
        print(f"Error describing image {image_path}: {e}")
        return "Description unavailable due to error."

async def process_images(image_dir):
    results = []
    loop = asyncio.get_running_loop()
    files = await loop.run_in_executor(None, lambda: os.listdir(image_dir))

    for image_file in files:
        if image_file.lower().endswith((".jpeg", ".png", ".jpg")):
            image_path = os.path.join(image_dir, image_file)
            print(f"Describing image from {image_path}")
            page_number = "Unknown"
            if "slide" in image_file:
                try:
                    page_number = int(image_file.split("slide")[1].split("_")[0])
                except:
                    pass
            caption = await describe_image(image_path)
            results.append({
                "page_or_slide": page_number,
                "image_path": image_path.replace("\\", "/"),
                "description": caption
            })

    os.makedirs("img_vision", exist_ok=True)
    async with aiofiles.open("img_vision/image_descriptions.json", "w", encoding="utf-8") as f:
        await f.write(json.dumps(results, indent=2, ensure_ascii=False))

    print("Image descriptions saved to img_vision/image_descriptions.json")

if __name__ == "__main__":
    asyncio.run(process_images("output/images"))
