"""
SAIV Backend API - Module 2

See docs/API-SPECIFICATION.md for the complete, authoritative endpoint
contract and module2-backend/IMPLEMENTATION-PLAN.md for the build order.
Routers are mounted here as each phase lands.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings

settings = get_settings()

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


@app.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {"status": "healthy", "service": "backend"}


@app.get("/")
async def root():
    """Root endpoint - service info."""
    return {"service": "SAIV Backend API", "version": "1.0.0"}


# Routers are mounted here phase-by-phase, all under /api/v1 per
# API-SPECIFICATION.md. Phase 2 adds: auth, users.
