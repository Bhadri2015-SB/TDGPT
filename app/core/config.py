from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
UPLOAD_ROOT = BASE_DIR / "uploads" / "unprocessed"

FILE_TYPE_MAP = {
    "PDF": [".pdf"],
    "Word": [".doc", ".docx"],
    "PPT": [".ppt", ".pptx"],
    "MD": [".md"],
    "Excel": [".xls", ".xlsx", ".csv"],
    "Image": [".jpg", ".jpeg", ".png", ".gif"],
    "Video": [".mp4", ".avi", ".mov"],
    "SQL": [".sql"]
}


# Create folders if not exist
# for folder in [IMAGE_DIR, DOC_DIR, OTHER_DIR]:
#     folder.mkdir(parents=True, exist_ok=True)
