"""Shared helpers for model definitions."""
import uuid


def gen_uuid() -> str:
    """Default value for VARCHAR(36) UUID primary keys."""
    return str(uuid.uuid4())
