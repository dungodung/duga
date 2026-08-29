"""Seed the top ten Wikipedia languages as content languages

Revision ID: b3f1c07a5e92
Revises: c2669d54cd43
Create Date: 2026-08-29 19:02:11.400318

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b3f1c07a5e92'
down_revision = 'c2669d54cd43'
branch_labels = None
depends_on = None


# The ten largest Wikipedias by article count, measured against each wiki's
# own action=query&meta=siteinfo on 2026-08-29 rather than taken from
# memory: en, ceb, de, fr, sv, nl, es, ru, it, pl. `fr` is already seeded by
# 822be768fd1c and `sr` stays seeded although it isn't in the top ten -- it
# is the conference language and removing it would be a silent regression.
#
# Autonyms come from action=query&meta=languageinfo on the same date, with
# the first letter capitalised to match the existing sr/fr rows (MediaWiki
# returns "español"/"italiano"/"polski" lowercase). Language codes are
# Wikimedia's, not ISO's, per SPEC.md section 13.
#
# Content languages only. These are NOT interface languages -- app/i18n.py's
# AUTONYMS and i18n/*.json stay at en/sr/fr, and SPEC.md section 13 keeps
# the two independent on purpose: you can browse German gaps with a Serbian
# interface without anyone having translated Duga's chrome into German.
NEW_LANGUAGES = [
    {'code': 'en', 'autonym': 'English'},
    {'code': 'ceb', 'autonym': 'Cebuano'},
    {'code': 'de', 'autonym': 'Deutsch'},
    {'code': 'sv', 'autonym': 'Svenska'},
    {'code': 'nl', 'autonym': 'Nederlands'},
    {'code': 'es', 'autonym': 'Español'},
    {'code': 'ru', 'autonym': 'Русский'},
    {'code': 'it', 'autonym': 'Italiano'},
    {'code': 'pl', 'autonym': 'Polski'},
]


def upgrade():
    language = sa.table(
        'language',
        sa.column('code', sa.String),
        sa.column('autonym', sa.String),
        sa.column('seeded', sa.Boolean),
    )
    op.bulk_insert(language, [dict(row, seeded=True) for row in NEW_LANGUAGES])


def downgrade():
    codes = ", ".join(repr(row['code']) for row in NEW_LANGUAGES)
    op.execute(f"DELETE FROM language WHERE code IN ({codes})")
