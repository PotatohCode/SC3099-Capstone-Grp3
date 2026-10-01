"""
Runs the retention sweep automatically (SECURITY-REQUIREMENTS.md "Data
Retention ... Scheduled cleanup job"; Briefing "30-day auto-deletion
policy"). Before this, the sweep only ran when an admin called
POST /admin/retention/run, so in a deployment nobody pokes, expired
check-in PII was never anonymised.

Started from app startup: one sweep shortly after boot (so a restart
catches up), then every RETENTION_SWEEP_INTERVAL_MINUTES (0 disables it).
A short Redis lock keeps multiple worker processes from sweeping in the
same interval; if Redis is down we sweep anyway - the sweep is
idempotent, so a duplicate run is harmless. Errors are logged and the
loop carries on.
"""
import asyncio
import logging
from typing import Optional

import redis
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.db.base import SessionLocal
from app.services import retention
from app.services.audit import log_event
from app.services.rate_limit import _get_client

logger = logging.getLogger("saiv.retention")

_LOCK_KEY = "retention:sweep:lock"


def run_scheduled_sweep(lock_seconds: int) -> Optional[dict]:
    """One sweep, if this process wins the lock. Returns the result, or None if skipped/failed."""
    try:
        if not _get_client().set(_LOCK_KEY, "1", nx=True, ex=max(lock_seconds, 1)):
            return None  # another worker swept this interval
    except redis.RedisError:
        logger.warning("Redis unavailable for the retention lock; sweeping without it")

    db = SessionLocal()
    try:
        result = retention.run_retention_sweep(db)
        log_event(db, "retention_sweep_run", resource_type="retention", details={**result, "trigger": "scheduled"})
        db.commit()
        if result["users_anonymized"] or result["checkins_anonymized"]:
            logger.info("Scheduled retention sweep: %s", result)
        return result
    except Exception:
        db.rollback()
        logger.exception("Scheduled retention sweep failed")
        return None
    finally:
        db.close()


async def retention_loop() -> None:
    settings = get_settings()
    interval = settings.RETENTION_SWEEP_INTERVAL_MINUTES * 60
    await asyncio.sleep(settings.RETENTION_SWEEP_INITIAL_DELAY_SECONDS)
    while True:
        # Lock slightly shorter than the interval so the next run can take it.
        await run_in_threadpool(run_scheduled_sweep, max(interval - 30, 1))
        await asyncio.sleep(interval)
