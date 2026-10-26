FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for OpenCV and face_recognition
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    libopencv-dev \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 8001

# Number of uvicorn worker processes (uvicorn reads WEB_CONCURRENCY as its
# --workers default). Each worker loads its own MediaPipe and dlib models, so
# memory grows roughly per worker. See CHANGES.md before changing it.
ENV WEB_CONCURRENCY=2

# Lets /metrics add up the counters of all workers (prometheus_client
# multiprocess mode). Must be set before the app starts; see app/main.py.
ENV PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc

# Run the application. The metrics folder is emptied first so numbers from
# before a container restart don't carry over; exec keeps uvicorn as the main
# process so it receives Docker's stop signal.
CMD ["sh", "-c", "rm -rf \"$PROMETHEUS_MULTIPROC_DIR\" && mkdir -p \"$PROMETHEUS_MULTIPROC_DIR\" && exec uvicorn app.main:app --host 0.0.0.0 --port 8001"]
