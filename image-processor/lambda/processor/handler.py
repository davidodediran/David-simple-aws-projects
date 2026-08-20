import io
import os
import boto3
from PIL import Image, ImageFilter

s3 = boto3.client('s3')
DATA_BUCKET = os.environ['DATA_BUCKET']

FILTERS = {
    'grayscale': lambda img: img.convert('L').convert('RGB'),
    'thumbnail': lambda img: _thumbnail(img),
    'blur': lambda img: img.filter(ImageFilter.GaussianBlur(radius=5)),
    'sepia': lambda img: _sepia(img),
    'sharpen': lambda img: img.filter(ImageFilter.SHARPEN),
    'edges': lambda img: img.filter(ImageFilter.FIND_EDGES),
    'rotate': lambda img: img.rotate(-90, expand=True),
}


def _thumbnail(img):
    copy = img.copy()
    copy.thumbnail((300, 300), Image.LANCZOS)
    return copy


def _sepia(img):
    gray = img.convert('L')
    return Image.merge('RGB', [
        gray.point(lambda p: min(255, int(p * 1.2))),
        gray.point(lambda p: min(255, int(p * 1.0))),
        gray.point(lambda p: min(255, int(p * 0.8))),
    ])


def handler(event, context):
    for record in event.get('Records', []):
        bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']

        if not key.startswith('uploads/'):
            continue

        parts = key.split('/')
        if len(parts) < 3:
            continue
        job_id = parts[1]

        print(f'Processing job {job_id}: {key}')

        head = s3.head_object(Bucket=bucket, Key=key)
        mode = head.get('Metadata', {}).get('processing-mode', 'grayscale')

        obj = s3.get_object(Bucket=bucket, Key=key)
        image_bytes = obj['Body'].read()
        img = Image.open(io.BytesIO(image_bytes)).convert('RGB')

        if mode == 'all':
            filters_to_run = FILTERS
        elif mode in FILTERS:
            filters_to_run = {mode: FILTERS[mode]}
        else:
            print(f'Unknown mode: {mode}, defaulting to grayscale')
            filters_to_run = {'grayscale': FILTERS['grayscale']}

        for filter_name, filter_fn in filters_to_run.items():
            result = filter_fn(img)

            buf = io.BytesIO()
            fmt = 'PNG' if filter_name == 'edges' else 'JPEG'
            ext = 'png' if fmt == 'PNG' else 'jpg'
            result.save(buf, format=fmt, quality=85)
            buf.seek(0)

            out_key = f'processed/{job_id}/{filter_name}.{ext}'
            s3.put_object(
                Bucket=DATA_BUCKET,
                Key=out_key,
                Body=buf.getvalue(),
                ContentType=f'image/{ext}',
            )
            print(f'Wrote {out_key} ({buf.getbuffer().nbytes} bytes)')

    return {'statusCode': 200}
