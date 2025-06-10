import os
from pathlib import Path
from dotenv import load_dotenv


load_dotenv()


BASE_DIR = Path(__file__).resolve().parent.parent.parent


UPLOAD_ROOT = BASE_DIR / "uploads" / "unprocessed"
PROCESSED_ROOT = BASE_DIR / "uploads" / "processed"
OUTPUT_DIRECTORY = BASE_DIR / "output"
IMAGE_OUTPUT_DIR = OUTPUT_DIRECTORY / "images"


os.makedirs(OUTPUT_DIRECTORY, exist_ok=True)
os.makedirs(IMAGE_OUTPUT_DIR / "img_summary", exist_ok=True)
os.makedirs(IMAGE_OUTPUT_DIR / "img_vision", exist_ok=True)


SUBFOLDERS = ["PDF", "Xlsx", "pptx", "Markdown"]

FILE_TYPE_MAP = {
    "PDF": [".pdf"],
    "Word": [".doc", ".docx"],
    "PPT": [".ppt", ".pptx"],
    "MD": [".md"],
    "Excel": [".xls", ".xlsx", ".csv"],
    "Image": [".jpg", ".jpeg", ".png", ".gif"],
    "Video": [".mp4", ".avi", ".mov"],
    "SQLITE": [".sqlite", ".db", ".sqlite3"],
    "SQL_SCRIPT": [".sql"],
    "JSON": [".json"]
}


GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY is not set in environment variables.")

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama3-8b-8192")


SAVE_IMAGES = True
CHUNK_SIZE = 500

SECRET_KEY=os.getenv("SECRET_KEY")
ACCESS_TOKEN_EXPIRE_MINUTES=os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES")
ALGORITHM=os.getenv("ALGORITHM")
