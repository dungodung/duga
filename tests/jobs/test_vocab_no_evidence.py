import json
from datetime import datetime, timezone

from app.extensions import db
from app.models import Concept, Detector, Gap, Language, ScopeVersion, Term, TermEvidence, Topic
from jobs import vocab_no_evidence


def seed_active_scope_version():
    version = ScopeVersion(
        source_page="Wikidata:WikiProject LGBT/Duga/scope",
        revision_id=1,
        raw_json="{}",
        fetched_at=datetime.now(timezone.utc),
        active=True,
    )
    db.session.add(version)
    db.session.commit()


def seed_topic(qid, is_living=True):
    now = datetime.now(timezone.utc)
    db.session.add(
        Topic(qid=qid, entity_class="human", is_human=True, is_living=is_living, first_seen=now, last_seen=now)
    )
    db.session.commit()


def seed_languages(*codes):
    for code in codes:
        db.session.add(Language(code=code, autonym=code, seeded=True))
    db.session.commit()


def seed_concept_with_term(qid, language_code, written_form, concept_suppressed=False, term_suppressed=False):
    now = datetime.now(timezone.utc)
    concept = Concept(qid=qid, local_label=written_form, created_by="tester", created_at=now, suppressed=concept_suppressed)
    db.session.add(concept)
    db.session.flush()
    term = Term(
        concept_id=concept.id,
        language_code=language_code,
        written_form=written_form,
        created_by="tester",
        created_at=now,
        updated_at=now,
        suppressed=term_suppressed,
    )
    db.session.add(term)
    db.session.commit()
    return concept, term


def add_evidence(term):
    db.session.add(
        TermEvidence(
            term_id=term.id,
            kind="publication",
            citation="Some source",
            added_by="tester",
            added_at=datetime.now(timezone.utc),
        )
    )
    db.session.commit()


def test_run_flags_terms_with_no_evidence(app):
    with app.app_context():
        seed_active_scope_version()
        seed_topic("Q1", is_living=False)  # has evidence -> covered
        seed_topic("Q2", is_living=False)  # no evidence -> gap
        seed_topic("Q3", is_living=True)  # excluded by S7 regardless
        seed_languages("sr")

        _, term1 = seed_concept_with_term("Q1", "sr", "реч1")
        add_evidence(term1)
        seed_concept_with_term("Q2", "sr", "реч2")
        seed_concept_with_term("Q3", "sr", "реч3")

        vocab_no_evidence.run(app)

        gaps = Gap.query.filter_by(language_code="sr").all()
        assert {g.topic_qid for g in gaps} == {"Q2"}
        assert gaps[0].project_code == "vocabulary"
        assert gaps[0].gap_type == "no_evidence"
        assert json.loads(gaps[0].evidence_json)["label"] == "реч2"  # the term's own written form

        detector = Detector.query.filter_by(detector_key="vocab_no_evidence").first()
        assert detector.maturity == "experimental"
        assert detector.enabled is False


def test_action_url_links_directly_to_the_under_evidenced_term(app):
    with app.app_context():
        seed_active_scope_version()
        seed_topic("Q1", is_living=False)
        seed_languages("sr")
        _, term = seed_concept_with_term("Q1", "sr", "реч")

        vocab_no_evidence.run(app)

        gap = Gap.query.filter_by(language_code="sr").first()
        assert gap.action_url == f"/sr/vocabulary/{term.id}#add-evidence-form"
        assert '"_action_url"' not in gap.evidence_json


def test_run_ignores_a_term_whose_concept_has_no_qid(app):
    with app.app_context():
        seed_active_scope_version()
        seed_languages("sr")
        now = datetime.now(timezone.utc)
        concept = Concept(qid=None, local_label="purely local", created_by="tester", created_at=now)
        db.session.add(concept)
        db.session.flush()
        db.session.add(
            Term(
                concept_id=concept.id,
                language_code="sr",
                written_form="реч",
                created_by="tester",
                created_at=now,
                updated_at=now,
            )
        )
        db.session.commit()

        vocab_no_evidence.run(app)

        assert Gap.query.count() == 0


def test_run_is_idempotent(app):
    with app.app_context():
        seed_active_scope_version()
        seed_topic("Q1", is_living=False)
        seed_languages("sr")
        _, term = seed_concept_with_term("Q1", "sr", "реч")

        vocab_no_evidence.run(app)
        assert Gap.query.count() == 1

        add_evidence(term)
        vocab_no_evidence.run(app)
        assert Gap.query.count() == 0
