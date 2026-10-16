"""Settings read from environment variables (see docker-compose.yml)."""
import os
from zoneinfo import ZoneInfo

# Where the dashboard container reaches the other services.
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090").rstrip("/")

# Link opened in the *user's browser*, so it must be reachable from there,
# not from inside Docker.
GRAFANA_PUBLIC_URL = os.getenv("GRAFANA_PUBLIC_URL", "http://localhost:3001").rstrip("/")

# Preview mode (sample data, no backend needed) is off unless explicitly enabled.
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() in {"1", "true", "yes"}

# Timeouts from docs/recommended_design/INTEGRATION-GUIDE.md.
BACKEND_TIMEOUT_SECONDS = 30
PROMETHEUS_TIMEOUT_SECONDS = 5

# Polling interval for live parts of the dashboard (Module 4 design deck).
REFRESH_SECONDS = 30

# Backend stores naive UTC timestamps; staff see Singapore time.
LOCAL_TZ = ZoneInfo("Asia/Singapore")

# Backend page-size cap (CHANGES-2026-10-01.md: limit is capped at 100).
PAGE_SIZE = 100

STAFF_ROLES = {"ta", "instructor", "admin"}
