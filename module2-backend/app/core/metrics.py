"""
Prometheus instrumentation (Task 2.9). Exposed at GET /metrics - root
level, NOT under /api/v1 - matching module4-observability/prometheus.yml's
scrape config (`metrics_path: '/metrics'` against `backend:8000` directly).

Metric names are exact per IMPLEMENTATION-PLAN.md's Task 2.9 list - the
Module 4 dashboard queries them by these literal names via PromQL, so
don't rename without checking that doc.
"""
from prometheus_client import Counter, Histogram

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds", "HTTP request latency in seconds", ["method", "path", "status_code"],
)
checkin_attempts_total = Counter("checkin_attempts_total", "Total check-in submissions")
checkin_success_total = Counter("checkin_success_total", "Check-ins that resolved to approved")
login_failed_total = Counter("login_failed_total", "Failed login attempts")
checkins_flagged_total = Counter("checkins_flagged_total", "Check-ins that resolved to flagged")
risk_score_histogram = Histogram(
    "risk_score", "Distribution of computed check-in risk scores",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)
