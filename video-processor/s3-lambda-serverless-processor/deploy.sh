#!/bin/bash
# Deploy the serverless video processor stack.
# Usage: ./deploy.sh [stack-name] [region]

set -euo pipefail

STACK_NAME="${1:-serverless-video-processor}"
REGION="${2:-${AWS_DEFAULT_REGION:-eu-west-1}}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=========================================="
echo "  Serverless Video Processor - Deploy"
echo "  Stack:  $STACK_NAME"
echo "  Region: $REGION"
echo "=========================================="
echo ""

echo "=== [1/4] Deploying CloudFormation stack ==="
aws cloudformation deploy \
  --template-file "$SCRIPT_DIR/cloudformation/serverless-video-processor.yaml" \
  --stack-name "$STACK_NAME" \
  --capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
  --region "$REGION" \
  --no-fail-on-empty-changeset

echo ""
echo "=== [2/4] Reading stack outputs ==="
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
echo "=== [3/4] Deploying Lambda function code ==="

# Package and deploy processor Lambda
cd "$SCRIPT_DIR/lambda/processor"
zip -j /tmp/processor.zip handler.py
aws lambda update-function-code \
  --function-name "$PROCESSOR_NAME" \
  --zip-file fileb:///tmp/processor.zip \
  --region "$REGION" \
  --no-cli-pager
echo "  Processor Lambda deployed."

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
echo "=== [4/4] Deploying frontend ==="

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
