"""The top-ten-Wikipedia language seed (migration b3f1c07a5e92).

Tests build their schema with db.create_all(), so migration *data* is never
exercised by the rest of the suite. This is the one check worth having
anyway: `language.code` is a primary key, so a code that overlaps an
earlier seed would make the migration fail on the production database --
after it had already been reviewed and merged.
"""
import importlib.util
import os

MIGRATIONS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations", "versions")


def _load(filename):
    path = os.path.join(MIGRATIONS, filename)
    spec = importlib.util.spec_from_file_location(filename[:-3], path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_new_languages_do_not_collide_with_the_m2_seed():
    new = _load("b3f1c07a5e92_seed_top_ten_wikipedia_languages.py")
    codes = {row["code"] for row in new.NEW_LANGUAGES}
    # 822be768fd1c already seeds sr and fr.
    assert codes.isdisjoint({"sr", "fr"})
    assert len(codes) == len(new.NEW_LANGUAGES), "duplicate code within the migration"


def test_new_languages_are_the_measured_top_ten_minus_what_is_already_seeded():
    new = _load("b3f1c07a5e92_seed_top_ten_wikipedia_languages.py")
    codes = {row["code"] for row in new.NEW_LANGUAGES}
    # Top ten Wikipedias by article count as measured on 2026-08-29; fr is
    # already seeded, so nine rows are new. Pinned here so that changing the
    # list is a deliberate edit to a test, not a silent drift.
    assert codes == {"en", "ceb", "de", "sv", "nl", "es", "ru", "it", "pl"}


def test_every_new_language_has_a_non_empty_autonym():
    new = _load("b3f1c07a5e92_seed_top_ten_wikipedia_languages.py")
    for row in new.NEW_LANGUAGES:
        assert row["autonym"].strip(), row["code"]


def test_the_migration_chains_onto_the_current_head():
    new = _load("b3f1c07a5e92_seed_top_ten_wikipedia_languages.py")
    assert new.down_revision == "c2669d54cd43"
