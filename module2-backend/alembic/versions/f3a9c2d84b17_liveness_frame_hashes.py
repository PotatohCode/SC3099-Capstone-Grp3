"""Add liveness_frame_hashes for per-frame replay detection

Revision ID: f3a9c2d84b17
Revises: e8b2f4d61a90
Create Date: 2026-10-20 12:00:00.000000

Check-ins can now send a burst of frames instead of one photo. One hash
column on checkins can't answer "was ANY of these frames used before", so
each submitted image's SHA-256 goes in its own row, indexed by
(student_id, frame_hash). Existing checkins.liveness_image_hash values are
copied in, so photos used before this migration still count as replays.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3a9c2d84b17'
down_revision: Union[str, None] = 'e8b2f4d61a90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'liveness_frame_hashes',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('checkin_id', sa.String(length=36), nullable=False),
        sa.Column('student_id', sa.String(length=36), nullable=False),
        sa.Column('frame_hash', sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(['checkin_id'], ['checkins.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['student_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_liveness_frame_hashes_checkin_id'), 'liveness_frame_hashes', ['checkin_id'], unique=False)
    op.create_index(
        'ix_liveness_frame_hashes_student_hash', 'liveness_frame_hashes', ['student_id', 'frame_hash'], unique=False
    )
    # Backfill: md5(id) gives each row a unique 32-char id without needing
    # an extension (ids are opaque strings everywhere in this schema).
    op.execute(
        """
        INSERT INTO liveness_frame_hashes (id, checkin_id, student_id, frame_hash)
        SELECT md5('frame-backfill-' || id), id, student_id, liveness_image_hash
        FROM checkins
        WHERE liveness_image_hash IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index('ix_liveness_frame_hashes_student_hash', table_name='liveness_frame_hashes')
    op.drop_index(op.f('ix_liveness_frame_hashes_checkin_id'), table_name='liveness_frame_hashes')
    op.drop_table('liveness_frame_hashes')
