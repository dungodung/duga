"""Commons detector project

Revision ID: 4eaa3f76db75
Revises: 6255d6f3ff0b
Create Date: 2026-08-26 06:05:39.142964

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4eaa3f76db75'
down_revision = '6255d6f3ff0b'
branch_labels = None
depends_on = None


def upgrade():
    project = sa.table('project', sa.column('code', sa.String), sa.column('family', sa.String))
    op.bulk_insert(project, [
        {'code': 'commons', 'family': 'commons'},
    ])


def downgrade():
    op.execute("DELETE FROM project WHERE code = 'commons'")
