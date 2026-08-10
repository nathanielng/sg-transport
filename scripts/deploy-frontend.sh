#!/usr/bin/env bash
# Deploys frontend/index.html with real API_URL/API_KEY values filled in at
# upload time, so the committed source file only ever contains placeholders.
#
# Required env vars (none of these are committed to the repo):
#   STACK_NAME                  CloudFormation stack name (default: bus-stop-finder)
#   AWS_REGION                  e.g. ap-southeast-1
#   S3_DEST                     s3://<bucket>/<key>, e.g. s3://my-bucket/bus/index.html
#   CLOUDFRONT_DISTRIBUTION_ID  (optional) invalidates this path after upload
#
# Usage:
#   STACK_NAME=bus-stop-finder AWS_REGION=ap-southeast-1 \
#   S3_DEST=s3://my-bucket/bus/index.html \
#   CLOUDFRONT_DISTRIBUTION_ID=EXXXXXXXXXXXXX \
#   ./scripts/deploy-frontend.sh

set -euo pipefail

STACK_NAME="${STACK_NAME:-bus-stop-finder}"
: "${AWS_REGION:?Set AWS_REGION, e.g. ap-southeast-1}"
: "${S3_DEST:?Set S3_DEST, e.g. s3://my-bucket/bus/index.html}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_FILE="$SCRIPT_DIR/../frontend/index.html"
BUILD_DIR="$SCRIPT_DIR/../.build"
OUT_FILE="$BUILD_DIR/index.html"

mkdir -p "$BUILD_DIR"

API_URL=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$AWS_REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text)
API_KEY_ID=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$AWS_REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='ApiKeyId'].OutputValue" --output text)
API_KEY=$(aws apigateway get-api-key --api-key "$API_KEY_ID" --include-value --region "$AWS_REGION" \
  --query value --output text)

sed -e "s|__API_URL__|${API_URL}|" -e "s|__API_KEY__|${API_KEY}|" "$SRC_FILE" > "$OUT_FILE"

aws s3 cp "$OUT_FILE" "$S3_DEST" --content-type "text/html" --region "$AWS_REGION"
rm -f "$OUT_FILE"

if [[ -n "${CLOUDFRONT_DISTRIBUTION_ID:-}" ]]; then
  S3_KEY="/${S3_DEST#s3://*/}"
  aws cloudfront create-invalidation --distribution-id "$CLOUDFRONT_DISTRIBUTION_ID" \
    --paths "$S3_KEY" --region "$AWS_REGION" >/dev/null
  echo "Invalidated $S3_KEY on $CLOUDFRONT_DISTRIBUTION_ID"
fi

echo "Deployed to $S3_DEST"
