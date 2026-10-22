"""Escape existing course and session names

Revision ID: a6c1e93d7f52
Revises: f3a9c2d84b17
Create Date: 2026-10-22 23:30:00.000000

Course name/venue_name and session name/venue_name are now HTML-escaped
when stored, like every other free-text field (services/sanitize.py).
Rows saved before that were stored raw, so escape them once here, using the
same function. Data only, no schema change.

Runs once (Alembic records it), so values are never double-escaped. A value
that would no longer fit its VARCHAR(255) once escaped is left as it is
(the API now refuses such input with a 422).

Not reversible: there's no way to tell an escaped value from raw text that
happened to contain "&amp;". downgrade() is a no-op.
"""
import html
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a6c1e93d7f52'
down_revision: Union[str, None] = 'f3a9c2d84b17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = {"courses": ("name", "venue_name"), "sessions": ("name", "venue_name")}
_MAX = 255


def upgrade() -> None:
    conn = op.get_bind()
    for table, columns in _COLUMNS.items():
        for column in columns:
            rows = conn.execute(
                sa.text(f"SELECT id, {column} FROM {table} WHERE {column} ~ '[&<>\"'']'")
            ).fetchall()
            for row_id, value in rows:
                escaped = html.escape(value, quote=True)
                if escaped != value and len(escaped) <= _MAX:
                    conn.execute(
                        sa.text(f"UPDATE {table} SET {column} = :v WHERE id = :id"), {"v": escaped, "id": row_id}
                    )


def downgrade() -> None:
    pass
