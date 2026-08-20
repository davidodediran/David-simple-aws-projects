# Serverless Image Processor

A fully serverless image processing application using AWS Lambda, S3, and API Gateway. Upload an image through the static website, select a filter, and Lambda processes it - results display on the same page.

## Architecture

```
User -> S3 Website (static frontend)
              |
              v
         API Gateway (HTTP API)
              |
              v
         Lambda (API) -----> S3 Data Bucket (uploads/{job_id}/image.jpg)
                                    |
                              S3 Event Trigger
                                    |
                                    v
                             Lambda (Processor)
                                    |
                              [Pillow filters]
                                    |
                                    v
                             S3 Data Bucket (processed/{job_id}/filter.jpg)
                                    |
                              Pre-signed URLs
                                    |
                                    v
                             Frontend displays results
```

### Flow

1. User uploads image and selects a filter on the static site
2. Frontend calls `POST /upload` - API Lambda returns a pre-signed PUT URL for `uploads/{job_id}/`
3. Frontend uploads the image directly to S3 using the pre-signed URL
4. S3 event on `uploads/` prefix triggers the Processor Lambda
5. Processor Lambda reads the image, applies Pillow filters, writes results to `processed/{job_id}/`
6. Frontend polls `GET /job/{job_id}` until results appear
7. API Lambda lists `processed/{job_id}/` and returns pre-signed download URLs
8. Frontend displays the processed images below the upload section

### Networking

- Both Lambdas run inside a VPC with private subnets
- S3 traffic flows through a VPC Gateway Endpoint (AWS PrivateLink)
- CloudWatch Logs delivered via a VPC Interface Endpoint
- No NAT Gateway needed

## Services Used

| Service | Purpose |
|---------|---------|
| **S3** (Website) | Hosts the static frontend |
| **S3** (Data) | Stores uploads and processed images (two prefixes, one bucket) |
| **API Gateway** (HTTP API) | Routes to API Lambda |
| **Lambda** (API) | Generates pre-signed upload URLs, returns job status and result URLs |
| **Lambda** (Processor) | Triggered by S3 event, processes images with Pillow |
| **Lambda** (Cleanup) | Empties S3 buckets on stack deletion |
| **VPC** | Private network with S3 Gateway Endpoint |

## Processing Filters

| Filter | Description |
|--------|-------------|
| **Grayscale** | Convert to black and white |
| **Thumbnail** | Resize to 300px max dimension |
| **Blur** | Gaussian blur |
| **Sepia** | Warm sepia tone |
| **Sharpen** | Sharpen details |
| **Edges** | Edge detection |
| **Rotate** | Rotate 90 degrees clockwise |
| **All** | Apply all filters at once |

## Deployment

```bash
chmod +x deploy.sh
./deploy.sh
```

With a custom stack name and region:

```bash
./deploy.sh my-image-processor eu-west-1
```

## Usage

1. Open the Website URL printed at the end of deployment
2. Drag and drop an image (or click to browse)
3. Select a filter from the dropdown
4. Click **Upload & Process**
5. Results appear below - click any image to view full size, or download

## Cleanup

The stack includes a cleanup Lambda that empties all buckets automatically:

```bash
aws cloudformation delete-stack --stack-name image-processor
```

## Project Structure

```
image-processor/
  cloudformation/
    image-processor.yaml       # Full infrastructure template
  frontend/
    index.html                 # Static website (upload + results)
  lambda/
    api/
      handler.py               # API Lambda (upload URLs, job status)
    processor/
      handler.py               # Processor Lambda (Pillow, S3 event)
  deploy.sh                    # One-command deployment
  architecture.drawio          # AWS architecture diagram
  README.md
```
