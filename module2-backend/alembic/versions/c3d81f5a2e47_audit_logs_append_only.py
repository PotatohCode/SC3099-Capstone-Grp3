"""Make audit_logs append-only at the database level

Revision ID: c3d81f5a2e47
Revises: b7e2c4a91f03
Create Date: 2026-10-01 20:00:00.000000

SECURITY-REQUIREMENTS.md / Briefing: audit logs "cannot be modified or
deleted ... using append-only tables". The API already exposes no way to
change them; this enforces it in Postgres too, so even direct SQL can only
INSERT and SELECT. Nothing in the backend updates or deletes audit rows
(retention anonymises users/check-ins in place, and audit_logs.user_id has
no ON DELETE action).
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c3d81f5a2e47'
down_revision: Union[str, None] = 'b7e2c4a91f03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION audit_logs_block_changes() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs is append-only: % is not allowed', TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER audit_logs_no_update_delete
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION audit_logs_block_changes();
    """)
    op.execute("""
        CREATE TRIGGER audit_logs_no_truncate
        BEFORE TRUNCATE ON audit_logs
        FOR EACH STATEMENT EXECUTE FUNCTION audit_logs_block_changes();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_logs_no_truncate ON audit_logs;")
    op.execute("DROP TRIGGER IF EXISTS audit_logs_no_update_delete ON audit_logs;")
    op.execute("DROP FUNCTION IF EXISTS audit_logs_block_changes();")
