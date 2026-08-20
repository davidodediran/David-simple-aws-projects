#!/bin/bash
# Deploy the serverless video processor stack.
# Usage: ./deploy.sh [stack-name] [region]

set -euo pipefail

STACK_NAME="${1:-serverless-video-processor}"
REGION="${2:-${AWS_DEFAULT_REGION:-us-east-1}}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=========================================="
echo "  Serverless Video Processor - Deploy"
echo "  Stack:  $STACK_NAME"
echo "  Region: $REGION"
echo "=========================================="
echo ""

# --- Step 1: Build FFmpeg Lambda Layer ---
echo "=== [1/5] Building FFmpeg Lambda Layer ==="

LAYER_NAME="${STACK_NAME}-ffmpeg"
LAYER_DIR=$(mktemp -d)

# Check if layer already exists in this region
EXISTING_LAYER_ARN=$(aws lambda list-layer-versions \
  --layer-name "$LAYER_NAME" \
  --region "$REGION" \
  --query 'LayerVersions[0].LayerVersionArn' \
  --output text 2>/dev/null || echo "None")

if [ "$EXISTING_LAYER_ARN" != "None" ] && [ -n "$EXISTING_LAYER_ARN" ]; then
  echo "  FFmpeg layer already exists: $EXISTING_LAYER_ARN"
  FFMPEG_LAYER_ARN="$EXISTING_LAYER_ARN"
else
  echo "  Downloading ffmpeg static build..."
  curl -sL "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz" \
    -o "$LAYER_DIR/ffmpeg.tar.xz"

  echo "  Extracting ffmpeg and ffprobe..."
  mkdir -p "$LAYER_DIR/layer/bin"
  tar xf "$LAYER_DIR/ffmpeg.tar.xz" -C "$LAYER_DIR/layer/bin" \
    --strip-components=1 \
    --no-anchored ffmpeg ffprobe
  chmod +x "$LAYER_DIR/layer/bin/ffmpeg" "$LAYER_DIR/layer/bin/ffprobe"

  echo "  Packaging layer zip..."
  cd "$LAYER_DIR/layer"
  zip -r9 "$LAYER_DIR/ffmpeg-layer.zip" bin/ -q
  cd "$SCRIPT_DIR"

  echo "  Publishing Lambda layer..."
  FFMPEG_LAYER_ARN=$(aws lambda publish-layer-version \
    --layer-name "$LAYER_NAME" \
    --description "FFmpeg static build for video processing" \
    --zip-file "fileb://$LAYER_DIR/ffmpeg-layer.zip" \
    --compatible-runtimes python3.12 python3.11 python3.10 \
    --compatible-architectures x86_64 \
    --region "$REGION" \
    --query 'LayerVersionArn' \
    --output text)

  echo "  Published layer: $FFMPEG_LAYER_ARN"
fi

rm -rf "$LAYER_DIR"

# --- Step 2: Deploy CloudFormation stack ---
echo ""
echo "=== [2/5] Deploying CloudFormation stack ==="
aws cloudformation deploy \
  --template-file "$SCRIPT_DIR/cloudformation/serverless-video-processor.yaml" \
  --stack-name "$STACK_NAME" \
  --capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
  --region "$REGION" \
  --no-fail-on-empty-changeset

echo ""
echo "=== [3/5] Reading stack outputs ==="
OUTPUTS=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --query 'Stacks[0].Outputs' \
  --output json)

get_output() {
  echo "$OUTPUTS" | python3 -c "import sys,json; print([o['OutputValue'] for o in json.load(sys.stdin) if o['OutputKey']=='$1'][0])"
}

API_URL=$(get_output ApiGatewayURL)
WEBSITE_BUCKET=$(get_output WebsiteBucketName)
PROCESSOR_NAME=$(get_output ProcessorFunctionName)
API_NAME=$(get_output ApiFunctionName)
CLOUDFRONT_URL=$(get_output CloudFrontURL)
WEBSITE_URL=$(get_output WebsiteURL)

echo "  API Gateway:   $API_URL"
echo "  Website bucket: $WEBSITE_BUCKET"
echo "  Processor:     $PROCESSOR_NAME"
echo "  API function:  $API_NAME"

echo ""
echo "=== [4/5] Deploying Lambda function code ==="

# Package and deploy processor Lambda
cd "$SCRIPT_DIR/lambda/processor"
zip -j /tmp/processor.zip handler.py
aws lambda update-function-code \
  --function-name "$PROCESSOR_NAME" \
  --zip-file fileb:///tmp/processor.zip \
  --region "$REGION" \
  --no-cli-pager
echo "  Processor Lambda deployed."

echo "  Waiting for processor function update..."
aws lambda wait function-updated \
  --function-name "$PROCESSOR_NAME" \
  --region "$REGION"

# Attach FFmpeg layer to processor
echo "  Attaching FFmpeg layer to processor..."
aws lambda update-function-configuration \
  --function-name "$PROCESSOR_NAME" \
  --layers "$FFMPEG_LAYER_ARN" \
  --region "$REGION" \
  --no-cli-pager \
  --output text \
  --query 'FunctionName'
echo "  FFmpeg layer attached."

# Package and deploy API Lambda
cd "$SCRIPT_DIR/lambda/api"
zip -j /tmp/api.zip handler.py
aws lambda update-function-code \
  --function-name "$API_NAME" \
  --zip-file fileb:///tmp/api.zip \
  --region "$REGION" \
  --no-cli-pager
echo "  API Lambda deployed."

echo ""
echo "=== [5/5] Deploying frontend ==="

# Inject API URL into frontend and upload
cd "$SCRIPT_DIR/frontend"
sed "s|window.CONFIG_API_URL || ''|'${API_URL}'|g" index.html > /tmp/index-deployed.html
aws s3 cp /tmp/index-deployed.html "s3://$WEBSITE_BUCKET/index.html" \
  --content-type "text/html" \
  --region "$REGION"
echo "  Frontend deployed to $WEBSITE_BUCKET"

echo ""
echo "=========================================="
echo "  Deployment complete!"
echo "=========================================="
echo ""
echo "  Website (S3):     $WEBSITE_URL"
echo "  Website (HTTPS):  $CLOUDFRONT_URL"
echo "  API Gateway:      $API_URL"
echo ""
echo "  Note: CloudFront may take a few minutes"
echo "  to propagate. Use the S3 URL until then."
echo "=========================================="
