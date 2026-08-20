"""API Gateway Lambda handler for the serverless video processor.

Endpoints:
  POST /upload    - Generate a pre-signed upload URL for the input bucket
  GET  /job/{id}  - Get job status and output pre-signed download URLs
  GET  /jobs      - List recent jobs
"""

import json
import logging
import os
import uuid
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")

INPUT_BUCKET = os.environ["INPUT_BUCKET"]
OUTPUT_BUCKET = os.environ["OUTPUT_BUCKET"]
TABLE_NAME = os.environ["JOBS_TABLE"]
PRESIGN_EXPIRY = int(os.environ.get("PRESIGN_EXPIRY_SECONDS", "86400"))
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "*")


def handler(event, context):
    method = event.get("httpMethod", event.get("requestContext", {}).get("http", {}).get("method", ""))
    path = event.get("path", event.get("rawPath", ""))

    logger.info("%s %s", method, path)

    try:
        if method == "POST" and path == "/upload":
            return _handle_upload(event)
        elif method == "GET" and path.startswith("/job/"):
            job_id = path.split("/job/")[-1]
            return _handle_get_job(job_id)
        elif method == "GET" and path == "/jobs":
            return _handle_list_jobs()
        elif method == "OPTIONS":
            return _cors_response(200, "")
        else:
            return _response(404, {"error": "not found"})
    except Exception as e:
        logger.exception("Handler error")
        return _response(500, {"error": str(e)})


def _handle_upload(event):
    body = json.loads(event.get("body") or "{}")
    filename = body.get("filename", "video.mp4")
    mode = body.get("mode", "all")
    content_type = body.get("content_type", "video/mp4")

    if mode not in ("frames", "thumbnails", "transcode", "all"):
        return _response(400, {"error": f"Invalid mode: {mode}"})

    upload_id = str(uuid.uuid4())[:8]
    s3_key = f"uploads/{upload_id}/{filename}"

    presigned = s3.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": INPUT_BUCKET,
            "Key": s3_key,
            "ContentType": content_type,
        },
        ExpiresIn=3600,
    )

    # Store metadata in DynamoDB instead of S3 object metadata
    # to avoid requiring x-amz-meta-* headers on the client PUT
    table = dynamodb.Table(TABLE_NAME)
    import time
    table.put_item(Item={
        "job_id": upload_id,
        "status": "pending",
        "mode": mode,
        "original_filename": filename,
        "input_key": s3_key,
        "content_type": content_type,
        "created_at": int(time.time()),
        "ttl": int(time.time()) + 86400 * 7,
    })

    return _response(200, {
        "upload_url": presigned,
        "upload_id": upload_id,
        "key": s3_key,
        "content_type": content_type,
        "expires_in": 3600,
    })


def _handle_get_job(job_id):
    table = dynamodb.Table(TABLE_NAME)
    result = table.get_item(Key={"job_id": job_id})
    item = result.get("Item")

    if not item:
        return _response(404, {"error": "job not found"})

    item = _decimal_to_native(item)

    if item.get("status") == "completed" and item.get("outputs"):
        for output in item["outputs"]:
            output["download_url"] = s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": OUTPUT_BUCKET, "Key": output["key"]},
                ExpiresIn=PRESIGN_EXPIRY,
            )

    return _response(200, item)


def _handle_list_jobs():
    table = dynamodb.Table(TABLE_NAME)
    result = table.scan(Limit=50)
    items = [_decimal_to_native(i) for i in result.get("Items", [])]
    items.sort(key=lambda x: x.get("job_id", ""), reverse=True)

    return _response(200, {"jobs": items})


def _decimal_to_native(obj):
    if isinstance(obj, dict):
        return {k: _decimal_to_native(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimal_to_native(i) for i in obj]
    if isinstance(obj, Decimal):
        if obj % 1 == 0:
            return int(obj)
        return float(obj)
    return obj


def _cors_response(status, body):
    return {
        "statusCode": status,
        "headers": {
            "Access-Control-Allow-Origin": ALLOWED_ORIGINS,
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        },
        "body": body if isinstance(body, str) else json.dumps(body),
    }


def _response(status, body):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": ALLOWED_ORIGINS,
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        },
        "body": json.dumps(body),
    }
