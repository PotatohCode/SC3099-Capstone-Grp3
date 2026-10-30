FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for OpenCV and MediaPipe. (build-essential and
# cmake were only needed to compile dlib, replaced by ArcFace on 2026-10-30.)
RUN apt-get update && apt-get install -y \
    libopencv-dev \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (includes models/w600k_mbf.onnx, the ArcFace model)
COPY . .

# Expose port
EXPOSE 8001

# Number of uvicorn worker processes (uvicorn reads WEB_CONCURRENCY as its
# --workers default). Each worker loads its own MediaPipe and ArcFace models
# and uses one CPU core for them. 3 measured as the balance of speed vs
# memory on the full stack; see CHANGES.md 2026-10-29 and 2026-10-30 before
# changing.
ENV WEB_CONCURRENCY=3

# Lets /metrics add up the counters of all workers (prometheus_client
# multiprocess mode). Must be set before the app starts; see app/main.py.
ENV PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc

# Run the application. The metrics folder is emptied first so numbers from
# before a container restart don't carry over; exec keeps uvicorn as the main
# process so it receives Docker's stop signal.
CMD ["sh", "-c", "rm -rf \"$PROMETHEUS_MULTIPROC_DIR\" && mkdir -p \"$PROMETHEUS_MULTIPROC_DIR\" && exec uvicorn app.main:app --host 0.0.0.0 --port 8001"]
