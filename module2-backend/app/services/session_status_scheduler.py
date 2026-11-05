"""Background job that moves sessions scheduled -> active -> closed at each wall-clock quarter hour, from their check-in times."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, update
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.db.base import SessionLocal
from app.db.models.session import ClassSession
from app.services.audit import log_event

logger = logging.getLogger("saiv.session_status")

INITIAL_DELAY_SECONDS = 10
WAKE_OFFSET_SECONDS = 1
DEFAULT_STEP_MINUTES = 15

# start + min after (check-in close)
CLOSE_AT = ClassSession.checkin_closes_at


def step_minutes() -> int:
    """Configured interval in minutes; 0 disables, values not dividing 60 fall back to 15."""
    value = get_settings().SESSION_STATUS_INTERVAL_MINUTES
    if value <= 0:
        return 0
    if 60 % value:
        logger.warning("SESSION_STATUS_INTERVAL_MINUTES=%s does not divide 60; using %s", value, DEFAULT_STEP_MINUTES)
        return DEFAULT_STEP_MINUTES
    return value


def next_run_at(now: datetime, step: int) -> datetime:
    """Next wall-clock boundary (multiple of step minutes past the hour) strictly after now, plus a small offset."""
    floored = now.replace(minute=now.minute - now.minute % step, second=0, microsecond=0)
    return floored + timedelta(minutes=step, seconds=WAKE_OFFSET_SECONDS)


def _move(db: Session, where, values: dict, old: str, new: str, now: datetime,
          trigger: str = "scheduled", requested_by: Optional[str] = None) -> list:
    """Run one conditional bulk update and write one audit row per session it changed."""
    stmt = (
        update(ClassSession)
        .where(where)
        .values(status=new, updated_at=now, **values)
        .returning(ClassSession.id)
        .execution_options(synchronize_session=False)
    )
    ids = [row[0] for row in db.execute(stmt)]
    for session_id in ids:
        details = {"old_status": old, "new_status": new, "trigger": trigger}
        if requested_by:
            details["requested_by"] = requested_by
        # System change, so no user_id
        log_event(db, "session_updated", resource_type="session", resource_id=session_id, details=details)
    return ids


def advance_session_statuses(db: Session, now: datetime, trigger: str = "scheduled", requested_by: Optional[str] = None) -> dict:
    """Close sessions whose check-in has closed (start + min after), then activate ones whose check-in has opened; caller commits."""
    closed = _move(db, (ClassSession.status == "active") & (CLOSE_AT <= now),
                   {"actual_end": func.coalesce(ClassSession.actual_end, now)}, "active", "closed", now, trigger, requested_by)
    # Never activated and already over
    stale = _move(db, (ClassSession.status == "scheduled") & (CLOSE_AT <= now),
                  {"actual_end": func.coalesce(ClassSession.actual_end, now)}, "scheduled", "closed", now, trigger, requested_by)
    activated = _move(db, (ClassSession.status == "scheduled") & (ClassSession.checkin_opens_at <= now),
                      {"actual_start": func.coalesce(ClassSession.actual_start, now)}, "scheduled", "active", now,
                      trigger, requested_by)
    return {"activated": activated, "closed": closed + stale}


def run_status_pass() -> Optional[dict]:
    """One pass in its own DB session; returns the changed ids, or None if it failed."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        result = advance_session_statuses(db, now)
        db.commit()
        if result["activated"] or result["closed"]:
            logger.info("Session status pass at %s: %s", now.isoformat(), result)
        return result
    except Exception:
        db.rollback()
        logger.exception("Session status pass failed")
        return None
    finally:
        db.close()


async def session_status_loop() -> None:
    """Catch-up pass shortly after startup, then one pass at every quarter hour."""
    step = step_minutes()
    if not step:
        return
    await asyncio.sleep(INITIAL_DELAY_SECONDS)
    await run_in_threadpool(run_status_pass)
    while True:
        target = next_run_at(datetime.now(timezone.utc), step)
        # Re-sleep if woken early
        while (remaining := (target - datetime.now(timezone.utc)).total_seconds()) > 0:
            await asyncio.sleep(remaining)
        await run_in_threadpool(run_status_pass)
