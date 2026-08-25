"""S1+ sitelink detector projects

Revision ID: 6255d6f3ff0b
Revises: 4b924db3132a
Create Date: 2026-08-25 22:17:24.766558

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6255d6f3ff0b'
down_revision = '4b924db3132a'
branch_labels = None
depends_on = None


def upgrade():
    project = sa.table('project', sa.column('code', sa.String), sa.column('family', sa.String))
    op.bulk_insert(project, [
        {'code': 'wiktionary', 'family': 'wiktionary'},
        {'code': 'wikiquote', 'family': 'wikiquote'},
        {'code': 'wikisource', 'family': 'wikisource'},
    ])


def downgrade():
    op.execute("DELETE FROM project WHERE code IN ('wiktionary', 'wikiquote', 'wikisource')")
