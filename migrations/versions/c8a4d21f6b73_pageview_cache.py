"""pageview_cache: one completed month's pageviews per (topic, language)

Revision ID: c8a4d21f6b73
Revises: b3f1c07a5e92
Create Date: 2026-08-29 20:14:52.118374

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c8a4d21f6b73'
down_revision = 'b3f1c07a5e92'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'pageview_cache',
        sa.Column('topic_qid', sa.String(length=16), nullable=False),
        sa.Column('language_code', sa.String(length=20), nullable=False),
        sa.Column('month', sa.String(length=7), nullable=False),
        sa.Column('views', sa.Integer(), nullable=False),
        sa.Column('fetched_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('topic_qid', 'language_code', 'month'),
    )
    with op.batch_alter_table('pageview_cache', schema=None) as batch_op:
        batch_op.create_index('ix_pageview_cache_month', ['month'], unique=False)


def downgrade():
    with op.batch_alter_table('pageview_cache', schema=None) as batch_op:
        batch_op.drop_index('ix_pageview_cache_month')
    op.drop_table('pageview_cache')
