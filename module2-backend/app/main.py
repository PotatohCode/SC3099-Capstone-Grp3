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

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import get_settings
from app.core.errors import DEFAULT_CODE_BY_STATUS, APIError, ErrorCode
from app.routers import admin, auth, checkins, courses, devices, enrollments, sessions, users

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
)


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
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500, content={"detail": "Internal server error", "code": ErrorCode.INTERNAL_ERROR}
    )


@app.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {"status": "healthy", "service": "backend"}


@app.get("/")
async def root():
    """Root endpoint - service info."""
    return {"service": "SAIV Backend API", "version": "1.0.0"}


API_PREFIX = "/api/v1"
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(users.router, prefix=API_PREFIX)
app.include_router(admin.router, prefix=API_PREFIX)
app.include_router(courses.router, prefix=API_PREFIX)
app.include_router(sessions.router, prefix=API_PREFIX)
app.include_router(enrollments.router, prefix=API_PREFIX)
app.include_router(devices.router, prefix=API_PREFIX)
app.include_router(checkins.router, prefix=API_PREFIX)

# Routers are mounted here phase-by-phase, all under /api/v1 per
# API-SPECIFICATION.md. Phase 7 adds: stats, audit, export.
