"""Shared response envelopes and cross-schema types."""
from typing import Annotated, Generic, List, Literal, TypeVar

from pydantic import AfterValidator, BaseModel, Field

from app.services.sanitize import sanitize_text

T = TypeVar("T")

# Single source of truth for the role literal - schemas/auth.py re-exports
# this (RegisterRequest imports Role from there historically), and
# schemas/user.py uses it directly for admin role reassignment. Defined
# here rather than in auth.py to avoid a user.py <-> auth.py import cycle
# (auth.py already imports UserResponse from user.py).
Role = Literal["student", "instructor", "ta", "admin"]

# New passwords (register, admin bulk create). See schemas/auth.py.
PASSWORD_MAX_LENGTH = 128


# Free text stored HTML-escaped in a VARCHAR(255) column. Routers escape it
# (services/sanitize.py) just before saving, and escaping makes it longer
# ("<" -> "&lt;"), so a value within max_length could still overflow the
# column: a 500 (or a dropped connection) instead of a validation error.
# This checks the escaped length up front, so it's a normal 422. The value
# itself is returned unescaped; escaping stays in the routers.
_STORED_TEXT_MAX = 255


def _fits_column_once_escaped(value: str) -> str:
    if len(sanitize_text(value)) > _STORED_TEXT_MAX:
        raise ValueError(
            f"too long: at most {_STORED_TEXT_MAX} characters once special characters (& < > \" ') are escaped"
        )
    return value


# Required names (full_name, course/session name).
EscapedName = Annotated[str, Field(min_length=1, max_length=_STORED_TEXT_MAX), AfterValidator(_fits_column_once_escaped)]
# Optional labels (venue_name, device_name).
EscapedLabel = Annotated[str, Field(max_length=_STORED_TEXT_MAX), AfterValidator(_fits_column_once_escaped)]


# API-SPECIFICATION.md "Pagination": max 100 per page. Larger requests are
# capped rather than rejected, so a client asking for more still gets a
# valid page (the response's `limit` shows the size actually used).
MAX_PAGE_SIZE = 100


def page_limit(limit: int) -> int:
    return min(limit, MAX_PAGE_SIZE)


class Page(BaseModel, Generic[T]):
    """Standard list-endpoint envelope per API-SPECIFICATION.md's Task 2.1:
    { "items": [...], "total": N, "limit": N, "offset": N }"""

    items: List[T]
    total: int
    limit: int
    offset: int
