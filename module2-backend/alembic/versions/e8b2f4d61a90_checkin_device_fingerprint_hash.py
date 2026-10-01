"""Add checkins.device_fingerprint_hash for proxy sign-in detection

Revision ID: e8b2f4d61a90
Revises: d5a7e9c13b26
Create Date: 2026-10-01 21:30:00.000000

SHA-256 of the client's device_fingerprint (never the raw value). Used to
flag one device checking in several different students in quick succession.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8b2f4d61a90'
down_revision: Union[str, None] = 'd5a7e9c13b26'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('checkins', sa.Column('device_fingerprint_hash', sa.String(length=64), nullable=True))
    op.create_index(op.f('ix_checkins_device_fingerprint_hash'), 'checkins', ['device_fingerprint_hash'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_checkins_device_fingerprint_hash'), table_name='checkins')
    op.drop_column('checkins', 'device_fingerprint_hash')
