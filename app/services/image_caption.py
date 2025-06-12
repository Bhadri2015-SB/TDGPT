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
