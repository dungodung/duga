"""Vocabulary detector project

Revision ID: c2669d54cd43
Revises: 4eaa3f76db75
Create Date: 2026-08-26 06:39:27.244091

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c2669d54cd43'
down_revision = '4eaa3f76db75'
branch_labels = None
depends_on = None


def upgrade():
    project = sa.table('project', sa.column('code', sa.String), sa.column('family', sa.String))
    op.bulk_insert(project, [
        {'code': 'vocabulary', 'family': 'duga'},
    ])


def downgrade():
    op.execute("DELETE FROM project WHERE code = 'vocabulary'")
