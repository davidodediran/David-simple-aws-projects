FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py config.py processor.py s3_client.py web.py ./
COPY templates/ templates/

RUN mkdir -p /app/input /app/output /app/static

ENV LOCAL_INPUT_DIR=/app/input \
    LOCAL_OUTPUT_DIR=/app/output \
    PROCESSING_MODE=frames \
    FRAME_INTERVAL=1 \
    THUMBNAIL_WIDTH=320 \
    THUMBNAIL_HEIGHT=240 \
    TRANSCODE_FORMAT=mp4 \
    TRANSCODE_CODEC=libx264 \
    POLL_INTERVAL_SECONDS=30 \
    LOG_LEVEL=INFO

EXPOSE 5000

CMD ["gunicorn", "web:app", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "--timeout", "300"]
