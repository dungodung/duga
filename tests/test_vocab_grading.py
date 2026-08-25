from datetime import datetime, timezone

from app.extensions import db
from app.models import Concept, Term, TermAssertion, TermEvidence
from app.vocab_grading import recompute_evidence_grade


def make_term(app):
    now = datetime.now(timezone.utc)
    concept = Concept(local_label="test concept", created_by="Someone", created_at=now)
    db.session.add(concept)
    db.session.flush()
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


def add_evidence(term, kind):
    db.session.add(
        TermEvidence(
            term_id=term.id,
            kind=kind,
            citation="citation text",
            added_by="Someone",
            added_at=datetime.now(timezone.utc),
        )
    )
    db.session.commit()
    db.session.refresh(term)


def add_assertion(term, contributor, agrees=True):
    db.session.add(
        TermAssertion(term_id=term.id, contributor=contributor, agrees=agrees, created_at=datetime.now(timezone.utc))
    )
    db.session.commit()
    db.session.refresh(term)


def test_new_term_grades_single_report(app):
    with app.app_context():
        term = make_term(app)
        assert recompute_evidence_grade(term) == "single_report"


def test_documented_evidence_grades_documented(app):
    with app.app_context():
        term = make_term(app)
        add_evidence(term, "dictionary")
        assert recompute_evidence_grade(term) == "documented"


def test_organisation_evidence_grades_organisational(app):
    with app.app_context():
        term = make_term(app)
        add_evidence(term, "organisation")
        assert recompute_evidence_grade(term) == "organisational"


def test_other_evidence_does_not_upgrade_grade(app):
    with app.app_context():
        term = make_term(app)
        add_evidence(term, "other")
        assert recompute_evidence_grade(term) == "single_report"


def test_below_threshold_assertions_stay_single_report(app):
    with app.app_context():
        term = make_term(app)
        add_assertion(term, "A")
        add_assertion(term, "B")
        assert recompute_evidence_grade(term) == "single_report"


def test_threshold_assertions_grade_community(app):
    with app.app_context():
        term = make_term(app)
        add_assertion(term, "A")
        add_assertion(term, "B")
        add_assertion(term, "C")
        assert recompute_evidence_grade(term) == "community"


def test_disagreeing_assertions_do_not_count_toward_community(app):
    with app.app_context():
        term = make_term(app)
        add_assertion(term, "A", agrees=False)
        add_assertion(term, "B", agrees=False)
        add_assertion(term, "C", agrees=False)
        assert recompute_evidence_grade(term) == "single_report"


def test_documented_evidence_outranks_community_assertions(app):
    with app.app_context():
        term = make_term(app)
        add_assertion(term, "A")
        add_assertion(term, "B")
        add_assertion(term, "C")
        add_evidence(term, "law")
        assert recompute_evidence_grade(term) == "documented"


def test_configurable_threshold(app):
    with app.app_context():
        app.config["DUGA_COMMUNITY_ASSERTION_THRESHOLD"] = 1
        term = make_term(app)
        add_assertion(term, "A")
        assert recompute_evidence_grade(term) == "community"
