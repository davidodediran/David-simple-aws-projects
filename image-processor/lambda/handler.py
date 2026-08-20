import json
import os
import io
import base64
import uuid
import boto3
from PIL import Image, ImageFilter, ImageEnhance

s3 = boto3.client('s3')
OUTPUT_BUCKET = os.environ['OUTPUT_BUCKET']
PRESIGN_EXPIRY = int(os.environ.get('PRESIGN_EXPIRY_SECONDS', '3600'))

MODES = {
    'grayscale': 'Convert to grayscale',
    'thumbnail': 'Resize to 300px thumbnail',
    'blur': 'Apply Gaussian blur',
    'sepia': 'Apply sepia tone filter',
    'sharpen': 'Sharpen the image',
    'edges': 'Detect edges',
    'rotate': 'Rotate 90 degrees clockwise',
    'all': 'Apply all filters',
}


def process_image(image_bytes, mode):
    img = Image.open(io.BytesIO(image_bytes)).convert('RGB')
    results = {}

    def apply_grayscale(src):
        return src.convert('L').convert('RGB')

    def apply_thumbnail(src):
        copy = src.copy()
        copy.thumbnail((300, 300), Image.LANCZOS)
        return copy

    def apply_blur(src):
        return src.filter(ImageFilter.GaussianBlur(radius=5))

    def apply_sepia(src):
        gray = src.convert('L')
        sepia = Image.merge('RGB', [
            gray.point(lambda p: min(255, int(p * 1.2))),
            gray.point(lambda p: min(255, int(p * 1.0))),
            gray.point(lambda p: min(255, int(p * 0.8))),
        ])
        return sepia

    def apply_sharpen(src):
        return src.filter(ImageFilter.SHARPEN)

    def apply_edges(src):
        return src.filter(ImageFilter.FIND_EDGES)

    def apply_rotate(src):
        return src.rotate(-90, expand=True)

    filters = {
        'grayscale': apply_grayscale,
        'thumbnail': apply_thumbnail,
        'blur': apply_blur,
        'sepia': apply_sepia,
        'sharpen': apply_sharpen,
        'edges': apply_edges,
        'rotate': apply_rotate,
    }

    if mode == 'all':
        for name, fn in filters.items():
            results[name] = fn(img)
    elif mode in filters:
        results[mode] = filters[mode](img)
    else:
        raise ValueError(f'Unknown mode: {mode}')

    return results


def handler(event, context):
    method = event.get('requestContext', {}).get('http', {}).get('method', '')
    path = event.get('rawPath', '')

    if method == 'POST' and path == '/process':
        return handle_process(event)
    elif method == 'GET' and path.startswith('/results/'):
        return handle_get_result(event)
    else:
        return response(404, {'error': 'Not found'})


def handle_process(event):
    try:
        body = event.get('body', '')
        is_base64 = event.get('isBase64Encoded', False)

        if is_base64:
            raw = base64.b64decode(body)
        else:
            raw = body.encode() if isinstance(body, str) else body

        content_type = ''
        headers = event.get('headers', {})
        content_type = headers.get('content-type', '')

        if 'multipart/form-data' in content_type or 'application/json' in content_type:
            payload = json.loads(base64.b64decode(body) if is_base64 else body)
            image_data = base64.b64decode(payload['image'])
            mode = payload.get('mode', 'grayscale')
            filename = payload.get('filename', 'image.jpg')
        else:
            return response(400, {'error': 'Send JSON with base64-encoded image'})

        job_id = str(uuid.uuid4())[:8]
        results = process_image(image_data, mode)

        output_files = []
        for filter_name, img in results.items():
            buf = io.BytesIO()
            fmt = 'JPEG' if filter_name != 'edges' else 'PNG'
            ext = 'jpg' if fmt == 'JPEG' else 'png'
            img.save(buf, format=fmt, quality=85)
            buf.seek(0)

            key = f'{job_id}/{filter_name}.{ext}'
            s3.put_object(
                Bucket=OUTPUT_BUCKET,
                Key=key,
                Body=buf.getvalue(),
                ContentType=f'image/{ext}',
            )

            url = s3.generate_presigned_url(
                'get_object',
                Params={'Bucket': OUTPUT_BUCKET, 'Key': key},
                ExpiresIn=PRESIGN_EXPIRY,
            )

            output_files.append({
                'filter': filter_name,
                'key': key,
                'url': url,
                'size_kb': round(buf.getbuffer().nbytes / 1024, 1),
            })

        return response(200, {
            'job_id': job_id,
            'mode': mode,
            'results': output_files,
        })

    except Exception as e:
        print(f'Error processing image: {e}')
        return response(500, {'error': str(e)})


def handle_get_result(event):
    try:
        path = event.get('rawPath', '')
        key = path.replace('/results/', '', 1)

        url = s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': OUTPUT_BUCKET, 'Key': key},
            ExpiresIn=PRESIGN_EXPIRY,
        )
        return response(200, {'url': url})

    except Exception as e:
        return response(500, {'error': str(e)})


def response(status_code, body):
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
        },
        'body': json.dumps(body),
    }
