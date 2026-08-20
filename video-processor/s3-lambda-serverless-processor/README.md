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
                     [FFmpeg Layer]
                          |
                          v
                     S3 Output Bucket -> Pre-signed URLs (24h) -> User downloads
```

> Open `architecture.drawio` in [app.diagrams.net](https://app.diagrams.net) for the full diagram with AWS icons.

## Services Used

| Service | Purpose |
|---------|---------|
| **S3** (Website Bucket) | Hosts the static frontend (HTML/CSS/JS) |
| **CloudFront** | HTTPS CDN for the static website |
| **API Gateway** (HTTP API) | REST endpoints for upload URLs and job status |
| **Lambda** (API) | Generates pre-signed upload URLs, returns job status |
| **Lambda** (Processor) | Triggered by S3 events, runs ffmpeg on uploaded videos |
| **Lambda Layer** (FFmpeg) | Static ffmpeg/ffprobe binaries, built by deploy.sh |
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

### Option 1: One-command deploy (recommended)

```bash
chmod +x deploy.sh
./deploy.sh serverless-video-processor eu-west-1
```

This will:
1. Build and publish the FFmpeg Lambda layer (skips if already exists)
2. Deploy the CloudFormation stack
3. Deploy the API and Processor Lambda code
4. Attach the FFmpeg layer to the Processor Lambda
5. Upload the frontend with the API URL injected

### Option 2: AWS CloudShell

If you deployed the CloudFormation template via the AWS Console, you still need to run deploy.sh to upload the Lambda code and frontend. Open CloudShell and run:

```bash
git clone https://github.com/davidodediran/David-simple-aws-projects.git
cd David-simple-aws-projects/video-processor/s3-lambda-serverless-processor
chmod +x deploy.sh
./deploy.sh serverless-video-processor eu-west-1
```

The script detects the existing stack and skips to deploying the code.

### Option 3: Step-by-step (manual)

#### Step 1: Build the FFmpeg Lambda Layer

```bash
# Download and package ffmpeg
mkdir -p /tmp/ffmpeg-layer/bin
curl -sL "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz" -o /tmp/ffmpeg.tar.xz
tar xf /tmp/ffmpeg.tar.xz -C /tmp/ffmpeg-layer/bin --strip-components=1 --no-anchored ffmpeg ffprobe
chmod +x /tmp/ffmpeg-layer/bin/ffmpeg /tmp/ffmpeg-layer/bin/ffprobe

# Zip and publish
cd /tmp/ffmpeg-layer && zip -r9 /tmp/ffmpeg-layer.zip bin/
aws lambda publish-layer-version \
  --layer-name serverless-video-processor-ffmpeg \
  --zip-file fileb:///tmp/ffmpeg-layer.zip \
  --compatible-runtimes python3.12 python3.11 python3.10 \
  --compatible-architectures x86_64 \
  --region eu-west-1 \
  --query 'LayerVersionArn' --output text
```

Note the returned Layer ARN.

#### Step 2: Deploy the CloudFormation stack

```bash
aws cloudformation deploy \
  --template-file cloudformation/serverless-video-processor.yaml \
  --stack-name serverless-video-processor \
  --capabilities CAPABILITY_NAMED_IAM \
  --region eu-west-1
```

#### Step 3: Get the stack outputs

```bash
aws cloudformation describe-stacks \
  --stack-name serverless-video-processor \
  --query 'Stacks[0].Outputs' \
  --output table \
  --region eu-west-1
```

Note the `ApiGatewayURL`, `WebsiteBucketName`, `ProcessorFunctionName`, and `ApiFunctionName`.

#### Step 4: Deploy Lambda code

```bash
# Processor Lambda
cd lambda/processor
zip -j /tmp/processor.zip handler.py
aws lambda update-function-code \
  --function-name serverless-video-processor-processor \
  --zip-file fileb:///tmp/processor.zip \
  --region eu-west-1
aws lambda wait function-updated \
  --function-name serverless-video-processor-processor \
  --region eu-west-1

# Attach FFmpeg layer (use the ARN from Step 1)
aws lambda update-function-configuration \
  --function-name serverless-video-processor-processor \
  --layers "arn:aws:lambda:eu-west-1:ACCOUNT_ID:layer:serverless-video-processor-ffmpeg:1" \
  --region eu-west-1

# API Lambda
cd ../api
zip -j /tmp/api.zip handler.py
aws lambda update-function-code \
  --function-name serverless-video-processor-api \
  --zip-file fileb:///tmp/api.zip \
  --region eu-west-1
```

#### Step 5: Deploy the frontend

Replace `YOUR_API_URL` with the `ApiGatewayURL` from Step 3:

```bash
sed "s|window.CONFIG_API_URL || ''|'https://YOUR_API_ID.execute-api.eu-west-1.amazonaws.com'|g" \
  frontend/index.html > /tmp/index-deployed.html

aws s3 cp /tmp/index-deployed.html \
  s3://serverless-video-processor-website-ACCOUNT_ID/index.html \
  --content-type "text/html" \
  --region eu-west-1
```

#### Step 6: Open the website

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
aws cloudformation delete-stack --stack-name serverless-video-processor --region eu-west-1
```

The stack includes a cleanup Lambda that empties all S3 buckets automatically before deletion.

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
  architecture.drawio                 # AWS architecture diagram (draw.io)
  README.md
```
