import json
import logging
import subprocess
from pathlib import Path

import ffmpeg

from config import Config

logger = logging.getLogger(__name__)


def _parse_frame_rate(rate_str):
    """Parse an ffprobe frame rate fraction like '30/1' safely."""
    parts = rate_str.split("/")
    if len(parts) == 2:
        try:
            num, den = int(parts[0]), int(parts[1])
            return num / den if den != 0 else 0.0
        except ValueError:
            return 0.0
    try:
        return float(rate_str)
    except ValueError:
        return 0.0


def get_video_metadata(video_path):
    """Extract video metadata using ffprobe."""
    try:
        probe = ffmpeg.probe(str(video_path))
        video_stream = next(
            (s for s in probe["streams"] if s["codec_type"] == "video"),
            None,
        )
        if not video_stream:
            return None

        duration = float(probe["format"].get("duration", 0))

        return {
            "filename": Path(video_path).name,
            "duration_seconds": duration,
            "width": int(video_stream.get("width", 0)),
            "height": int(video_stream.get("height", 0)),
            "codec": video_stream.get("codec_name", "unknown"),
            "fps": _parse_frame_rate(video_stream.get("r_frame_rate", "0/1")),
            "format": probe["format"].get("format_name", "unknown"),
            "size_bytes": int(probe["format"].get("size", 0)),
        }
    except (ffmpeg.Error, StopIteration):
        logger.exception("Failed to probe %s", video_path)
        return None


def extract_frames(video_path, output_dir, interval=None):
    """Extract frames from video at the configured interval.

    Args:
        video_path: Path to the input video.
        output_dir: Directory to write extracted frames.
        interval: Seconds between extracted frames (default from config).

    Returns:
        List of paths to extracted frame images.
    """
    if interval is None:
        interval = Config.FRAME_INTERVAL

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    output_pattern = str(output_dir / "frame_%06d.jpg")

    try:
        (
            ffmpeg
            .input(str(video_path))
            .filter("fps", fps=1 / interval)
            .output(output_pattern, qscale=2)
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
    except ffmpeg.Error as e:
        logger.error("Frame extraction failed: %s", e.stderr.decode() if e.stderr else str(e))
        raise

    frames = sorted(output_dir.glob("frame_*.jpg"))
    logger.info("Extracted %d frames from %s (interval=%ds)", len(frames), video_path, interval)
    return frames


def generate_thumbnails(video_path, output_dir):
    """Generate thumbnail images at regular intervals throughout the video."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata = get_video_metadata(video_path)
    if not metadata:
        raise ValueError(f"Cannot read metadata from {video_path}")

    duration = metadata["duration_seconds"]
    thumb_count = max(1, int(duration / 10))
    timestamps = [i * (duration / thumb_count) for i in range(thumb_count)]

    thumbnails = []
    for i, ts in enumerate(timestamps):
        output_path = output_dir / f"thumb_{i:04d}.jpg"
        try:
            (
                ffmpeg
                .input(str(video_path), ss=ts)
                .filter("scale", Config.THUMBNAIL_WIDTH, Config.THUMBNAIL_HEIGHT)
                .output(str(output_path), vframes=1, qscale=2)
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )
            thumbnails.append(output_path)
        except ffmpeg.Error as e:
            logger.warning("Thumbnail at %.1fs failed: %s", ts, e.stderr.decode() if e.stderr else str(e))

    logger.info("Generated %d thumbnails from %s", len(thumbnails), video_path)
    return thumbnails


def transcode_video(video_path, output_dir):
    """Transcode video to the configured format and codec."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    stem = Path(video_path).stem
    output_path = output_dir / f"{stem}.{Config.TRANSCODE_FORMAT}"

    try:
        (
            ffmpeg
            .input(str(video_path))
            .output(
                str(output_path),
                vcodec=Config.TRANSCODE_CODEC,
                acodec="aac",
                movflags="faststart",
            )
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
    except ffmpeg.Error as e:
        logger.error("Transcoding failed: %s", e.stderr.decode() if e.stderr else str(e))
        raise

    logger.info("Transcoded %s -> %s", video_path, output_path)
    return output_path


def process_video(video_path, output_base_dir, mode=None):
    """Run the configured processing pipeline on a single video.

    Args:
        video_path: Path to the input video.
        output_base_dir: Base directory for all outputs for this video.
        mode: Processing mode - 'frames', 'thumbnails', 'transcode', or 'all'.

    Returns:
        Dict with metadata and paths to all generated outputs.
    """
    if mode is None:
        mode = Config.PROCESSING_MODE

    video_path = Path(video_path)
    output_base_dir = Path(output_base_dir)
    video_name = video_path.stem

    result = {
        "source": str(video_path),
        "video_name": video_name,
        "metadata": get_video_metadata(video_path),
        "outputs": {},
    }

    if mode in ("frames", "all"):
        frames_dir = output_base_dir / "frames"
        frames = extract_frames(video_path, frames_dir)
        result["outputs"]["frames"] = {
            "directory": str(frames_dir),
            "count": len(frames),
        }

    if mode in ("thumbnails", "all"):
        thumbs_dir = output_base_dir / "thumbnails"
        thumbnails = generate_thumbnails(video_path, thumbs_dir)
        result["outputs"]["thumbnails"] = {
            "directory": str(thumbs_dir),
            "count": len(thumbnails),
        }

    if mode in ("transcode", "all"):
        transcode_dir = output_base_dir / "transcoded"
        transcoded = transcode_video(video_path, transcode_dir)
        result["outputs"]["transcoded"] = {
            "path": str(transcoded),
            "size_bytes": transcoded.stat().st_size,
        }

    manifest_path = output_base_dir / "manifest.json"
    manifest_path.write_text(json.dumps(result, indent=2, default=str))
    result["manifest"] = str(manifest_path)

    logger.info("Processing complete for %s (mode=%s)", video_name, mode)
    return result
