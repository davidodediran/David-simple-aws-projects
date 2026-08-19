#!/bin/bash
# EC2 bootstrap script - run as user data or after SSH'ing in.
# Tested on Amazon Linux 2023 and Ubuntu 22.04+.

set -euo pipefail

APP_DIR="/opt/video-processor"
APP_USER="videoprocessor"

echo "=== Installing system dependencies ==="
if command -v dnf &>/dev/null; then
    sudo dnf update -y
    sudo dnf install -y python3.11 python3.11-pip ffmpeg git
elif command -v apt-get &>/dev/null; then
    sudo apt-get update -y
    sudo apt-get install -y python3 python3-pip python3-venv ffmpeg git
fi

echo "=== Creating application user ==="
if ! id "$APP_USER" &>/dev/null; then
    sudo useradd --system --create-home --shell /bin/bash "$APP_USER"
fi

echo "=== Setting up application directory ==="
sudo mkdir -p "$APP_DIR"/{input,output}
sudo chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo "=== Copying application files ==="
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
sudo cp "$SCRIPT_DIR"/{app.py,web.py,config.py,processor.py,s3_client.py,requirements.txt} "$APP_DIR/"
sudo cp -r "$SCRIPT_DIR/templates" "$APP_DIR/"
sudo mkdir -p "$APP_DIR/static"
sudo cp "$SCRIPT_DIR/.env.example" "$APP_DIR/.env"
sudo chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo "=== Installing Python dependencies ==="
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/venv"
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "=== Installing systemd services ==="

# Background S3 poller (optional, for headless processing)
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

# Web UI (Gunicorn on port 5000)
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
ExecStart=/opt/video-processor/venv/bin/gunicorn web:app --bind 0.0.0.0:5000 --workers 2 --threads 4 --timeout 300
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
EnvironmentFile=/opt/video-processor/.env

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable video-processor-web

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit /opt/video-processor/.env with your S3 bucket names and AWS region"
echo "  2. Attach an IAM role to this EC2 instance with S3 read/write permissions"
echo "  3. Open port 5000 in your EC2 security group (or use an ALB)"
echo "  4. Start the web UI:  sudo systemctl start video-processor-web"
echo "  5. Open http://<ec2-public-ip>:5000 in your browser"
echo "  6. Check logs:        journalctl -u video-processor-web -f"
echo ""
echo "Optional - also start the background S3 poller:"
echo "  sudo systemctl start video-processor"
