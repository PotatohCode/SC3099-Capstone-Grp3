"""Shared response envelopes and cross-schema types."""
from typing import Generic, List, Literal, TypeVar

from pydantic import BaseModel

T = TypeVar("T")

# Single source of truth for the role literal - schemas/auth.py re-exports
# this (RegisterRequest imports Role from there historically), and
# schemas/user.py uses it directly for admin role reassignment. Defined
# here rather than in auth.py to avoid a user.py <-> auth.py import cycle
# (auth.py already imports UserResponse from user.py).
Role = Literal["student", "instructor", "ta", "admin"]


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
