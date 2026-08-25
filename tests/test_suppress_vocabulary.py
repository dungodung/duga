from datetime import datetime, timezone

import pytest

from app.extensions import db
from app.models import AuditLog, Concept, Term
from scripts import suppress_vocabulary


def make_concept():
    concept = Concept(local_label="a concept", created_by="Someone", created_at=datetime.now(timezone.utc))
    db.session.add(concept)
    db.session.commit()
    return concept


def make_term(concept):
    now = datetime.now(timezone.utc)
    term = Term(
        concept_id=concept.id,
        language_code="sr",
        written_form="реч",
        register="unknown",
        evidence_grade="single_report",
        lifecycle="local",
        created_by="Someone",
        created_at=now,
        updated_at=now,
    )
    db.session.add(term)
    db.session.commit()
    return term


def test_suppress_concept_sets_flag_and_audit_logs(app):
    with app.app_context():
        concept = make_concept()
        suppress_vocabulary.suppress("concept", concept.id, "test reason", "dungodung")

        refreshed = db.session.get(Concept, concept.id)
        assert refreshed.suppressed is True

        entry = AuditLog.query.filter_by(action="suppress_concept").first()
        assert entry is not None
        assert entry.actor == "dungodung"


def test_suppress_term_sets_flag(app):
    with app.app_context():
        concept = make_concept()
        term = make_term(concept)
        suppress_vocabulary.suppress("term", term.id, "test reason", "dungodung")

        assert db.session.get(Term, term.id).suppressed is True


def test_unsuppress_clears_flag(app):
    with app.app_context():
        concept = make_concept()
        suppress_vocabulary.suppress("concept", concept.id, "reason", "dungodung")
        suppress_vocabulary.unsuppress("concept", concept.id, "dungodung")

        assert db.session.get(Concept, concept.id).suppressed is False


def test_suppress_unknown_id_exits_nonzero(app):
    with app.app_context():
        with pytest.raises(SystemExit) as exc_info:
            suppress_vocabulary.suppress("term", 9999, "reason", "dungodung")
        assert exc_info.value.code != 0


def test_main_requires_reason_when_suppressing(app):
    with app.app_context():
        concept_id = make_concept().id
    import sys

    argv = sys.argv
    sys.argv = ["suppress_vocabulary.py", "concept", str(concept_id), "--by", "dungodung"]
    try:
        with pytest.raises(SystemExit):
            suppress_vocabulary.main()
    finally:
        sys.argv = argv
