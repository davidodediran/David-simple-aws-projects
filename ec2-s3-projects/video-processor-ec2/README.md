# Video Processor for EC2

A Python application that processes video files on an EC2 instance and stores the results in Amazon S3. Includes a web UI for uploading videos, selecting processing types, and viewing results with file sizes.

## Architecture

```
User (Browser) --> EC2 (Flask Web UI :5000) --> ffmpeg (process video)
                                            --> S3 Output Bucket (upload results)

S3 Input Bucket --> EC2 (CLI poller) --> ffmpeg --> S3 Output Bucket
```

**Two ways to use it:**
- **Web UI** - Upload videos from your browser, pick a processing mode, view results
- **CLI** - Process local files or poll an S3 bucket for incoming videos

## Prerequisites

- An AWS account
- An EC2 instance (Amazon Linux 2023 or Ubuntu 22.04+)
- Two S3 buckets (one for input, one for output)
- An IAM role attached to the EC2 instance

## Step 1: Create the S3 Buckets

Create two S3 buckets in your preferred region. Replace the names with your own.

```bash
aws s3 mb s3://my-video-input-bucket --region eu-west-1
aws s3 mb s3://my-video-output-bucket --region eu-west-1
```

## Step 2: Create the IAM Role

1. Go to the **IAM Console** > **Roles** > **Create role**
2. Select **AWS service** > **EC2** as the trusted entity
3. Create a new policy using the contents of `iam-policy.json` in this project
4. Replace `my-video-input-bucket` and `my-video-output-bucket` with your actual bucket names
5. Attach the policy to the role and name it (e.g., `VideoProcessorEC2Role`)

The policy grants:
- Read, list, delete on the input bucket (to fetch and move processed videos)
- Write on the input bucket (to move files to the `done/` prefix)
- Write on the output bucket (to upload processed results)

## Step 3: Launch the EC2 Instance

1. Go to the **EC2 Console** > **Launch instance**
2. Choose **Amazon Linux 2023** or **Ubuntu 22.04** AMI
3. Select an instance type:
   - `t3.medium` - light workloads, short videos
   - `c5.xlarge` - heavier transcoding, longer videos
4. Under **Advanced details** > **IAM instance profile**, select the role you created in Step 2
5. In the **Security group**, add a rule to allow inbound TCP on port **5000** (for the web UI)
   - Source: your IP address or `0.0.0.0/0` (not recommended for production)
6. Launch and SSH into the instance

```bash
ssh -i your-key.pem ec2-user@<ec2-public-ip>
```

## Step 4: Deploy the Application

Clone or copy the project files to the EC2 instance, then run the setup script:

```bash
git clone <your-repo-url>
cd simple-projects/ec2-s3-projects/video-processor-ec2
bash setup-ec2.sh
```

The setup script will:
- Install Python 3, ffmpeg, and pip
- Create a system user (`videoprocessor`)
- Copy files to `/opt/video-processor/`
- Create a Python virtual environment and install dependencies
- Register two systemd services

## Step 5: Configure the Environment

Edit the `.env` file with your actual bucket names and preferences:

```bash
sudo vi /opt/video-processor/.env
```

Update these values:

| Variable | Description | Example |
|----------|-------------|---------|
| `AWS_REGION` | Your AWS region | `eu-west-1` |
| `S3_INPUT_BUCKET` | Bucket for incoming videos | `my-video-input-bucket` |
| `S3_OUTPUT_BUCKET` | Bucket for processed results | `my-video-output-bucket` |
| `S3_INPUT_PREFIX` | Prefix (folder) to watch in the input bucket | `raw/` |
| `S3_OUTPUT_PREFIX` | Prefix for uploaded results | `processed/` |
| `PROCESSING_MODE` | Default processing type | `frames` |
| `FRAME_INTERVAL` | Seconds between extracted frames | `1` |
| `THUMBNAIL_WIDTH` | Thumbnail width in pixels | `320` |
| `THUMBNAIL_HEIGHT` | Thumbnail height in pixels | `240` |
| `TRANSCODE_FORMAT` | Output video format | `mp4` |
| `TRANSCODE_CODEC` | Video codec for transcoding | `libx264` |

## Step 6: Start the Web UI

```bash
sudo systemctl start video-processor-web
```

Verify it is running:

```bash
sudo systemctl status video-processor-web
```

Check the logs:

```bash
journalctl -u video-processor-web -f
```

Open your browser and go to:

```
http://<ec2-public-ip>:5000
```

## Step 7: Using the Web UI

### Upload and Process a Video

1. Open `http://<ec2-public-ip>:5000` in your browser
2. Click **Choose File** and select a video (supported: `.mp4`, `.avi`, `.mov`, `.mkv`, `.wmv`, `.flv`, `.webm`)
3. Select a **Processing Type** from the dropdown:
   - **Extract Frames** - pulls individual frame images at a set interval (default: every 1 second)
   - **Generate Thumbnails** - creates smaller preview images at regular points throughout the video
   - **Transcode Video** - re-encodes the video to a different format/codec
   - **All Processing** - runs all three operations
4. Click **Upload & Process**
5. You are redirected to the **Job Detail** page, which auto-refreshes every 3 seconds while processing

### View Results

On the Job Detail page you will see:

- **Input Size (MB)** - the size of your original uploaded video
- **Output Size (MB)** - the total size of all processed files
- **Files Generated** - how many output files were created
- **Duration** - the length of the video
- **Resolution** - the video dimensions (e.g., 1920x1080)
- **S3 Location** - where the results are stored in S3

Below the stats, the results are grouped by type:

- **Transcoded Video** - shows a download link and file size in MB
- **Extracted Frames** - image previews with individual file sizes in MB, click to view full size
- **Thumbnails** - image previews with individual file sizes in MB, click to view full size

All result links are S3 presigned URLs that expire after 1 hour.

### Dashboard

Go back to `http://<ec2-public-ip>:5000` to see all your processing jobs in a table with:

- File name
- Processing mode used
- Input size (MB)
- Output size (MB)
- Status (queued / processing / completed / failed)
- Timestamp
- Link to view details

## Step 8: Using the CLI (Optional)

The CLI mode is useful for scripting, cron jobs, or headless processing without the web UI.

### Process a single local file

```bash
cd /opt/video-processor
./venv/bin/python app.py --file /path/to/video.mp4
```

### Process with a specific mode

```bash
./venv/bin/python app.py --file /path/to/video.mp4 --mode thumbnails
./venv/bin/python app.py --file /path/to/video.mp4 --mode transcode
./venv/bin/python app.py --file /path/to/video.mp4 --mode all
```

### Process all videos in a directory

```bash
./venv/bin/python app.py --dir /path/to/videos/
```

### Poll S3 for new videos (background service)

Start the S3 polling service (watches the input bucket and processes new videos automatically):

```bash
sudo systemctl start video-processor
```

Or run it manually in the foreground:

```bash
./venv/bin/python app.py
```

Upload a video to the input bucket to test:

```bash
aws s3 cp sample-video.mp4 s3://my-video-input-bucket/raw/
```

The poller picks it up, processes it, uploads results to the output bucket, and moves the original to `raw/done/`.

## Processing Modes Explained

| Mode | What it does | Output |
|------|-------------|--------|
| `frames` | Extracts individual frames from the video at a fixed interval | JPEG images (`frame_000001.jpg`, `frame_000002.jpg`, ...) |
| `thumbnails` | Generates smaller preview images at evenly spaced points | JPEG images (`thumb_0000.jpg`, `thumb_0001.jpg`, ...) scaled to 320x240 |
| `transcode` | Re-encodes the video using a different codec/format | Single video file (default: H.264 MP4 with AAC audio) |
| `all` | Runs frames + thumbnails + transcode together | All of the above |

## Troubleshooting

### Web UI not loading

1. Confirm the service is running: `sudo systemctl status video-processor-web`
2. Check the security group allows inbound TCP on port 5000
3. Check the logs: `journalctl -u video-processor-web -f`

### Processing fails

1. Verify ffmpeg is installed: `ffmpeg -version`
2. Check the video format is supported (`.mp4`, `.avi`, `.mov`, `.mkv`, `.wmv`, `.flv`, `.webm`)
3. Check disk space: `df -h` (processing creates temp files locally)

### S3 permission errors

1. Confirm the IAM role is attached to the EC2 instance
2. Verify the bucket names in `/opt/video-processor/.env` match the IAM policy
3. Test access manually: `aws s3 ls s3://my-video-output-bucket/`

### View all logs

```bash
journalctl -u video-processor-web -f    # web UI logs
journalctl -u video-processor -f        # S3 poller logs
```

## File Structure

```
video-processor-ec2/
  app.py              # CLI entry point (S3 poller, single file, batch directory)
  web.py              # Flask web UI (upload, process, view results)
  processor.py        # Video processing logic (ffmpeg)
  s3_client.py        # S3 download/upload/move operations
  config.py           # Configuration from environment variables
  setup-ec2.sh        # EC2 bootstrap script (installs deps, creates systemd services)
  iam-policy.json     # IAM policy template for the EC2 instance role
  requirements.txt    # Python dependencies
  .env.example        # Environment variable template
  templates/
    base.html         # Shared page layout and styles
    index.html        # Dashboard - upload form and jobs table
    job.html          # Job detail - stats, results gallery, file sizes
```
