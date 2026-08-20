"""Lambda handler triggered by S3 PutObject events on the input bucket.

Reads the processing mode from object metadata, runs ffmpeg, and writes
results to the output bucket. Updates DynamoDB with job status.
"""

import json
import logging
import os
import subprocess
import uuid
from pathlib import Path
from urllib.parse import unquote_plus

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")

OUTPUT_BUCKET = os.environ["OUTPUT_BUCKET"]
TABLE_NAME = os.environ["JOBS_TABLE"]
PRESIGN_EXPIRY = int(os.environ.get("PRESIGN_EXPIRY_SECONDS", "86400"))

TMP_DIR = Path("/tmp")


def handler(event, context):
    table = dynamodb.Table(TABLE_NAME)

    for record in event["Records"]:
        bucket = record["s3"]["bucket"]["name"]
        key = unquote_plus(record["s3"]["object"]["key"])
        size = record["s3"]["object"].get("size", 0)

        # Extract job_id from the S3 key: uploads/{job_id}/filename
        parts = key.split("/")
        if len(parts) >= 3 and parts[0] == "uploads":
            job_id = parts[1]
        else:
            job_id = str(uuid.uuid4())[:8]

        logger.info("Job %s: processing s3://%s/%s (%d bytes)", job_id, bucket, key, size)

        # Read mode from DynamoDB (set by API Lambda at upload time)
        existing = table.get_item(Key={"job_id": job_id}).get("Item", {})
        mode = existing.get("mode", "all")
        original_name = existing.get("original_filename", key.split("/")[-1])

        if mode not in ("frames", "thumbnails", "transcode", "all"):
            mode = "all"

        table.update_item(
            Key={"job_id": job_id},
            UpdateExpression="SET #s = :s, input_size = :sz",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "processing", ":sz": size},
        )

        try:
            outputs = _process(bucket, key, job_id, mode)

            table.update_item(
                Key={"job_id": job_id},
                UpdateExpression="SET #s = :s, outputs = :o, output_count = :c",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":s": "completed",
                    ":o": outputs,
                    ":c": len(outputs),
                },
            )
            logger.info("Job %s: completed with %d outputs", job_id, len(outputs))

        except Exception as e:
            logger.exception("Job %s failed", job_id)
            table.update_item(
                Key={"job_id": job_id},
                UpdateExpression="SET #s = :s, #e = :e",
                ExpressionAttributeNames={"#s": "status", "#e": "error"},
                ExpressionAttributeValues={":s": "failed", ":e": str(e)},
            )

        finally:
            _cleanup(job_id)

    return {"statusCode": 200, "body": "ok"}


def _process(bucket, key, job_id, mode):
    work = TMP_DIR / job_id
    work.mkdir(exist_ok=True)
    input_path = work / "input_video"

    s3.download_file(bucket, key, str(input_path))

    probe = _probe(input_path)
    outputs = []

    if mode in ("frames", "all"):
        outputs.extend(_extract_frames(input_path, work, job_id, probe))

    if mode in ("thumbnails", "all"):
        outputs.extend(_generate_thumbnails(input_path, work, job_id))

    if mode in ("transcode", "all"):
        outputs.extend(_transcode(input_path, work, job_id))

    return outputs


def _probe(path):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                duration_str = stream.get("duration", "0")
                try:
                    duration = float(duration_str)
                except ValueError:
                    duration = 0
                return {
                    "width": stream.get("width", 0),
                    "height": stream.get("height", 0),
                    "duration": duration,
                    "codec": stream.get("codec_name", "unknown"),
                }
    except Exception:
        pass
    return {"width": 0, "height": 0, "duration": 0, "codec": "unknown"}


def _extract_frames(input_path, work_dir, job_id, probe):
    frames_dir = work_dir / "frames"
    frames_dir.mkdir(exist_ok=True)

    duration = probe.get("duration", 0)
    interval = max(1, int(duration / 10)) if duration > 10 else 1

    subprocess.run(
        ["ffmpeg", "-i", str(input_path), "-vf", f"fps=1/{interval}",
         "-q:v", "2", str(frames_dir / "frame_%04d.jpg")],
        capture_output=True, timeout=600,
    )

    return _upload_outputs(frames_dir, job_id, "frames")


def _generate_thumbnails(input_path, work_dir, job_id):
    thumbs_dir = work_dir / "thumbnails"
    thumbs_dir.mkdir(exist_ok=True)

    subprocess.run(
        ["ffmpeg", "-i", str(input_path), "-vf",
         "thumbnail=300,scale=320:-1", "-frames:v", "3",
         "-q:v", "2", str(thumbs_dir / "thumb_%04d.jpg")],
        capture_output=True, timeout=300,
    )

    return _upload_outputs(thumbs_dir, job_id, "thumbnails")


def _transcode(input_path, work_dir, job_id):
    out_dir = work_dir / "transcoded"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{job_id}.mp4"

    subprocess.run(
        ["ffmpeg", "-i", str(input_path), "-c:v", "libx264", "-preset", "fast",
         "-crf", "28", "-c:a", "aac", "-b:a", "128k",
         "-movflags", "+faststart", str(out_path)],
        capture_output=True, timeout=600,
    )

    return _upload_outputs(out_dir, job_id, "transcoded")


def _upload_outputs(directory, job_id, category):
    results = []
    for file_path in sorted(directory.iterdir()):
        if not file_path.is_file():
            continue

        s3_key = f"{job_id}/{category}/{file_path.name}"
        size = file_path.stat().st_size

        content_type = "image/jpeg"
        if file_path.suffix == ".mp4":
            content_type = "video/mp4"
        elif file_path.suffix == ".png":
            content_type = "image/png"

        s3.upload_file(
            str(file_path), OUTPUT_BUCKET, s3_key,
            ExtraArgs={"ContentType": content_type},
        )

        results.append({
            "key": s3_key,
            "filename": file_path.name,
            "category": category,
            "size": size,
            "size_display": _format_size(size),
            "format": file_path.suffix.lstrip(".").upper(),
            "content_type": content_type,
        })

    return results


def _format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{round(size_bytes / 1024, 1)} KB"
    return f"{round(size_bytes / (1024 * 1024), 2)} MB"


def _cleanup(job_id):
    work = TMP_DIR / job_id
    if work.exists():
        import shutil
        shutil.rmtree(work, ignore_errors=True)
