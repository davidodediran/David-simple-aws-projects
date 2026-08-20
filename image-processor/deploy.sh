#!/bin/bash
set -euo pipefail

STACK_NAME="${1:-image-processor}"
REGION="${2:-${AWS_DEFAULT_REGION:-us-east-1}}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Image Processor Deployment ==="
echo "Stack:  $STACK_NAME"
echo "Region: $REGION"
echo ""

get_output() {
  aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" \
    --output text \
    --no-cli-pager
}

# Step 1: Deploy CloudFormation stack
echo "--- Step 1: Deploying CloudFormation stack ---"
aws cloudformation deploy \
  --template-file "$SCRIPT_DIR/cloudformation/image-processor.yaml" \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --capabilities CAPABILITY_NAMED_IAM \
  --no-cli-pager \
  --parameter-overrides EnvironmentName="$STACK_NAME" \
  || true

echo ""
echo "--- Stack Outputs ---"
aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --query 'Stacks[0].Outputs' \
  --output table \
  --no-cli-pager

# Step 2: Package and deploy Lambda function with Pillow
echo ""
echo "--- Step 2: Packaging Lambda function with Pillow ---"
FUNC_NAME=$(get_output ProcessorFunctionName)
TMPDIR=$(mktemp -d)

pip install Pillow -t "$TMPDIR/package" --quiet --platform manylinux2014_x86_64 --only-binary=:all:
cp "$SCRIPT_DIR/lambda/handler.py" "$TMPDIR/package/"
cd "$TMPDIR/package"
zip -r9 "$TMPDIR/lambda.zip" . -q
cd "$SCRIPT_DIR"

echo "Deploying Lambda code ($FUNC_NAME)..."
aws lambda update-function-code \
  --function-name "$FUNC_NAME" \
  --zip-file "fileb://$TMPDIR/lambda.zip" \
  --region "$REGION" \
  --no-cli-pager \
  --output text \
  --query 'FunctionName'

echo "Waiting for function update to complete..."
aws lambda wait function-updated \
  --function-name "$FUNC_NAME" \
  --region "$REGION"

rm -rf "$TMPDIR"
echo "Lambda deployed."

# Step 3: Deploy frontend with API URL injected
echo ""
echo "--- Step 3: Deploying frontend ---"
API_URL=$(get_output ApiGatewayURL)
WEBSITE_BUCKET=$(get_output WebsiteBucketName)
WEBSITE_URL=$(get_output WebsiteURL)

TMPHTML=$(mktemp)
sed "s|window.CONFIG_API_URL || ''|'${API_URL}'|" "$SCRIPT_DIR/frontend/index.html" > "$TMPHTML"

aws s3 cp "$TMPHTML" "s3://$WEBSITE_BUCKET/index.html" \
  --content-type "text/html" \
  --region "$REGION" \
  --no-cli-pager

rm -f "$TMPHTML"

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Website URL: $WEBSITE_URL"
echo "API URL:     $API_URL"
echo ""
echo "Open the Website URL in your browser to start processing images."
