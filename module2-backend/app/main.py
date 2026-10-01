"""
SAIV Backend API - Module 2

See docs/API-SPECIFICATION.md for the complete, authoritative endpoint
contract and module2-backend/IMPLEMENTATION-PLAN.md for the build order.
Routers are mounted here as each phase lands.

Error format: see IMPLEMENTATION-PLAN.md's "Team decisions that deviate
from the written docs" - every non-422 error body includes a `code` field
alongside `detail`, via the exception handlers registered below.
"""
import logging
import re
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings
from app.core.errors import DEFAULT_CODE_BY_STATUS, APIError, ErrorCode
from app.core.metrics import http_request_duration_seconds
from app.routers import admin, audit, auth, checkins, courses, devices, enrollments, export, sessions, stats, users

settings = get_settings()
logger = logging.getLogger("saiv.errors")

app = FastAPI(
    title="SAIV Backend API",
    description="Secure Attendance & Identity Verification System",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Lets browser code read Retry-After on 429s (account lockout, rate
    # limits) - cross-origin JS can only see headers listed here.
    expose_headers=["Retry-After", "X-Request-ID"],
)


class MetricsMiddleware(BaseHTTPMiddleware):
    """Records http_request_duration_seconds (Task 2.9) for every request,
    including ones to /metrics itself (harmless - Prometheus scraping
    itself just shows up as a fast, cheap data point)."""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start
        route = request.scope.get("route")
        path_label = getattr(route, "path", None) or request.url.path
        http_request_duration_seconds.labels(
            method=request.method, path=path_label, status_code=str(response.status_code)
        ).observe(duration)
        return response


app.add_middleware(MetricsMiddleware)

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Correlation id for every request (Module 2 design deck: "Request ID
    for correlation"). Reuses a well-formed incoming X-Request-ID (so a
    caller can trace its own request), otherwise generates one; echoed on
    the response and included in server-side error logs. Added last, so
    it's the outermost user middleware and covers everything inside it."""

    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


app.add_middleware(RequestIDMiddleware)


@app.exception_handler(APIError)
async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code, content={"detail": exc.detail, "code": exc.code}, headers=exc.headers
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Catches any plain HTTPException(...) not yet migrated to APIError -
    still emits `code`, derived from the status code as a generic fallback."""
    code = DEFAULT_CODE_BY_STATUS.get(exc.status_code, "ERROR")
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "code": code}, headers=exc.headers)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Never leak internals (per API-SPECIFICATION.md's Error Responses
    section) - log the real error server-side, return the generic message."""
    # Unhandled errors are answered outside the user middleware stack, so
    # attach the request id here too.
    request_id = getattr(request.state, "request_id", None)
    logger.exception("Unhandled exception on %s %s [request_id=%s]", request.method, request.url.path, request_id)
    return JSONResponse(
        status_code=500, content={"detail": "Internal server error", "code": ErrorCode.INTERNAL_ERROR},
        headers={"X-Request-ID": request_id} if request_id else None,
    )


@app.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {"status": "healthy", "service": "backend"}


@app.get("/")
async def root():
    """Root endpoint - service info."""
    return {"service": "SAIV Backend API", "version": "1.0.0"}


@app.get("/metrics")
async def metrics():
    """Root level, NOT under /api/v1 - matches
    module4-observability/prometheus.yml's scrape config (metrics_path:
    '/metrics' against backend:8000 directly). A plain route rather than
    prometheus_client's make_asgi_app()/app.mount(): Starlette's Mount
    307-redirects a bare /metrics to /metrics/ (confirmed live), which a
    strict scraper isn't guaranteed to follow - this avoids that
    entirely."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

API_PREFIX = "/api/v1"
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(users.router, prefix=API_PREFIX)
app.include_router(admin.router, prefix=API_PREFIX)
app.include_router(courses.router, prefix=API_PREFIX)
app.include_router(sessions.router, prefix=API_PREFIX)
app.include_router(enrollments.router, prefix=API_PREFIX)
app.include_router(devices.router, prefix=API_PREFIX)
app.include_router(checkins.router, prefix=API_PREFIX)
app.include_router(audit.router, prefix=API_PREFIX)
app.include_router(stats.router, prefix=API_PREFIX)
app.include_router(export.router, prefix=API_PREFIX)

# Routers are mounted here phase-by-phase, all under /api/v1 per
# API-SPECIFICATION.md. Phase 7 (7d-7e) adds: rate limiting, metrics,
# retention job.
