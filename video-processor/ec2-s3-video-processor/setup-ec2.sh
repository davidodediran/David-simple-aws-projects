#!/bin/bash
# Full EC2 bootstrap: clones the repo, installs everything, configures and starts the app.
# Run on a fresh Amazon Linux 2023 or Ubuntu 22.04+ instance.
#
# Usage (as ec2-user / ubuntu):
#   curl -fsSL https://raw.githubusercontent.com/davidodediran/David-simple-aws-projects/main/video-processor/ec2-s3-video-processor/setup-ec2.sh | bash
#
# Or with a CloudFormation stack name to auto-detect buckets:
#   curl -fsSL ...setup-ec2.sh | bash -s -- --stack video-processor

set -euo pipefail

APP_DIR="/opt/video-processor"
APP_USER="videoprocessor"
REPO_URL="https://github.com/davidodediran/David-simple-aws-projects.git"
REPO_SUBDIR="video-processor/ec2-s3-video-processor"
STACK_NAME=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --stack) STACK_NAME="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

echo "=========================================="
echo "  Video Processor - EC2 Setup"
echo "=========================================="
echo ""

# -----------------------------------------------------------
# 1. System dependencies
# -----------------------------------------------------------
echo "=== [1/7] Installing system dependencies ==="
if command -v dnf &>/dev/null; then
    sudo dnf update -y
    sudo dnf install -y python3.11 python3.11-pip git tar xz
    PY=python3.11
elif command -v apt-get &>/dev/null; then
    sudo apt-get update -y
    sudo apt-get install -y python3 python3-pip python3-venv git curl
    PY=python3
else
    echo "ERROR: Unsupported package manager. Need dnf or apt-get."
    exit 1
fi

# -----------------------------------------------------------
# 2. Install ffmpeg (static build for AL2023, package for Ubuntu)
# -----------------------------------------------------------
echo "=== [2/7] Installing ffmpeg ==="
if command -v ffmpeg &>/dev/null; then
    echo "ffmpeg already installed: $(ffmpeg -version 2>&1 | head -1)"
else
    if command -v dnf &>/dev/null; then
        cd /tmp
        curl -LO https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz
        tar xf ffmpeg-release-amd64-static.tar.xz
        sudo cp ffmpeg-*-static/ffmpeg ffmpeg-*-static/ffprobe /usr/local/bin/
        rm -rf ffmpeg-*-static*
    else
        sudo apt-get install -y ffmpeg
    fi
    echo "ffmpeg installed: $(ffmpeg -version 2>&1 | head -1)"
fi

# -----------------------------------------------------------
# 3. Clone repo and copy application files
# -----------------------------------------------------------
echo "=== [3/7] Cloning repository ==="
CLONE_DIR="/tmp/video-processor-repo"
rm -rf "$CLONE_DIR"
git clone --depth 1 "$REPO_URL" "$CLONE_DIR"

echo "=== Creating application user ==="
if ! id "$APP_USER" &>/dev/null; then
    sudo useradd --system --create-home --shell /bin/bash "$APP_USER"
fi

echo "=== Copying application files ==="
sudo mkdir -p "$APP_DIR"/{input,output,templates,static}

SRC="$CLONE_DIR/$REPO_SUBDIR"
sudo cp "$SRC"/{app.py,web.py,config.py,processor.py,s3_client.py,requirements.txt} "$APP_DIR/"
sudo cp -r "$SRC/templates/"* "$APP_DIR/templates/"
sudo chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# -----------------------------------------------------------
# 4. Configure .env (auto-detect from CloudFormation or use defaults)
# -----------------------------------------------------------
echo "=== [4/7] Configuring environment ==="

# Get region from instance metadata
TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" \
    -H "X-aws-ec2-metadata-token-ttl-seconds: 60" 2>/dev/null || true)
if [[ -n "$TOKEN" ]]; then
    REGION=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" \
        http://169.254.169.254/latest/meta-data/placement/region 2>/dev/null || echo "${AWS_DEFAULT_REGION:-us-east-1}")
else
    REGION="${AWS_DEFAULT_REGION:-us-east-1}"
fi

INPUT_BUCKET=""
OUTPUT_BUCKET=""

# Auto-detect bucket names from CloudFormation stack
if [[ -n "$STACK_NAME" ]]; then
    echo "  Detecting buckets from CloudFormation stack: $STACK_NAME"
    INPUT_BUCKET=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
        --query "Stacks[0].Outputs[?OutputKey=='InputBucketName'].OutputValue" \
        --output text --region "$REGION" 2>/dev/null || true)
    OUTPUT_BUCKET=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
        --query "Stacks[0].Outputs[?OutputKey=='OutputBucketName'].OutputValue" \
        --output text --region "$REGION" 2>/dev/null || true)
fi

# Fall back: try the default stack name
if [[ -z "$INPUT_BUCKET" ]]; then
    INPUT_BUCKET=$(aws cloudformation describe-stacks --stack-name "video-processor" \
        --query "Stacks[0].Outputs[?OutputKey=='InputBucketName'].OutputValue" \
        --output text --region "$REGION" 2>/dev/null || true)
    OUTPUT_BUCKET=$(aws cloudformation describe-stacks --stack-name "video-processor" \
        --query "Stacks[0].Outputs[?OutputKey=='OutputBucketName'].OutputValue" \
        --output text --region "$REGION" 2>/dev/null || true)
fi

# Fall back: construct from account ID
if [[ -z "$INPUT_BUCKET" ]]; then
    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "")
    if [[ -n "$ACCOUNT_ID" ]]; then
        INPUT_BUCKET="video-processor-input-${ACCOUNT_ID}"
        OUTPUT_BUCKET="video-processor-output-${ACCOUNT_ID}"
        echo "  Constructed bucket names from account ID: $ACCOUNT_ID"
    else
        INPUT_BUCKET="my-video-input-bucket"
        OUTPUT_BUCKET="my-video-output-bucket"
        echo "  WARNING: Could not detect buckets. Edit /opt/video-processor/.env manually."
    fi
fi

echo "  Input bucket:  $INPUT_BUCKET"
echo "  Output bucket: $OUTPUT_BUCKET"
echo "  Region:        $REGION"

sudo tee "$APP_DIR/.env" > /dev/null << ENVEOF
AWS_REGION=$REGION
S3_INPUT_BUCKET=$INPUT_BUCKET
S3_OUTPUT_BUCKET=$OUTPUT_BUCKET
S3_INPUT_PREFIX=raw/
S3_OUTPUT_PREFIX=processed/
LOCAL_INPUT_DIR=/opt/video-processor/input
LOCAL_OUTPUT_DIR=/opt/video-processor/output
PROCESSING_MODE=frames
FRAME_INTERVAL=1
THUMBNAIL_WIDTH=320
THUMBNAIL_HEIGHT=240
TRANSCODE_FORMAT=mp4
TRANSCODE_CODEC=libx264
POLL_INTERVAL_SECONDS=30
LOG_LEVEL=INFO
ENVEOF
sudo chown "$APP_USER:$APP_USER" "$APP_DIR/.env"

# -----------------------------------------------------------
# 5. Python virtual environment and dependencies
# -----------------------------------------------------------
echo "=== [5/7] Installing Python dependencies ==="
sudo -u "$APP_USER" $PY -m venv "$APP_DIR/venv"
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

# -----------------------------------------------------------
# 6. Systemd services
# -----------------------------------------------------------
echo "=== [6/7] Installing systemd services ==="

sudo tee /etc/systemd/system/video-processor.service > /dev/null << 'EOF'
[Unit]
Description=Video Processor - S3 Poll Worker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=videoprocessor
Group=videoprocessor
WorkingDirectory=/opt/video-processor
ExecStart=/opt/video-processor/venv/bin/python /opt/video-processor/app.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
EnvironmentFile=/opt/video-processor/.env

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/video-processor-web.service > /dev/null << 'EOF'
[Unit]
Description=Video Processor - Web UI
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=videoprocessor
Group=videoprocessor
WorkingDirectory=/opt/video-processor
ExecStart=/opt/video-processor/venv/bin/gunicorn web:app --bind 0.0.0.0:5000 --workers 1 --threads 4 --timeout 300
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
EnvironmentFile=/opt/video-processor/.env

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload

# -----------------------------------------------------------
# 7. Start the web UI
# -----------------------------------------------------------
echo "=== [7/7] Starting video processor web UI ==="
sudo systemctl enable video-processor-web
sudo systemctl start video-processor-web

# Clean up
rm -rf "$CLONE_DIR"

# Get public IP for the URL
PUBLIC_IP=""
if [[ -n "$TOKEN" ]]; then
    PUBLIC_IP=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" \
        http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "")
fi

echo ""
echo "=========================================="
echo "  Setup complete!"
echo "=========================================="
echo ""
echo "  Status:  $(sudo systemctl is-active video-processor-web)"
if [[ -n "$PUBLIC_IP" ]]; then
echo "  Web UI:  http://$PUBLIC_IP:5000"
else
echo "  Web UI:  http://<ec2-public-ip>:5000"
fi
echo ""
echo "  Logs:    sudo journalctl -u video-processor-web -f"
echo "  Config:  $APP_DIR/.env"
echo ""
echo "  Optional - start background S3 poller:"
echo "    sudo systemctl start video-processor"
echo "=========================================="
