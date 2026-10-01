"""Add checkins.liveness_image_hash for replay detection

Revision ID: d5a7e9c13b26
Revises: c3d81f5a2e47
Create Date: 2026-10-01 21:00:00.000000

SHA-256 of the submitted liveness image bytes (never the image). Used to
reject a student re-submitting a previously captured photo.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5a7e9c13b26'
down_revision: Union[str, None] = 'c3d81f5a2e47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('checkins', sa.Column('liveness_image_hash', sa.String(length=64), nullable=True))
    op.create_index(op.f('ix_checkins_liveness_image_hash'), 'checkins', ['liveness_image_hash'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_checkins_liveness_image_hash'), table_name='checkins')
    op.drop_column('checkins', 'liveness_image_hash')
