import json
import os
import uuid
import boto3

s3 = boto3.client('s3')
DATA_BUCKET = os.environ['DATA_BUCKET']
PRESIGN_EXPIRY = int(os.environ.get('PRESIGN_EXPIRY_SECONDS', '3600'))


def handler(event, context):
    method = event.get('requestContext', {}).get('http', {}).get('method', '')
    path = event.get('rawPath', '')

    if method == 'POST' and path == '/upload':
        return handle_upload(event)
    elif method == 'GET' and path.startswith('/job/'):
        return handle_job_status(event)
    else:
        return response(404, {'error': 'Not found'})


def handle_upload(event):
    try:
        body = json.loads(event.get('body', '{}'))
        filename = body.get('filename', 'image.jpg')
        mode = body.get('mode', 'grayscale')

        job_id = str(uuid.uuid4())[:8]
        key = f'uploads/{job_id}/{filename}'

        upload_url = s3.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': DATA_BUCKET,
                'Key': key,
                'ContentType': 'image/*',
                'Metadata': {'processing-mode': mode},
            },
            ExpiresIn=300,
        )

        return response(200, {
            'job_id': job_id,
            'upload_url': upload_url,
            'key': key,
            'mode': mode,
        })

    except Exception as e:
        print(f'Error: {e}')
        return response(500, {'error': str(e)})


def handle_job_status(event):
    try:
        path = event.get('rawPath', '')
        job_id = path.split('/job/')[-1]

        result = s3.list_objects_v2(
            Bucket=DATA_BUCKET,
            Prefix=f'processed/{job_id}/',
        )

        if result.get('KeyCount', 0) == 0:
            return response(200, {
                'job_id': job_id,
                'status': 'processing',
                'results': [],
            })

        files = []
        for obj in result.get('Contents', []):
            key = obj['Key']
            name = key.split('/')[-1]
            url = s3.generate_presigned_url(
                'get_object',
                Params={'Bucket': DATA_BUCKET, 'Key': key},
                ExpiresIn=PRESIGN_EXPIRY,
            )
            files.append({
                'filter': name.rsplit('.', 1)[0],
                'key': key,
                'url': url,
                'size_kb': round(obj['Size'] / 1024, 1),
            })

        return response(200, {
            'job_id': job_id,
            'status': 'completed',
            'results': files,
        })

    except Exception as e:
        print(f'Error: {e}')
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
