"""
SAIV Backend API - Module 2

See docs/API-SPECIFICATION.md for the complete, authoritative endpoint
contract and module2-backend/IMPLEMENTATION-PLAN.md for the build order.
Routers are mounted here as each phase lands.

Error format: see IMPLEMENTATION-PLAN.md's "Team decisions that deviate
from the written docs" - every non-422 error body includes a `code` field
alongside `detail`, via the exception handlers registered below.
"""
import asyncio
import logging
import re
import time
import uuid

import anyio.to_thread
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError, OperationalError
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings
from app.core.errors import DEFAULT_CODE_BY_STATUS, APIError, ErrorCode
from app.core.metrics import http_request_duration_seconds
from app.routers import admin, audit, auth, checkins, courses, devices, enrollments, export, sessions, stats, users
from app.db.base import SessionLocal
from app.services.rate_limit import _get_client as _redis_client
from app.services.retention_scheduler import retention_loop

settings = get_settings()
logger = logging.getLogger("saiv.errors")

app = FastAPI(
    title="SAIV Backend API",
    description="Secure Attendance & Identity Verification System",
    version="1.0.0",
)

class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Rejects requests whose declared Content-Length exceeds
    MAX_REQUEST_BODY_BYTES before the body is read. Registered before
    CORSMiddleware, so CORS wraps it and a browser still sees a readable
    413 rather than an opaque CORS failure."""

    async def dispatch(self, request: Request, call_next):
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > settings.MAX_REQUEST_BODY_BYTES:
            return JSONResponse(
                status_code=413,
                content={"detail": "Request body too large", "code": ErrorCode.REQUEST_TOO_LARGE},
            )
        return await call_next(request)


def _internal_error(request: Request) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=500, content={"detail": "Internal server error", "code": ErrorCode.INTERNAL_ERROR},
        headers={"X-Request-ID": request_id} if request_id else None,
    )


class UnhandledErrorMiddleware(BaseHTTPMiddleware):
    """Turns an unexpected exception into our 500 JSON *here*, inside the
    user middleware. Left to Starlette's outermost ServerErrorMiddleware
    (the Exception handler below), the error is re-raised after the 500 is
    sent and the server drops the keep-alive connection without a
    `Connection: close`, so the client's *next* request on that connection
    fails too (measured: every 500 cost a second request). Handled here, the
    connection stays usable, and metrics, CORS and X-Request-ID all see a
    normal 500 response. Added first, so it's the innermost middleware."""

    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except Exception:
            logger.exception(
                "Unhandled exception on %s %s [request_id=%s]",
                request.method, request.url.path, getattr(request.state, "request_id", None),
            )
            return _internal_error(request)


app.add_middleware(UnhandledErrorMiddleware)
app.add_middleware(BodySizeLimitMiddleware)

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


def _invalid_input(detail: str) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": detail, "code": ErrorCode.INVALID_INPUT})


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    """psycopg2 refuses any string containing a NUL character (raised as a
    plain ValueError when the query runs), so "\\x00" / "%00" in a path id,
    a query filter or a body field used to be a 500. It's bad input: 400.
    Any other ValueError is unexpected: logged, generic 500."""
    if "NUL (0x00)" in str(exc):
        return _invalid_input("Input contains a NUL character")
    logger.exception("Unhandled ValueError on %s %s", request.method, request.url.path)
    return _internal_error(request)


@app.exception_handler(DataError)
async def data_error_handler(request: Request, exc: DataError) -> JSONResponse:
    """The database rejected a value: a number out of range (e.g.
    offset=10^20 overflows bigint), a malformed value, and so on. That's
    the client's input, not a server fault: 400, without the SQL details."""
    logger.warning("Database rejected input on %s %s: %s", request.method, request.url.path, exc.orig)
    return _invalid_input("A value is out of range or not valid")


# Unique constraints/indexes -> the error the endpoint's own "already exists?"
# check returns. That check and the INSERT aren't atomic: two identical
# requests at the same instant both pass the check, and the loser hits the
# constraint here (measured: 20 parallel duplicates -> up to 71% 500s).
# The data was always safe; this only fixes the answer.
_UNIQUE_VIOLATIONS = {
    "ix_users_email": ("Email already registered", ErrorCode.EMAIL_ALREADY_REGISTERED),
    "ix_courses_code": ("Course code already exists", ErrorCode.COURSE_CODE_TAKEN),
    "uq_enrollment_student_course": ("Student already enrolled", ErrorCode.ALREADY_ENROLLED),
    "uq_checkin_session_student": ("Already checked in for this session", ErrorCode.ALREADY_CHECKED_IN),
    "ix_devices_device_fingerprint": (
        "Device fingerprint already registered to another user", ErrorCode.DEVICE_FINGERPRINT_TAKEN,
    ),
}


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    if constraint in _UNIQUE_VIOLATIONS:
        detail, code = _UNIQUE_VIOLATIONS[constraint]
        return JSONResponse(status_code=400, content={"detail": detail, "code": code})
    logger.exception("Unhandled IntegrityError on %s %s", request.method, request.url.path)
    return _internal_error(request)


@app.exception_handler(OperationalError)
async def operational_error_handler(request: Request, exc: OperationalError) -> JSONResponse:
    """Database unreachable (or a transient failure like a deadlock). Not a
    bug in the request or the server: 503 so clients know to retry, rather
    than a 500. The pool's pre-ping reconnects once Postgres is back."""
    logger.error("Database unavailable on %s %s: %s", request.method, request.url.path, exc.orig)
    return JSONResponse(
        status_code=503,
        content={"detail": "Service temporarily unavailable, please retry", "code": ErrorCode.SERVICE_UNAVAILABLE},
        headers={"Retry-After": "5"},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Never leak internals (per API-SPECIFICATION.md's Error Responses
    section) - log the real error server-side, return the generic message.
    Backstop only: UnhandledErrorMiddleware normally answers first."""
    logger.exception(
        "Unhandled exception on %s %s [request_id=%s]",
        request.method, request.url.path, getattr(request.state, "request_id", None),
    )
    return _internal_error(request)


@app.on_event("startup")
async def size_thread_pool() -> None:
    # See THREADPOOL_SIZE in core/config.py for why the default 40 deadlocks.
    anyio.to_thread.current_default_thread_limiter().total_tokens = settings.THREADPOOL_SIZE


@app.on_event("startup")
async def start_retention_sweep() -> None:
    if settings.RETENTION_SWEEP_INTERVAL_MINUTES > 0:
        app.state.retention_task = asyncio.create_task(retention_loop())


@app.on_event("shutdown")
async def stop_retention_sweep() -> None:
    task = getattr(app.state, "retention_task", None)
    if task is not None:
        task.cancel()


@app.get("/health")
def health_check():
    """Readiness, not just liveness: checks Postgres and Redis.
    - database unreachable -> 503 "unhealthy" (nothing works without it)
    - redis unreachable    -> 200 "degraded" (the backend keeps working:
      rate limiting fails open by design)
    Used by docker-compose's backend healthcheck, so the frontend and
    dashboard only start once the backend can actually serve requests.
    (The course's backend health test accepts 200 or 503.)"""
    checks = {}
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"
    finally:
        db.close()
    try:
        _redis_client().ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "unavailable"

    if checks["database"] != "ok":
        return JSONResponse(status_code=503, content={"status": "unhealthy", "service": "backend", **checks})
    status_text = "healthy" if checks["redis"] == "ok" else "degraded"
    return {"status": status_text, "service": "backend", **checks}


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
