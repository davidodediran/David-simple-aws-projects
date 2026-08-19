import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class Config:
    AWS_REGION = os.getenv("AWS_REGION", "eu-west-1")
    S3_INPUT_BUCKET = os.getenv("S3_INPUT_BUCKET", "my-video-input-bucket")
    S3_OUTPUT_BUCKET = os.getenv("S3_OUTPUT_BUCKET", "my-video-output-bucket")
    S3_INPUT_PREFIX = os.getenv("S3_INPUT_PREFIX", "raw/")
    S3_OUTPUT_PREFIX = os.getenv("S3_OUTPUT_PREFIX", "processed/")

    LOCAL_INPUT_DIR = Path(os.getenv("LOCAL_INPUT_DIR", "/opt/video-processor/input"))
    LOCAL_OUTPUT_DIR = Path(os.getenv("LOCAL_OUTPUT_DIR", "/opt/video-processor/output"))

    PROCESSING_MODE = os.getenv("PROCESSING_MODE", "frames")
    FRAME_INTERVAL = int(os.getenv("FRAME_INTERVAL", "1"))
    THUMBNAIL_WIDTH = int(os.getenv("THUMBNAIL_WIDTH", "320"))
    THUMBNAIL_HEIGHT = int(os.getenv("THUMBNAIL_HEIGHT", "240"))
    TRANSCODE_FORMAT = os.getenv("TRANSCODE_FORMAT", "mp4")
    TRANSCODE_CODEC = os.getenv("TRANSCODE_CODEC", "libx264")

    POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "30"))
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    SUPPORTED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv", ".webm"}
