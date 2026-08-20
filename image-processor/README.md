# Serverless Image Processor

A fully serverless image processing application using AWS Lambda, S3, and API Gateway. Upload an image through the static website, select a processing filter, and Lambda processes it and returns the result - all displayed on the same page.

## Architecture

```
User -> S3 (static website)
         |
         v
    API Gateway (HTTP API)
         |
         v
    Lambda (VPC) --[S3 Gateway Endpoint]--> S3 Output Bucket
         |                                       |
         v                                       v
    Process image (Pillow)              Pre-signed URL -> User views result
```

### Networking

- Lambda runs inside a VPC with private subnets
- S3 traffic flows through a VPC Gateway Endpoint (AWS PrivateLink) - never touches the public internet
- CloudWatch Logs delivered via a VPC Interface Endpoint
- No NAT Gateway needed - keeps costs near zero

## Services Used

| Service | Purpose |
|---------|---------|
| **S3** (Website Bucket) | Hosts the static frontend |
| **S3** (Output Bucket) | Stores processed images (7-day lifecycle) |
| **API Gateway** (HTTP API) | Routes POST /process and GET /results to Lambda |
| **Lambda** (in VPC) | Receives image, applies Pillow filters, uploads results to S3 |
| **VPC** | Private network for Lambda with S3 Gateway Endpoint |
| **Lambda** (Cleanup) | Empties S3 buckets on stack deletion |

## Processing Filters

| Filter | Description | Output |
|--------|-------------|--------|
| **Grayscale** | Convert to black and white | JPG |
| **Thumbnail** | Resize to 300px max dimension | JPG |
| **Blur** | Gaussian blur (radius 5) | JPG |
| **Sepia** | Warm sepia tone | JPG |
| **Sharpen** | Sharpen details | JPG |
| **Edges** | Edge detection | PNG |
| **Rotate** | Rotate 90 degrees clockwise | JPG |
| **All** | Apply all filters | All of the above |

## Prerequisites

- AWS CLI configured with appropriate permissions
- Python 3.12+ with pip
- An AWS account

## Deployment

### One-command deploy

```bash
chmod +x deploy.sh
./deploy.sh
```

With a custom stack name and region:

```bash
./deploy.sh my-image-processor eu-west-1
```

This will:
1. Create the CloudFormation stack (VPC, S3, Lambda, API Gateway, VPC endpoints)
2. Package and deploy the Lambda function with Pillow
3. Deploy the frontend with the API URL injected

### Usage

1. Open the Website URL printed at the end of deployment
2. Drag and drop an image (or click to browse) - max 6 MB
3. Select a processing filter from the dropdown
4. Click **Upload & Process**
5. View the results below - click any image to view full size
6. Download processed images using the download links (valid for 1 hour)

## Limits

| Limit | Value | Notes |
|-------|-------|-------|
| Max image size | 6 MB | API Gateway payload limit |
| Lambda timeout | 60 seconds | More than enough for image processing |
| Lambda memory | 1 GB | Allocated for Pillow performance |
| Pre-signed URL expiry | 1 hour | Configurable via PresignExpirySeconds |
| Output retention | 7 days | S3 lifecycle rule |

## Cost Estimate

Near-zero when idle. S3 Gateway Endpoint is free.

| Component | Cost driver |
|-----------|-------------|
| Lambda | ~$0.01 per 1000 images processed |
| S3 | ~$0.023/GB/month storage |
| API Gateway | ~$1.00 per 1M requests |
| CloudWatch Logs VPC Endpoint | ~$7/month per AZ (~$14/month total) |

## Cleanup

The stack includes a cleanup Lambda that empties all S3 buckets automatically:

```bash
aws cloudformation delete-stack --stack-name image-processor
```

No need to manually empty buckets first.

## Project Structure

```
image-processor/
  cloudformation/
    image-processor.yaml    # Full infrastructure template
  frontend/
    index.html              # Static website (upload UI + results viewer)
  lambda/
    handler.py              # Image processing Lambda (Pillow)
  deploy.sh                 # One-command deployment script
  README.md
```
