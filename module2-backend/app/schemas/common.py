"""Shared response envelopes."""
from typing import Generic, List, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Standard list-endpoint envelope per API-SPECIFICATION.md's Task 2.1:
    { "items": [...], "total": N, "limit": N, "offset": N }"""

    items: List[T]
    total: int
    limit: int
    offset: int
