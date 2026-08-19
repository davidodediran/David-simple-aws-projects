#!/bin/bash
# Deploy the serverless video processor stack.
# Usage: ./deploy.sh [stack-name]

set -euo pipefail

STACK_NAME="${1:-serverless-video-processor}"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Deploying CloudFormation stack: $STACK_NAME ==="

aws cloudformation deploy \
  --template-file "$SCRIPT_DIR/cloudformation/serverless-video-processor.yaml" \
  --stack-name "$STACK_NAME" \
  --capabilities CAPABILITY_NAMED_IAM \
  --region "$REGION" \
  --no-fail-on-empty-changeset

echo ""
echo "=== Getting stack outputs ==="
OUTPUTS=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --query 'Stacks[0].Outputs' \
  --output json)

API_URL=$(echo "$OUTPUTS" | python3 -c "import sys,json; print([o['OutputValue'] for o in json.load(sys.stdin) if o['OutputKey']=='ApiGatewayURL'][0])")
WEBSITE_BUCKET=$(echo "$OUTPUTS" | python3 -c "import sys,json; print([o['OutputValue'] for o in json.load(sys.stdin) if o['OutputKey']=='WebsiteBucketName'][0])")
PROCESSOR_NAME=$(echo "$OUTPUTS" | python3 -c "import sys,json; print([o['OutputValue'] for o in json.load(sys.stdin) if o['OutputKey']=='ProcessorFunctionName'][0])")
API_NAME=$(echo "$OUTPUTS" | python3 -c "import sys,json; print([o['OutputValue'] for o in json.load(sys.stdin) if o['OutputKey']=='ApiFunctionName'][0])")
CLOUDFRONT_URL=$(echo "$OUTPUTS" | python3 -c "import sys,json; print([o['OutputValue'] for o in json.load(sys.stdin) if o['OutputKey']=='CloudFrontURL'][0])")
WEBSITE_URL=$(echo "$OUTPUTS" | python3 -c "import sys,json; print([o['OutputValue'] for o in json.load(sys.stdin) if o['OutputKey']=='WebsiteURL'][0])")

echo ""
echo "=== Deploying Lambda function code ==="

# Package and deploy processor Lambda
cd "$SCRIPT_DIR/lambda/processor"
zip -j /tmp/processor.zip handler.py
aws lambda update-function-code \
  --function-name "$PROCESSOR_NAME" \
  --zip-file fileb:///tmp/processor.zip \
  --region "$REGION"
echo "Processor Lambda deployed."

# Package and deploy API Lambda
cd "$SCRIPT_DIR/lambda/api"
zip -j /tmp/api.zip handler.py
aws lambda update-function-code \
  --function-name "$API_NAME" \
  --zip-file fileb:///tmp/api.zip \
  --region "$REGION"
echo "API Lambda deployed."

echo ""
echo "=== Deploying frontend ==="

# Inject API URL into frontend
cd "$SCRIPT_DIR/frontend"
sed "s|window.CONFIG_API_URL || ''|'${API_URL}'|g" index.html > /tmp/index-deployed.html
aws s3 cp /tmp/index-deployed.html "s3://$WEBSITE_BUCKET/index.html" \
  --content-type "text/html" \
  --region "$REGION"
echo "Frontend deployed."

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
