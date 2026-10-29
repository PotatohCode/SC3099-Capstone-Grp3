"""Add checkins.entry_method and checkins.override_previous for manual check-ins

Revision ID: b9d4e1f7a2c6
Revises: a6c1e93d7f52
Create Date: 2026-10-27 12:00:00.000000

Staff can now check a student in by hand (POST /checkins/manual), either
creating a record or approving a flagged/appealed/rejected one in place.
entry_method says which: app (the student's own check-in), manual (created
by staff) or override (approved by staff over an earlier outcome).
override_previous holds the overridden status/reviewer/notes as JSON, so
POST /checkins/{id}/manual/undo can restore them exactly.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b9d4e1f7a2c6'
down_revision: Union[str, None] = 'a6c1e93d7f52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'checkins', sa.Column('entry_method', sa.String(length=20), nullable=False, server_default='app')
    )
    op.add_column('checkins', sa.Column('override_previous', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('checkins', 'override_previous')
    op.drop_column('checkins', 'entry_method')
