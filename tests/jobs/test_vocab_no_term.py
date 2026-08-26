from datetime import datetime, timezone

import responses

from app.extensions import db
from app.models import Concept, Detector, Gap, Language, ScopeVersion, Term, Topic
from jobs import vocab_no_term

API_URL = "https://www.wikidata.org/w/api.php"


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


def entities_response(entities):
    return {"entities": entities}


def entity(label=None, language="sr"):
    return {"labels": ({language: {"value": label, "language": language}} if label is not None else {})}


@responses.activate
def test_run_flags_topics_with_no_local_term(app):
    with app.app_context():
        seed_active_scope_version()
        seed_topic("Q1", is_living=False)  # has a term -> covered
        seed_topic("Q2", is_living=False)  # no concept at all -> gap
        seed_topic("Q3", is_living=True)  # excluded by S7 regardless
        seed_languages("sr")
        seed_concept_with_term("Q1", "sr", "реч")

        responses.add(
            responses.GET,
            API_URL,
            json=entities_response({"Q2": entity(label="Second Topic")}),
            status=200,
        )
        vocab_no_term.run(app)

        gaps = Gap.query.filter_by(language_code="sr").all()
        assert {g.topic_qid for g in gaps} == {"Q2"}
        assert gaps[0].project_code == "vocabulary"
        assert gaps[0].gap_type == "no_term"
        assert gaps[0].action_url == "/sr/vocabulary#add-term-form"
        assert '"label": "Second Topic"' in gaps[0].evidence_json

        detector = Detector.query.filter_by(detector_key="vocab_no_term").first()
        assert detector.maturity == "experimental"
        assert detector.enabled is False


@responses.activate
def test_run_treats_suppressed_term_as_still_missing(app):
    with app.app_context():
        seed_active_scope_version()
        seed_topic("Q1", is_living=False)
        seed_languages("sr")
        seed_concept_with_term("Q1", "sr", "реч", term_suppressed=True)

        responses.add(
            responses.GET, API_URL,
            json=entities_response({"Q1": entity(label="First Topic")}),
            status=200,
        )
        vocab_no_term.run(app)

        assert Gap.query.filter_by(language_code="sr").count() == 1


@responses.activate
def test_run_treats_suppressed_concept_as_still_missing(app):
    with app.app_context():
        seed_active_scope_version()
        seed_topic("Q1", is_living=False)
        seed_languages("sr")
        seed_concept_with_term("Q1", "sr", "реч", concept_suppressed=True)

        responses.add(
            responses.GET, API_URL,
            json=entities_response({"Q1": entity(label="First Topic")}),
            status=200,
        )
        vocab_no_term.run(app)

        assert Gap.query.filter_by(language_code="sr").count() == 1


@responses.activate
def test_run_is_idempotent(app):
    with app.app_context():
        seed_active_scope_version()
        seed_topic("Q1", is_living=False)
        seed_languages("sr")

        responses.add(
            responses.GET, API_URL,
            json=entities_response({"Q1": entity(label="First Topic")}),
            status=200,
        )
        vocab_no_term.run(app)
        assert Gap.query.count() == 1

        seed_concept_with_term("Q1", "sr", "реч")
        vocab_no_term.run(app)
        assert Gap.query.count() == 0
