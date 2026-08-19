import logging
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from config import Config

logger = logging.getLogger(__name__)


class S3Client:
    def __init__(self):
        self.s3 = boto3.client("s3", region_name=Config.AWS_REGION)

    def list_new_videos(self):
        """List video files in the S3 input bucket/prefix."""
        try:
            paginator = self.s3.get_paginator("list_objects_v2")
            pages = paginator.paginate(
                Bucket=Config.S3_INPUT_BUCKET,
                Prefix=Config.S3_INPUT_PREFIX,
            )

            videos = []
            for page in pages:
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    ext = Path(key).suffix.lower()
                    if ext in Config.SUPPORTED_EXTENSIONS:
                        videos.append(key)

            return videos
        except ClientError:
            logger.exception("Failed to list objects in s3://%s/%s", Config.S3_INPUT_BUCKET, Config.S3_INPUT_PREFIX)
            return []

    def download_video(self, s3_key, local_path):
        """Download a video from S3 to the local filesystem."""
        local_path = Path(local_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info("Downloading s3://%s/%s -> %s", Config.S3_INPUT_BUCKET, s3_key, local_path)
        self.s3.download_file(Config.S3_INPUT_BUCKET, s3_key, str(local_path))
        return local_path

    def upload_file(self, local_path, s3_key):
        """Upload a processed file to the S3 output bucket."""
        content_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".mp4": "video/mp4",
            ".webm": "video/webm",
            ".json": "application/json",
        }

        ext = Path(local_path).suffix.lower()
        extra_args = {}
        if ext in content_types:
            extra_args["ContentType"] = content_types[ext]

        logger.info("Uploading %s -> s3://%s/%s", local_path, Config.S3_OUTPUT_BUCKET, s3_key)
        self.s3.upload_file(str(local_path), Config.S3_OUTPUT_BUCKET, s3_key, ExtraArgs=extra_args)

    def upload_directory(self, local_dir, s3_prefix):
        """Upload all files in a local directory to S3 under the given prefix."""
        local_dir = Path(local_dir)
        uploaded = 0

        for file_path in local_dir.rglob("*"):
            if file_path.is_file():
                relative = file_path.relative_to(local_dir)
                s3_key = f"{s3_prefix}{relative}"
                self.upload_file(file_path, s3_key)
                uploaded += 1

        logger.info("Uploaded %d files to s3://%s/%s", uploaded, Config.S3_OUTPUT_BUCKET, s3_prefix)
        return uploaded

    def move_to_processed(self, s3_key):
        """Move a processed video from the input prefix to a 'processed/' prefix to avoid reprocessing."""
        new_key = s3_key.replace(Config.S3_INPUT_PREFIX, f"{Config.S3_INPUT_PREFIX}done/", 1)

        self.s3.copy_object(
            Bucket=Config.S3_INPUT_BUCKET,
            CopySource={"Bucket": Config.S3_INPUT_BUCKET, "Key": s3_key},
            Key=new_key,
        )
        self.s3.delete_object(Bucket=Config.S3_INPUT_BUCKET, Key=s3_key)
        logger.info("Moved %s -> %s", s3_key, new_key)
