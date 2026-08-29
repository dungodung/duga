"""Self-service suppression UI (SPEC.md S4). The operator CLIs are covered
by tests/test_suppress_topic.py and tests/test_suppress_vocabulary.py; this
covers the logged-in web path added alongside them."""
from datetime import datetime, timezone

from app.models import AuditLog, Concept, Gap, Term, Topic
from tests.test_vocabulary_routes import make_concept, make_term


def _topic(db, qid="Q1", suppressed=False):
    now = datetime.now(timezone.utc)
    db.session.add(
        Topic(qid=qid, entity_class="human", is_human=True, is_living=False,
              first_seen=now, last_seen=now, suppressed=suppressed)
    )
    db.session.add(
        Gap(topic_qid=qid, language_code="sr", project_code="wikipedia", gap_type="no_article",
            detector_key="wp_no_article", scope_version_id=1,
            evidence_json='{"label": "Marsha P. Johnson"}',
            action_url="https://www.wikidata.org/wiki/Q1", computed_at=now)
    )
    db.session.commit()


def _concept_and_term(db):
    concept = make_concept(local_label="pride")
    return concept, make_term(concept, written_form="понос")


def test_suppress_topic_requires_login(client, db, seed_languages):
    _topic(db)
    resp = client.post("/topic/Q1/suppress", data={"reason": "outing risk"})
    assert resp.status_code in (302, 401, 403)
    assert db.session.get(Topic, "Q1").suppressed is False


def test_suppress_topic_confirm_page_names_the_topic(client, db, seed_languages, logged_in):
    _topic(db)
    resp = client.get("/topic/Q1/suppress?lang=sr&uselang=en")
    assert resp.status_code == 200
    # The label comes from the gap's evidence, not from the URL.
    assert b"Marsha P. Johnson" in resp.data
    assert b"every language" in resp.data


def test_suppress_topic_hides_it_everywhere_and_logs_the_reason(client, db, seed_languages, logged_in):
    _topic(db)
    resp = client.post("/topic/Q1/suppress", data={"reason": "outing risk", "lang": "sr"})
    assert resp.status_code == 302

    topic = db.session.get(Topic, "Q1")
    assert topic.suppressed is True
    assert topic.suppressed_reason == "outing risk"
    assert topic.suppressed_by == logged_in.wiki_username
    assert topic.suppressed_at is not None

    entry = AuditLog.query.filter_by(action="suppress_topic", entity_id="Q1").one()
    assert entry.actor == logged_in.wiki_username
    assert "outing risk" in entry.after_json

    # S4: filtered at query time in every code path, not just the one it
    # was suppressed from. Asserted on the rows themselves -- the name
    # legitimately reappears once more, in the "now suppressed" flash the
    # next request consumes.
    body = client.get("/sr/gaps").data
    assert b'class="gap-row"' not in body


def test_suppress_topic_refuses_an_empty_reason(client, db, seed_languages, logged_in):
    _topic(db)
    resp = client.post("/topic/Q1/suppress", data={"reason": "   ", "lang": "sr"})
    assert resp.status_code == 302
    assert db.session.get(Topic, "Q1").suppressed is False


def test_suppress_topic_404s_for_an_already_suppressed_topic(client, db, seed_languages, logged_in):
    _topic(db, suppressed=True)
    assert client.get("/topic/Q1/suppress").status_code == 404
    assert client.post("/topic/Q1/suppress", data={"reason": "again"}).status_code == 404


def test_suppress_topic_ignores_an_unseeded_redirect_language(client, db, seed_languages, logged_in):
    """The redirect target is validated against seeded languages, so it
    can't be turned into an open redirect."""
    _topic(db)
    resp = client.post("/topic/Q1/suppress", data={"reason": "x", "lang": "https://evil.example"})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")


def test_suppress_term_hides_it_and_logs_the_reason(client, db, seed_languages, logged_in):
    _concept, term = _concept_and_term(db)
    resp = client.post(f"/term/{term.id}/suppress", data={"reason": "slur, not in use"})
    assert resp.status_code == 302

    assert db.session.get(Term, term.id).suppressed is True
    entry = AuditLog.query.filter_by(action="suppress_term", entity_id=str(term.id)).one()
    assert "slur, not in use" in entry.after_json
    assert f"/sr/vocabulary/{term.id}".encode() not in client.get("/sr/vocabulary").data
    assert client.get(f"/sr/vocabulary/{term.id}").status_code == 404


def test_suppress_concept_also_hides_its_terms(client, db, seed_languages, logged_in):
    concept, term = _concept_and_term(db)
    resp = client.post(f"/concept/{concept.id}/suppress", data={"reason": "duplicate"})
    assert resp.status_code == 302

    assert db.session.get(Concept, concept.id).suppressed is True
    # The term row itself is untouched, but it's filtered out by the join.
    assert db.session.get(Term, term.id).suppressed is False
    assert f"/sr/vocabulary/{term.id}".encode() not in client.get("/sr/vocabulary").data
    assert client.get(f"/concept/{concept.id}").status_code == 404


def test_suppress_term_requires_a_reason(client, db, seed_languages, logged_in):
    _concept, term = _concept_and_term(db)
    resp = client.post(f"/term/{term.id}/suppress", data={"reason": ""})
    assert resp.status_code == 302
    assert db.session.get(Term, term.id).suppressed is False


def test_suppress_links_are_hidden_from_logged_out_visitors(client, db, seed_languages):
    _topic(db)
    assert b"/topic/Q1/suppress" not in client.get("/sr/gaps").data


def test_suppress_link_is_shown_to_a_logged_in_contributor(client, db, seed_languages, logged_in):
    _topic(db)
    assert b"/topic/Q1/suppress" in client.get("/sr/gaps").data
