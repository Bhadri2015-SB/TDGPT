import os
from pathlib import Path
from dotenv import load_dotenv


def is_running_in_docker():
    try:
        with open('/proc/1/cgroup', 'rt') as ifh:
            content = ifh.read()
            return 'docker' in content or 'containerd' in content
    except Exception:
        return False



if not (os.getenv("RUNNING_IN_DOCKER") or is_running_in_docker()):
    load_dotenv()


BASE_DIR = Path(__file__).resolve().parent.parent.parent

UPLOAD_ROOT = BASE_DIR / "uploads" / "unprocessed"
PROCESSED_ROOT = BASE_DIR / "uploads" / "processed"
OUTPUT_DIRECTORY = BASE_DIR / "output"
IMAGE_OUTPUT_DIR = OUTPUT_DIRECTORY / "images"

os.makedirs(OUTPUT_DIRECTORY, exist_ok=True)
os.makedirs(IMAGE_OUTPUT_DIR / "img_summary", exist_ok=True)
os.makedirs(IMAGE_OUTPUT_DIR / "img_vision", exist_ok=True)


FILE_TYPE_MAP = {
    "PDF": [".pdf"],
    "Word": [".doc", ".docx"],
    "PPT": [".ppt", ".pptx"],
    "MD": [".md"],
    "Excel": [".xls", ".xlsx", ".csv"],
    "SQLITE": [".sqlite", ".db", ".sqlite3"],
    "SQL_SCRIPT": [".sql"],
    "JSON": [".json"]
}


MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_ROOT_PASSWORD", "Root")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "tdgpt")


# if is_running_in_docker():
DB_URL = os.getenv("URL_DATABASE")
# else:
#     DB_URL = f"mysql+asyncmy://{MYSQL_USER}:{MYSQL_PASSWORD}@127.0.0.1:3307/{MYSQL_DATABASE}"


print(f"[DEBUG] Using DB URL: {DB_URL}")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY is not set in environment variables.")

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama3-8b-8192")


SAVE_IMAGES = True
CHUNK_SIZE = 500

SECRET_KEY = os.getenv("SECRET_KEY")
ACCESS_TOKEN_EXPIRE_MINUTES = os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES")
ALGORITHM = os.getenv("ALGORITHM")

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
URL_DATABASE = os.getenv("URL_DATABASE")

EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
