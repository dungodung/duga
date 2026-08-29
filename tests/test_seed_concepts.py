"""scripts/seed_concepts.py -- the mechanism for SPEC.md section 16's seed
concept list. The list itself is a community decision and is deliberately
not in this repo; these cover the loader's guarantees."""
import json

import pytest

from app.extensions import db
from app.models import AuditLog, Concept, Term
from scripts import seed_concepts

LANGS = {"sr", "fr"}


def payload(*concepts):
    return {"concepts": list(concepts)}


def a_concept(label="genderqueer", terms=None):
    return {"local_label": label, "terms": terms if terms is not None else []}


def a_term(written_form="родно квир", language_code="sr", **extra):
    return {"written_form": written_form, "language_code": language_code, **extra}


def test_creates_concepts_and_terms(app):
    with app.app_context():
        created = seed_concepts.load(payload(a_concept(terms=[a_term()])), "dungodung")
        assert created == (1, 1, 0)

        concept = Concept.query.one()
        assert concept.local_label == "genderqueer"
        assert concept.lifecycle == "local"
        assert concept.qid is None
        assert concept.created_by == "dungodung"

        term = Term.query.one()
        assert term.written_form == "родно квир"
        assert term.lifecycle == "local"
        # SPEC.md section 8: seeded terms earn their grade like any other.
        assert term.evidence_grade == "single_report"


def test_is_idempotent(app):
    with app.app_context():
        data = payload(a_concept(terms=[a_term()]))
        seed_concepts.load(data, "dungodung")
        second = seed_concepts.load(data, "dungodung")

        assert second == (0, 0, 2)
        assert Concept.query.count() == 1
        assert Term.query.count() == 1


def test_matches_an_existing_concept_case_insensitively(app):
    with app.app_context():
        seed_concepts.load(payload(a_concept(label="Genderqueer")), "dungodung")
        seed_concepts.load(payload(a_concept(label="genderqueer", terms=[a_term()])), "dungodung")

        assert Concept.query.count() == 1
        assert Term.query.one().concept_id == Concept.query.one().id


def test_dry_run_writes_nothing(app):
    with app.app_context():
        counts = seed_concepts.load(payload(a_concept(terms=[a_term()])), "dungodung", dry_run=True)
        assert counts == (1, 1, 0)
        assert Concept.query.count() == 0
        assert Term.query.count() == 0


def test_logs_every_creation(app):
    with app.app_context():
        seed_concepts.load(payload(a_concept(terms=[a_term()])), "dungodung")

        assert AuditLog.query.filter_by(action="create_concept").count() == 1
        entry = AuditLog.query.filter_by(action="create_term").one()
        assert "seed_concepts" in entry.after_json


def test_rejects_an_unseeded_language(app):
    with app.app_context():
        with pytest.raises(seed_concepts.SeedError) as exc:
            seed_concepts.validate(payload(a_concept(terms=[a_term(language_code="de")])), LANGS)
        assert "not a seeded content language" in str(exc.value)


def test_rejects_an_invalid_register(app):
    with app.app_context():
        with pytest.raises(seed_concepts.SeedError) as exc:
            seed_concepts.validate(payload(a_concept(terms=[a_term(register="rude")])), LANGS)
        assert "register" in str(exc.value)


def test_rejects_an_upstream_link(app):
    """Seeding must not become a second, weaker promotion path -- linking
    to Wikidata goes through M7's live existence check (SPEC.md section 10)."""
    with app.app_context():
        with pytest.raises(seed_concepts.SeedError) as exc:
            seed_concepts.validate(payload({"local_label": "x", "qid": "Q42", "terms": []}), LANGS)
        assert "not seedable" in str(exc.value)

        with pytest.raises(seed_concepts.SeedError):
            seed_concepts.validate(payload(a_concept(terms=[a_term(lexeme_id="L1")])), LANGS)


def test_rejects_a_seeded_evidence_grade(app):
    with app.app_context():
        with pytest.raises(seed_concepts.SeedError):
            seed_concepts.validate(payload(a_concept(terms=[a_term(evidence_grade="documented")])), LANGS)


def test_reports_every_problem_at_once(app):
    """Validation runs over the whole file before anything is written, so
    one bad entry can't leave a half-loaded database behind."""
    with app.app_context():
        with pytest.raises(seed_concepts.SeedError) as exc:
            seed_concepts.validate(
                payload(a_concept(label=""), a_concept(terms=[a_term(language_code="xx")])), LANGS
            )
        assert "local_label is required" in str(exc.value)
        assert "not a seeded content language" in str(exc.value)


def test_the_example_file_is_valid_against_its_own_documentation(app):
    """The shipped example is the format's documentation, so it has to pass
    the validator it documents."""
    import os

    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "seed_concepts.example.json")
    with app.app_context():
        with open(path, encoding="utf-8") as fh:
            seed_concepts.validate(json.load(fh), LANGS)
