#!/usr/bin/env python3
"""EC2 Video Processor - polls S3 for new videos, processes them, uploads results.

Usage:
    # Poll S3 continuously for new videos
    python app.py

    # Process a single local file
    python app.py --file /path/to/video.mp4

    # Process all videos in a local directory
    python app.py --dir /path/to/videos/

    # Override processing mode
    python app.py --mode all
    python app.py --file video.mp4 --mode thumbnails
"""

import argparse
import logging
import shutil
import signal
import sys
import time
from pathlib import Path

from config import Config
from processor import process_video
from s3_client import S3Client

logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("video-processor")

running = True


def handle_shutdown(signum, frame):
    global running
    logger.info("Shutdown signal received, finishing current job...")
    running = False


signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)


def process_and_upload(video_path, s3_client, mode=None):
    """Process a single video and upload results to S3."""
    video_path = Path(video_path)
    video_name = video_path.stem

    output_dir = Config.LOCAL_OUTPUT_DIR / video_name
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        result = process_video(video_path, output_dir, mode=mode)

        s3_prefix = f"{Config.S3_OUTPUT_PREFIX}{video_name}/"
        uploaded = s3_client.upload_directory(output_dir, s3_prefix)

        logger.info(
            "Completed %s: %d files uploaded to s3://%s/%s",
            video_name, uploaded, Config.S3_OUTPUT_BUCKET, s3_prefix,
        )
        return result

    except Exception:
        logger.exception("Failed to process %s", video_path)
        return None
    finally:
        if output_dir.exists():
            shutil.rmtree(output_dir)


def poll_s3(s3_client, mode=None):
    """Continuously poll S3 for new videos and process them."""
    logger.info(
        "Starting S3 poll loop (bucket=%s, prefix=%s, interval=%ds, mode=%s)",
        Config.S3_INPUT_BUCKET, Config.S3_INPUT_PREFIX,
        Config.POLL_INTERVAL_SECONDS, mode or Config.PROCESSING_MODE,
    )

    while running:
        videos = s3_client.list_new_videos()

        if videos:
            logger.info("Found %d new video(s) to process", len(videos))

        for s3_key in videos:
            if not running:
                break

            video_name = Path(s3_key).name
            local_path = Config.LOCAL_INPUT_DIR / video_name

            try:
                s3_client.download_video(s3_key, local_path)
                process_and_upload(local_path, s3_client, mode=mode)
                s3_client.move_to_processed(s3_key)
            except Exception:
                logger.exception("Error processing %s", s3_key)
            finally:
                if local_path.exists():
                    local_path.unlink()

        if running:
            time.sleep(Config.POLL_INTERVAL_SECONDS)

    logger.info("Poll loop stopped")


def process_local_file(file_path, s3_client, mode=None):
    """Process a single local video file."""
    file_path = Path(file_path)
    if not file_path.exists():
        logger.error("File not found: %s", file_path)
        sys.exit(1)
    if file_path.suffix.lower() not in Config.SUPPORTED_EXTENSIONS:
        logger.error("Unsupported format: %s", file_path.suffix)
        sys.exit(1)

    result = process_and_upload(file_path, s3_client, mode=mode)
    if result:
        logger.info("Done. Manifest: %s", result.get("manifest"))
    else:
        sys.exit(1)


def process_local_dir(dir_path, s3_client, mode=None):
    """Process all video files in a local directory."""
    dir_path = Path(dir_path)
    if not dir_path.is_dir():
        logger.error("Directory not found: %s", dir_path)
        sys.exit(1)

    videos = [
        f for f in dir_path.iterdir()
        if f.is_file() and f.suffix.lower() in Config.SUPPORTED_EXTENSIONS
    ]

    if not videos:
        logger.warning("No supported video files found in %s", dir_path)
        return

    logger.info("Found %d video(s) in %s", len(videos), dir_path)

    for video in sorted(videos):
        if not running:
            break
        process_and_upload(video, s3_client, mode=mode)

    logger.info("Batch processing complete")


def main():
    parser = argparse.ArgumentParser(description="EC2 Video Processor")
    parser.add_argument("--file", help="Process a single local video file")
    parser.add_argument("--dir", help="Process all videos in a local directory")
    parser.add_argument(
        "--mode",
        choices=["frames", "thumbnails", "transcode", "all"],
        help="Processing mode (default from .env)",
    )
    args = parser.parse_args()

    Config.LOCAL_INPUT_DIR.mkdir(parents=True, exist_ok=True)
    Config.LOCAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    s3_client = S3Client()

    if args.file:
        process_local_file(args.file, s3_client, mode=args.mode)
    elif args.dir:
        process_local_dir(args.dir, s3_client, mode=args.mode)
    else:
        poll_s3(s3_client, mode=args.mode)


if __name__ == "__main__":
    main()
