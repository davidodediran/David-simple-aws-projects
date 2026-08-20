# Serverless Video Processor (S3 + Lambda)

A fully serverless video processing application using AWS Lambda, S3, API Gateway, DynamoDB, and CloudFront. Upload a video through the web UI, select a processing mode, and Lambda automatically processes it when it lands in S3.

## Architecture

```
User -> CloudFront -> S3 (static website)
                          |
                          v
                     API Gateway -> Lambda (API)
                          |              |
                          v              v
                     S3 Input       DynamoDB (jobs)
                     Bucket              ^
                          |              |
                     S3 Event            |
                          |              |
                          v              |
                     Lambda (Processor) -+
                          |
                          v
                     S3 Output Bucket -> Pre-signed URLs (24h) -> User downloads
```

## Services Used

| Service | Purpose |
|---------|---------|
| **S3** (Website Bucket) | Hosts the static frontend (HTML/CSS/JS) |
| **CloudFront** | HTTPS CDN for the static website |
| **API Gateway** (HTTP API) | REST endpoints for upload URLs and job status |
| **Lambda** (API) | Generates pre-signed upload URLs, returns job status |
| **Lambda** (Processor) | Triggered by S3 events, runs ffmpeg on uploaded videos |
| **S3** (Input Bucket) | Receives uploaded videos, triggers Lambda |
| **S3** (Output Bucket) | Stores processed results (frames, thumbnails, transcoded video) |
| **DynamoDB** | Tracks job status and output metadata |

## Processing Modes

| Mode | Description | Output |
|------|-------------|--------|
| **frames** | Extract frames at regular intervals | JPG images |
| **thumbnails** | Generate representative thumbnails | JPG images |
| **transcode** | Re-encode to H.264/AAC MP4 (compressed) | MP4 video |
| **all** | Run all three modes | All of the above |

## Prerequisites

- AWS CLI configured with appropriate permissions
- Python 3.12+
- An AWS account

## Deployment

### Option 1: One-command deploy

```bash
chmod +x deploy.sh
./deploy.sh
```

This will:
1. Create the CloudFormation stack (S3 buckets, Lambda functions, API Gateway, DynamoDB, CloudFront)
2. Deploy the Lambda function code
3. Deploy the frontend with the API URL injected

### Option 2: Step-by-step

#### Step 1: Deploy the CloudFormation stack

```bash
aws cloudformation deploy \
  --template-file cloudformation/serverless-video-processor.yaml \
  --stack-name serverless-video-processor \
  --capabilities CAPABILITY_NAMED_IAM
```

#### Step 2: Get the stack outputs

```bash
aws cloudformation describe-stacks \
  --stack-name serverless-video-processor \
  --query 'Stacks[0].Outputs' \
  --output table
```

Note the `ApiGatewayURL`, `WebsiteBucketName`, `ProcessorFunctionName`, and `ApiFunctionName`.

#### Step 3: Deploy Lambda code

```bash
# Processor Lambda
cd lambda/processor
zip -j /tmp/processor.zip handler.py
aws lambda update-function-code \
  --function-name serverless-video-processor-processor \
  --zip-file fileb:///tmp/processor.zip

# API Lambda
cd ../api
zip -j /tmp/api.zip handler.py
aws lambda update-function-code \
  --function-name serverless-video-processor-api \
  --zip-file fileb:///tmp/api.zip
```

#### Step 4: Deploy the frontend

Edit `frontend/index.html` and set the API URL:

```javascript
const API_URL = 'https://your-api-id.execute-api.YOUR_REGION.amazonaws.com';
```

Upload to the website bucket:

```bash
aws s3 cp frontend/index.html s3://serverless-video-processor-website-ACCOUNT_ID/index.html \
  --content-type "text/html"
```

#### Step 5: Open the website

Use the S3 website URL or CloudFront URL from the stack outputs.

## Usage

1. Open the web UI in your browser
2. Drag and drop a video file (or click to browse)
3. Select a processing mode (frames, thumbnails, transcode, or all)
4. Click **Upload & Process**
5. Wait for Lambda to finish processing (progress shown in UI)
6. View results - click **View** to see all outputs with download links
7. Download files using the pre-signed URLs (valid for 24 hours)

## Limits

| Limit | Value | Notes |
|-------|-------|-------|
| Max upload size | 500 MB | Frontend enforced; can increase |
| Lambda timeout | 15 min | Maximum Lambda execution time |
| Lambda ephemeral storage | 10 GB | Temp space for ffmpeg processing |
| Lambda memory | 3 GB | Allocated for ffmpeg performance |
| Pre-signed URL expiry | 24 hours | Configurable via `PresignExpirySeconds` parameter |
| Output retention | 30 days | S3 lifecycle rule on output bucket |
| Input retention | 7 days | S3 lifecycle rule on input bucket |

## FFmpeg Lambda Layer

The template uses a public ffmpeg Lambda layer by default. To use your own:

```bash
aws cloudformation deploy \
  --template-file cloudformation/serverless-video-processor.yaml \
  --stack-name serverless-video-processor \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides FFmpegLayerArn=arn:aws:lambda:YOUR_REGION:123456789:layer:ffmpeg:1
```

## Cost Estimate

This is a pay-per-use architecture. When idle, costs are near zero.

| Component | Cost driver |
|-----------|-------------|
| Lambda (Processor) | ~$0.05 per GB-second (3GB, up to 15 min per video) |
| Lambda (API) | ~$0.20 per 1M requests |
| S3 | ~$0.023/GB/month storage + request costs |
| DynamoDB | Pay-per-request, pennies for typical usage |
| CloudFront | ~$0.085/GB transfer |
| API Gateway | ~$1.00 per 1M requests |

## Cleanup

```bash
# Empty all buckets first
aws s3 rm s3://serverless-video-processor-input-ACCOUNT_ID --recursive
aws s3 rm s3://serverless-video-processor-output-ACCOUNT_ID --recursive
aws s3 rm s3://serverless-video-processor-website-ACCOUNT_ID --recursive

# Delete the stack
aws cloudformation delete-stack --stack-name serverless-video-processor
```

## Project Structure

```
s3-lambda-serverless-processor/
  cloudformation/
    serverless-video-processor.yaml   # Full infrastructure template
  frontend/
    index.html                        # Static website (upload UI + results viewer)
  lambda/
    api/
      handler.py                      # API Lambda (upload URLs, job status)
    processor/
      handler.py                      # Processor Lambda (ffmpeg, S3 events)
  deploy.sh                           # One-command deployment script
  README.md
```
