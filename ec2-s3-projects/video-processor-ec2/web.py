#!/usr/bin/env python3
"""Flask web UI for the EC2 Video Processor."""

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, url_for
from PIL import Image

from config import Config
from processor import get_video_metadata, process_video
from s3_client import S3Client

logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("video-processor-web")

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2 GB upload limit

s3_client = S3Client()

# In-memory job tracker (use a database for production at scale)
jobs = {}


def _format_size(size_bytes):
    """Return a human-friendly size string: bytes, KB, or MB."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{round(size_bytes / 1024, 1)} KB"
    return f"{round(size_bytes / (1024 * 1024), 2)} MB"


def _bytes_to_mb(size_bytes):
    return round(size_bytes / (1024 * 1024), 2)


def _run_processing(job_id, video_path, mode):
    """Background worker that processes a video and uploads results to S3."""
    job = jobs[job_id]
    try:
        job["status"] = "processing"
        job["started_at"] = datetime.now(timezone.utc).isoformat()

        output_dir = Config.LOCAL_OUTPUT_DIR / job_id
        result = process_video(video_path, output_dir, mode=mode)

        s3_prefix = f"{Config.S3_OUTPUT_PREFIX}{job_id}/"
        uploaded = s3_client.upload_directory(output_dir, s3_prefix)

        outputs = []
        for file_path in Path(output_dir).rglob("*"):
            if file_path.is_file() and file_path.name != "manifest.json":
                relative = file_path.relative_to(output_dir)
                s3_key = f"{s3_prefix}{relative}"
                size_bytes = file_path.stat().st_size

                presigned_url = s3_client.s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": Config.S3_OUTPUT_BUCKET, "Key": s3_key},
                    ExpiresIn=3600,
                )

                output_entry = {
                    "filename": str(relative),
                    "s3_key": s3_key,
                    "size_bytes": size_bytes,
                    "size_mb": _bytes_to_mb(size_bytes),
                    "size_display": _format_size(size_bytes),
                    "url": presigned_url,
                    "type": _classify_output(str(relative)),
                    "format": file_path.suffix.lstrip(".").upper(),
                    "dimensions": None,
                }

                if file_path.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp", ".webp"):
                    try:
                        with Image.open(file_path) as img:
                            output_entry["dimensions"] = f"{img.width}x{img.height}"
                    except Exception:
                        pass

                outputs.append(output_entry)

        total_output_bytes = sum(o["size_bytes"] for o in outputs)
        input_bytes = int(job["input_size_mb"] * 1024 * 1024)
        compression_ratio = None
        savings_percent = None
        if input_bytes > 0 and total_output_bytes > 0:
            compression_ratio = round(input_bytes / total_output_bytes, 1)
            savings_percent = round((1 - total_output_bytes / input_bytes) * 100, 1)

        job["status"] = "completed"
        job["completed_at"] = datetime.now(timezone.utc).isoformat()
        job["outputs"] = outputs
        job["files_uploaded"] = uploaded
        job["total_output_mb"] = _bytes_to_mb(total_output_bytes)
        job["total_output_display"] = _format_size(total_output_bytes)
        job["compression_ratio"] = compression_ratio
        job["savings_percent"] = savings_percent
        job["metadata"] = result.get("metadata")
        job["s3_prefix"] = f"s3://{Config.S3_OUTPUT_BUCKET}/{s3_prefix}"

    except Exception as e:
        logger.exception("Job %s failed", job_id)
        job["status"] = "failed"
        job["error"] = str(e)
    finally:
        if Path(video_path).exists():
            Path(video_path).unlink()
        output_dir = Config.LOCAL_OUTPUT_DIR / job_id
        if output_dir.exists():
            import shutil
            shutil.rmtree(output_dir)


def _classify_output(filename):
    filename_lower = filename.lower()
    if "frame" in filename_lower:
        return "frame"
    if "thumb" in filename_lower:
        return "thumbnail"
    if any(filename_lower.endswith(ext) for ext in (".mp4", ".webm", ".avi", ".mkv")):
        return "video"
    return "other"


@app.route("/")
def index():
    sorted_jobs = sorted(jobs.values(), key=lambda j: j["created_at"], reverse=True)
    return render_template("index.html", jobs=sorted_jobs)


@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("video")
    if not file or file.filename == "":
        return redirect(url_for("index"))

    ext = Path(file.filename).suffix.lower()
    if ext not in Config.SUPPORTED_EXTENSIONS:
        return render_template("index.html", jobs=list(jobs.values()),
                               error=f"Unsupported format: {ext}"), 400

    mode = request.form.get("mode", "frames")
    if mode not in ("frames", "thumbnails", "transcode", "all"):
        mode = "frames"

    job_id = str(uuid.uuid4())[:8]
    safe_name = f"{job_id}{ext}"
    local_path = Config.LOCAL_INPUT_DIR / safe_name
    Config.LOCAL_INPUT_DIR.mkdir(parents=True, exist_ok=True)
    file.save(str(local_path))

    input_size = local_path.stat().st_size

    jobs[job_id] = {
        "id": job_id,
        "original_filename": file.filename,
        "mode": mode,
        "status": "queued",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_size_mb": _bytes_to_mb(input_size),
        "input_size_display": _format_size(input_size),
        "outputs": [],
        "total_output_mb": 0,
        "total_output_display": "0 B",
        "compression_ratio": None,
        "savings_percent": None,
        "error": None,
    }

    thread = threading.Thread(target=_run_processing, args=(job_id, str(local_path), mode))
    thread.daemon = True
    thread.start()

    return redirect(url_for("job_detail", job_id=job_id))


@app.route("/job/<job_id>")
def job_detail(job_id):
    job = jobs.get(job_id)
    if not job:
        return "Job not found", 404
    return render_template("job.html", job=job)


@app.route("/api/job/<job_id>")
def api_job_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    return jsonify(job)


if __name__ == "__main__":
    Config.LOCAL_INPUT_DIR.mkdir(parents=True, exist_ok=True)
    Config.LOCAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    app.run(host="0.0.0.0", port=5000, debug=False)
