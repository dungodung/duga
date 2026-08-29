"""Drop Cebuano as a tracked content language

Revision ID: e51d9b3a7c04
Revises: c8a4d21f6b73
Create Date: 2026-08-29 22:02:44.907213

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'e51d9b3a7c04'
down_revision = 'c8a4d21f6b73'
branch_labels = None
depends_on = None


# `ceb` was seeded by b3f1c07a5e92 because it is the second-largest
# Wikipedia by article count. Article count turned out to be the wrong
# measure for it: cebwiki is overwhelmingly bot-generated (~6.1M articles,
# ~230 active editors), so tracking it would produce one of the largest gap
# lists in the tool with almost nobody there to act on it -- and every
# detector pays for it nightly, since they loop languages x topics.
#
# Removing a content language is a data decision, not a schema one, so it
# gets its own migration rather than an edit to b3f1c07a5e92: that
# migration has already run in production and rewriting history would leave
# the deployed database and the repo disagreeing about what happened.
LANGUAGE_CODE = 'ceb'


def upgrade():
    # Nothing had been generated for ceb when this was written -- the
    # detectors had not yet run for it. The deletes are still here because
    # this migration may be applied to a database where they had, and a
    # language row disappearing while its gaps stayed behind would leave
    # rows no view can reach and no detector will ever clean up.
    for table, column in (
        ("gap", "language_code"),
        ("gap_override", "language_code"),
        ("pageview_cache", "language_code"),
    ):
        op.execute(f"DELETE FROM {table} WHERE {column} = '{LANGUAGE_CODE}'")
    # `term` is deliberately NOT cleaned out: a term is something a person
    # typed, not something a detector computed, and SPEC.md section 10
    # treats local vocabulary as the contributor's own work. If any Cebuano
    # term ever exists, it should be suppressed by a human decision, not
    # deleted by a migration.
    op.execute(f"DELETE FROM language WHERE code = '{LANGUAGE_CODE}'")


def downgrade():
    op.execute(
        "INSERT INTO language (code, autonym, seeded) "
        f"VALUES ('{LANGUAGE_CODE}', 'Cebuano', 1)"
    )
