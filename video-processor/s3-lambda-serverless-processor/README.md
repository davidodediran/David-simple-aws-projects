# Serverless Video Processor

Build a fully serverless video processing pipeline on AWS. Upload a video through a web UI, and AWS Lambda automatically extracts frames, generates thumbnails, and transcodes it using FFmpeg - all without managing any servers.

**What you will build:**
- A drag-and-drop web interface hosted on S3 + CloudFront
- A REST API (API Gateway + Lambda) that generates secure upload URLs
- An event-driven processor (Lambda + FFmpeg) triggered when a video lands in S3
- A job tracking system (DynamoDB) with real-time status updates

**What you will learn:**
- S3 event notifications triggering Lambda functions
- Pre-signed URLs for secure browser-to-S3 uploads
- Lambda Layers for packaging binary dependencies (FFmpeg)
- CloudFormation infrastructure-as-code deployment
- CloudFront CDN distribution for static websites

## Architecture

```
                         +-----------------+
                         |    CloudFront   |
                         |    (HTTPS CDN)  |
                         +--------+--------+
                                  |
                         +--------v--------+
    User  ------------->  S3 Website Bucket |  (static frontend)
                         +-----------------+
                                  |
                         +--------v--------+
                         |   API Gateway   |  (HTTP API)
                         +--------+--------+
                                  |
                    +-------------+-------------+
                    |                           |
           +--------v--------+        +--------v--------+
           |  Lambda (API)   |        |    DynamoDB     |
           |  - upload URLs  |------->|   (job status)  |
           |  - job status   |        +--------^--------+
           +--------+--------+                 |
                    |                          |
           +--------v--------+                 |
           |  S3 Input Bucket |                |
           +--------+--------+                 |
                    |                          |
              S3 Event Trigger                 |
                    |                          |
           +--------v--------+                 |
           | Lambda Processor |----------------+
           | [FFmpeg Layer]   |
           +--------+--------+
                    |
           +--------v--------+
           | S3 Output Bucket |---> Pre-signed URLs ---> User downloads
           +-----------------+
```

> Open `architecture.drawio` in [app.diagrams.net](https://app.diagrams.net) for the full diagram with AWS icons.

## AWS Services Used

| Service | Purpose |
|---------|---------|
| **S3** (3 buckets) | Website hosting, video input, processed output |
| **CloudFront** | HTTPS CDN for the static website |
| **API Gateway** (HTTP API) | REST endpoints for upload URLs and job status |
| **Lambda** (API function) | Generates pre-signed upload URLs, returns job status |
| **Lambda** (Processor function) | Triggered by S3 events, runs FFmpeg on uploaded videos |
| **Lambda Layer** (FFmpeg) | Static FFmpeg/FFprobe binaries for video processing |
| **DynamoDB** | Tracks job status, processing mode, and output metadata |
| **IAM** | Least-privilege roles for each Lambda function |
| **CloudFormation** | Infrastructure-as-code for the entire stack |

## Processing Modes

| Mode | What it does | Output |
|------|-------------|--------|
| **frames** | Extracts frames at regular intervals from the video | JPG images |
| **thumbnails** | Picks 3 representative thumbnails using scene detection | JPG images |
| **transcode** | Re-encodes to H.264/AAC MP4 with compression | MP4 video |
| **all** | Runs all three modes at once | All of the above |

## Prerequisites

- An AWS account (free tier eligible for most services)
- AWS CLI configured (`aws configure`) or AWS CloudShell
- Basic familiarity with the AWS Console

## Tutorial: Deploy Step by Step

You have two paths to deploy. **CloudShell** is the easiest if you are new to AWS.

### Path A: Deploy from CloudShell (Recommended for beginners)

CloudShell is a browser-based terminal built into the AWS Console. No local setup needed.

#### Step 1: Open CloudShell

1. Log in to the [AWS Console](https://console.aws.amazon.com)
2. Select your preferred region (e.g., **EU (Ireland) eu-west-1**) from the top-right dropdown
3. Click the **CloudShell** icon (terminal icon) in the top navigation bar
4. Wait for the shell to initialize

#### Step 2: Clone the repository

```bash
git clone https://github.com/davidodediran/David-simple-aws-projects.git
cd David-simple-aws-projects/video-processor/s3-lambda-serverless-processor
```

#### Step 3: Run the deployment script

```bash
chmod +x deploy.sh
./deploy.sh my-video-processor eu-west-1
```

> Replace `my-video-processor` with any name you like - this becomes your CloudFormation stack name. Replace `eu-west-1` with your chosen region.

The script runs 5 steps automatically:

| Step | What happens | Time |
|------|-------------|------|
| 1/5 | Downloads FFmpeg, packages it as a Lambda Layer, uploads to S3 | ~2 min |
| 2/5 | Deploys the CloudFormation stack (all infrastructure) | ~3 min |
| 3/5 | Reads the stack outputs (API URL, bucket names, etc.) | ~5 sec |
| 4/5 | Deploys Lambda function code and attaches the FFmpeg layer | ~30 sec |
| 5/5 | Injects the API URL into the frontend and uploads to S3 | ~10 sec |

#### Step 4: Open your app

When the script finishes, it prints two URLs:

```
Website (S3):     http://my-video-processor-website-123456789012.s3-website-eu-west-1.amazonaws.com
Website (HTTPS):  https://d1abc2def3ghij.cloudfront.net
```

- Use the **S3 URL** immediately - it works right away
- The **CloudFront URL** (HTTPS) may take 5-10 minutes to propagate on first deploy

#### Step 5: Upload a video

1. Open the website URL in your browser
2. Drag and drop a video file (or click to browse)
3. Select a processing mode (start with **thumbnails** for a quick test)
4. Click **Upload & Process**
5. Watch the status update from Pending to Processing to Completed
6. Click **View** to see results and download them

### Path B: Deploy from your local machine

#### Prerequisites

- AWS CLI installed and configured (`aws configure`)
- Git, Python 3.10+, and `curl` available

#### Deploy

```bash
git clone https://github.com/davidodediran/David-simple-aws-projects.git
cd David-simple-aws-projects/video-processor/s3-lambda-serverless-processor
chmod +x deploy.sh
./deploy.sh my-video-processor eu-west-1
```

The script handles everything. See Path A Step 3 above for what each step does.

### Path C: Deploy CloudFormation via the Console + code via CloudShell

If you prefer to create the stack through the AWS Console UI:

1. Go to **CloudFormation** in the AWS Console
2. Click **Create stack** > **With new resources**
3. Upload `cloudformation/serverless-video-processor.yaml`
4. Stack name: `my-video-processor` (or any name)
5. Leave parameters as defaults, click **Next** through the pages
6. Check **I acknowledge that AWS CloudFormation might create IAM resources with custom names**
7. Click **Submit** and wait for `CREATE_COMPLETE`

Then open **CloudShell** to deploy the code (the CloudFormation template only creates infrastructure, not the Lambda code or frontend):

```bash
git clone https://github.com/davidodediran/David-simple-aws-projects.git
cd David-simple-aws-projects/video-processor/s3-lambda-serverless-processor
chmod +x deploy.sh
./deploy.sh my-video-processor eu-west-1
```

> Use the same stack name you chose in the Console. The script detects the existing stack and skips infrastructure creation - it only deploys the code.

## How It Works

Here is the flow from upload to download:

```
1. User drops a video file on the web UI
2. Frontend calls POST /upload with filename and processing mode
3. API Lambda creates a DynamoDB job record (status: pending)
4. API Lambda generates a pre-signed S3 PUT URL and returns it
5. Frontend uploads the video directly to S3 using the pre-signed URL
6. S3 fires an event notification to the Processor Lambda
7. Processor Lambda downloads the video, runs FFmpeg, uploads results
8. Processor Lambda updates DynamoDB (status: completed, output list)
9. Frontend polls GET /job/{id} and displays results with download links
```

### Key design decisions

- **Pre-signed URLs** let the browser upload directly to S3, avoiding the API Gateway 10MB payload limit
- **Regional S3 endpoints** prevent 307 redirects that break browser CORS
- **DynamoDB stores job metadata** instead of S3 object metadata, keeping pre-signed URLs simple and avoiding signature mismatches
- **FFmpeg is packaged as a Lambda Layer** so it can be reused across functions and updated independently
- **The layer is uploaded to S3 first** because Lambda's direct upload limit is 50MB and the FFmpeg binary is ~70MB

## Redeploying After Code Changes

If you modify the Lambda code or frontend, redeploy with the same command:

```bash
./deploy.sh my-video-processor eu-west-1
```

The script skips the FFmpeg layer build if it already exists and uses `--no-fail-on-empty-changeset` for CloudFormation, so redeployments are fast.

## Limits

| Limit | Value | Notes |
|-------|-------|-------|
| Max upload size | 500 MB | Frontend enforced; adjustable in index.html |
| Lambda timeout | 15 min | Maximum Lambda execution time |
| Lambda ephemeral storage | 10 GB | Temp space for FFmpeg processing |
| Lambda memory | 3 GB | Allocated for FFmpeg performance |
| Pre-signed URL expiry | 24 hours | Configurable via `PresignExpirySeconds` parameter |
| Output retention | 30 days | S3 lifecycle rule on output bucket |
| Input retention | 7 days | S3 lifecycle rule on input bucket |

## Cost Estimate

This is a pay-per-use architecture. When idle, costs are effectively zero.

| Component | Pricing | Example |
|-----------|---------|---------|
| Lambda (Processor) | ~$0.05 per GB-second | 3GB x 60s = ~$0.003 per video |
| Lambda (API) | ~$0.20 per 1M requests | Negligible for personal use |
| S3 Storage | ~$0.023/GB/month | 1GB stored = ~$0.02/month |
| DynamoDB | Pay-per-request | Pennies for typical usage |
| CloudFront | ~$0.085/GB transfer | 1GB served = ~$0.09 |
| API Gateway | ~$1.00 per 1M requests | Negligible for personal use |

**Typical cost for processing 10 short videos:** less than $0.10

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| 404 Not Found on website | Frontend not deployed | Run `./deploy.sh` - steps 4 and 5 upload the code |
| "Error: Failed to get upload URL" | API Lambda missing permissions | Check the stack deployed successfully; redeploy if needed |
| "Error: Upload failed" (CORS) | S3 returning 307 redirect | Ensure you are running the latest code with regional S3 endpoint |
| Video stuck on "Processing" | Processor Lambda timeout or error | Check CloudWatch Logs for the processor function |
| CloudFront shows old version | CDN cache | Wait 5-10 min, or create an invalidation in the CloudFront console |

### Checking Lambda logs

```bash
# API Lambda logs
aws logs tail /aws/lambda/my-video-processor-api --follow --region eu-west-1

# Processor Lambda logs
aws logs tail /aws/lambda/my-video-processor-processor --follow --region eu-west-1
```

## Cleanup

Delete everything when you are done to avoid charges:

```bash
aws cloudformation delete-stack --stack-name my-video-processor --region eu-west-1
```

This removes all resources including S3 buckets, Lambda functions, DynamoDB table, API Gateway, and CloudFront distribution.

Also clean up the FFmpeg layer bucket (created outside CloudFormation):

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws s3 rb s3://my-video-processor-layers-${ACCOUNT_ID} --force --region eu-west-1
aws lambda delete-layer-version --layer-name my-video-processor-ffmpeg --version-number 1 --region eu-west-1
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
      handler.py                      # API Lambda (pre-signed URLs, job status)
    processor/
      handler.py                      # Processor Lambda (FFmpeg processing)
  deploy.sh                           # One-command deployment script
  architecture.drawio                 # AWS architecture diagram (open in draw.io)
  README.md
```
