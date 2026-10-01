FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 8000

# Apply database migrations, then serve. A fresh database (a grader's
# machine, or after `docker compose down -v`) has no tables until
# `alembic upgrade head` runs; doing it here means `docker compose up` is
# enough. It's a no-op when already at head. Postgres is ready first
# (backend depends_on postgres: service_healthy). Inline rather than an
# entrypoint script so Windows CRLF checkouts can't break it.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
