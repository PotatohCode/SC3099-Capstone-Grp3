"""Token cut-off on users (a password change ends the user's other sessions)

Revision ID: a4c7e2b9d153
Revises: b9d4e1f7a2c6
Create Date: 2026-11-02 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4c7e2b9d153'
down_revision: Union[str, None] = 'b9d4e1f7a2c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('tokens_valid_after', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('kept_session_id', sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'kept_session_id')
    op.drop_column('users', 'tokens_valid_after')
