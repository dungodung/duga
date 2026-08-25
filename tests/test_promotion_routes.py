from datetime import datetime, timezone

import responses

from app.extensions import db
from app.models import AuditLog, Concept, Term

API_URL = "https://www.wikidata.org/w/api.php"


def make_concept(lifecycle="local", qid=None, local_label="Some Concept"):
    concept = Concept(
        local_label=local_label,
        lifecycle=lifecycle,
        qid=qid,
        created_by="SomeoneElse",
        created_at=datetime.now(timezone.utc),
    )
    db.session.add(concept)
    db.session.commit()
    return concept


def make_term(concept, lifecycle="local", lang="sr", written_form="реч"):
    now = datetime.now(timezone.utc)
    term = Term(
        concept_id=concept.id,
        language_code=lang,
        written_form=written_form,
        register="neutral",
        evidence_grade="single_report",
        lifecycle=lifecycle,
        created_by="SomeoneElse",
        created_at=now,
        updated_at=now,
    )
    db.session.add(term)
    db.session.commit()
    return term


def mock_entity_found(entity_id):
    responses.add(
        responses.GET,
        API_URL,
        json={"entities": {entity_id: {"id": entity_id, "labels": {}}}},
        status=200,
    )


def mock_entity_missing(entity_id):
    responses.add(
        responses.GET,
        API_URL,
        json={"entities": {entity_id: {"id": entity_id, "missing": ""}}},
        status=200,
    )


# -- propose_concept -------------------------------------------------


def test_propose_concept_requires_login(client, db, seed_languages):
    concept = make_concept()
    resp = client.post(f"/concept/{concept.id}/propose")
    assert resp.status_code == 302
    assert "/login" in resp.location


def test_propose_concept_moves_local_to_proposed(client, db, seed_languages, logged_in):
    concept = make_concept(lifecycle="local")
    resp = client.post(f"/concept/{concept.id}/propose")
    assert resp.status_code == 302
    db.session.refresh(concept)
    assert concept.lifecycle == "proposed"

    entry = AuditLog.query.filter_by(action="propose_concept").first()
    assert entry is not None
    assert entry.entity_id == str(concept.id)


def test_propose_concept_rejects_non_local(client, db, seed_languages, logged_in):
    concept = make_concept(lifecycle="proposed")
    resp = client.post(f"/concept/{concept.id}/propose?uselang=en", follow_redirects=True)
    assert b"can only be proposed" in resp.data
    db.session.refresh(concept)
    assert concept.lifecycle == "proposed"


def test_propose_concept_404s_for_suppressed(client, db, seed_languages, logged_in):
    concept = make_concept(lifecycle="local")
    concept.suppressed = True
    db.session.commit()
    resp = client.post(f"/concept/{concept.id}/propose")
    assert resp.status_code == 404


# -- link_concept_upstream --------------------------------------------


def test_link_concept_upstream_requires_login(client, db, seed_languages):
    concept = make_concept(lifecycle="proposed")
    resp = client.post(f"/concept/{concept.id}/link-upstream", data={"qid": "Q42"})
    assert resp.status_code == 302
    assert "/login" in resp.location


def test_link_concept_upstream_rejects_not_proposed(client, db, seed_languages, logged_in):
    concept = make_concept(lifecycle="local")
    resp = client.post(f"/concept/{concept.id}/link-upstream?uselang=en", data={"qid": "Q42"}, follow_redirects=True)
    assert b"must be proposed" in resp.data
    db.session.refresh(concept)
    assert concept.qid is None


def test_link_concept_upstream_rejects_bad_qid_format(client, db, seed_languages, logged_in):
    concept = make_concept(lifecycle="proposed")
    resp = client.post(f"/concept/{concept.id}/link-upstream?uselang=en", data={"qid": "notaqid"}, follow_redirects=True)
    assert b"valid Wikidata item ID" in resp.data
    db.session.refresh(concept)
    assert concept.lifecycle == "proposed"


def test_link_concept_upstream_rejects_qid_already_taken(client, db, seed_languages, logged_in):
    make_concept(lifecycle="upstream", qid="Q42", local_label="Other Concept")
    concept = make_concept(lifecycle="proposed")
    resp = client.post(f"/concept/{concept.id}/link-upstream?uselang=en", data={"qid": "Q42"}, follow_redirects=True)
    assert b"already linked" in resp.data
    db.session.refresh(concept)
    assert concept.lifecycle == "proposed"


@responses.activate
def test_link_concept_upstream_rejects_nonexistent_entity(client, db, seed_languages, logged_in):
    mock_entity_missing("Q999999")
    concept = make_concept(lifecycle="proposed")
    resp = client.post(f"/concept/{concept.id}/link-upstream?uselang=en", data={"qid": "Q999999"}, follow_redirects=True)
    assert b"exist on Wikidata" in resp.data
    db.session.refresh(concept)
    assert concept.lifecycle == "proposed"


@responses.activate
def test_link_concept_upstream_success(client, db, seed_languages, logged_in):
    mock_entity_found("Q42")
    concept = make_concept(lifecycle="proposed")
    resp = client.post(f"/concept/{concept.id}/link-upstream", data={"qid": "Q42"})
    assert resp.status_code == 302
    db.session.refresh(concept)
    assert concept.lifecycle == "upstream"
    assert concept.qid == "Q42"

    entry = AuditLog.query.filter_by(action="link_concept_upstream").first()
    assert entry is not None


# -- propose_term ------------------------------------------------------


def test_propose_term_requires_login(client, db, seed_languages):
    concept = make_concept()
    term = make_term(concept)
    resp = client.post(f"/term/{term.id}/propose")
    assert resp.status_code == 302
    assert "/login" in resp.location


def test_propose_term_moves_local_to_proposed(client, db, seed_languages, logged_in):
    concept = make_concept()
    term = make_term(concept, lifecycle="local")
    resp = client.post(f"/term/{term.id}/propose")
    assert resp.status_code == 302
    db.session.refresh(term)
    assert term.lifecycle == "proposed"

    entry = AuditLog.query.filter_by(action="propose_term").first()
    assert entry is not None
    assert entry.entity_id == str(term.id)


def test_propose_term_rejects_non_local(client, db, seed_languages, logged_in):
    concept = make_concept()
    term = make_term(concept, lifecycle="upstream")
    resp = client.post(f"/term/{term.id}/propose?uselang=en", follow_redirects=True)
    assert b"can only be proposed" in resp.data
    db.session.refresh(term)
    assert term.lifecycle == "upstream"


# -- link_term_upstream -------------------------------------------------


def test_link_term_upstream_requires_login(client, db, seed_languages):
    concept = make_concept()
    term = make_term(concept, lifecycle="proposed")
    resp = client.post(f"/term/{term.id}/link-upstream", data={"lexeme_id": "L1"})
    assert resp.status_code == 302
    assert "/login" in resp.location


def test_link_term_upstream_rejects_not_proposed(client, db, seed_languages, logged_in):
    concept = make_concept()
    term = make_term(concept, lifecycle="local")
    resp = client.post(f"/term/{term.id}/link-upstream?uselang=en", data={"lexeme_id": "L1"}, follow_redirects=True)
    assert b"must be proposed" in resp.data
    db.session.refresh(term)
    assert term.lifecycle == "local"


def test_link_term_upstream_rejects_bad_lexeme_format(client, db, seed_languages, logged_in):
    concept = make_concept()
    term = make_term(concept, lifecycle="proposed")
    resp = client.post(f"/term/{term.id}/link-upstream?uselang=en", data={"lexeme_id": "notalexeme"}, follow_redirects=True)
    assert b"valid Wikidata Lexeme ID" in resp.data
    db.session.refresh(term)
    assert term.lifecycle == "proposed"


def test_link_term_upstream_rejects_sense_not_matching_lexeme(client, db, seed_languages, logged_in):
    concept = make_concept()
    term = make_term(concept, lifecycle="proposed")
    resp = client.post(
        f"/term/{term.id}/link-upstream?uselang=en",
        data={"lexeme_id": "L1", "sense_id": "L2-S1"},
        follow_redirects=True,
    )
    assert b"must belong to the Lexeme ID" in resp.data
    db.session.refresh(term)
    assert term.lifecycle == "proposed"


@responses.activate
def test_link_term_upstream_rejects_nonexistent_entity(client, db, seed_languages, logged_in):
    mock_entity_missing("L999999")
    concept = make_concept()
    term = make_term(concept, lifecycle="proposed")
    resp = client.post(f"/term/{term.id}/link-upstream?uselang=en", data={"lexeme_id": "L999999"}, follow_redirects=True)
    assert b"exist on Wikidata" in resp.data
    db.session.refresh(term)
    assert term.lifecycle == "proposed"


@responses.activate
def test_link_term_upstream_success_without_sense(client, db, seed_languages, logged_in):
    mock_entity_found("L1")
    concept = make_concept()
    term = make_term(concept, lifecycle="proposed")
    resp = client.post(f"/term/{term.id}/link-upstream", data={"lexeme_id": "L1"})
    assert resp.status_code == 302
    db.session.refresh(term)
    assert term.lifecycle == "upstream"
    assert term.lexeme_id == "L1"
    assert term.sense_id is None
    assert term.upstream_ref == "L1"


@responses.activate
def test_link_term_upstream_success_with_sense(client, db, seed_languages, logged_in):
    mock_entity_found("L1")
    concept = make_concept()
    term = make_term(concept, lifecycle="proposed")
    resp = client.post(f"/term/{term.id}/link-upstream", data={"lexeme_id": "L1", "sense_id": "L1-S1"})
    assert resp.status_code == 302
    db.session.refresh(term)
    assert term.lifecycle == "upstream"
    assert term.lexeme_id == "L1"
    assert term.sense_id == "L1-S1"
    assert term.upstream_ref == "L1-S1"

    entry = AuditLog.query.filter_by(action="link_term_upstream").first()
    assert entry is not None
