"""Partial updates (PUT /courses/{id}, PATCH /sessions/{id}, PATCH /users/{id}).

Update schemas make every field optional, so a client can send an explicit
`null`. For a NOT NULL column that used to reach the database and fail with
an IntegrityError (500). A null can't clear a required value, so it's
ignored, the same as leaving the field out. Nullable columns (e.g.
description, venue_name) can still be cleared with null.
"""
from typing import Any

from app.db.base import Base


def drop_nulls_for_required(model: type[Base], updates: dict[str, Any]) -> dict[str, Any]:
    columns = model.__table__.columns
    return {
        field: value
        for field, value in updates.items()
        if value is not None or field not in columns or columns[field].nullable
    }
