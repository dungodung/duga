import json
from datetime import datetime, timezone

import responses

from app.extensions import db
from app.models import AuditLog, Concept, Term, WikiEdit

API_URL = "https://www.wikidata.org/w/api.php"


def make_concept(qid="Q1", local_label="Some Concept"):
    concept = Concept(
        local_label=local_label,
        lifecycle="upstream",
        qid=qid,
        created_by="SomeoneElse",
        created_at=datetime.now(timezone.utc),
    )
    db.session.add(concept)
    db.session.commit()
    return concept


def make_term(concept, lexeme_id="L1", sense_id=None, lifecycle="upstream", lang="sr", written_form="реч", usage_note=None):
    now = datetime.now(timezone.utc)
    term = Term(
        concept_id=concept.id,
        language_code=lang,
        written_form=written_form,
        register="neutral",
        evidence_grade="single_report",
        lifecycle=lifecycle,
        lexeme_id=lexeme_id,
        sense_id=sense_id,
        upstream_ref=sense_id or lexeme_id,
        usage_note=usage_note,
        created_by="SomeoneElse",
        created_at=now,
        updated_at=now,
    )
    db.session.add(term)
    db.session.commit()
    return term


def mock_add_sense(sense_id="L1-S1", revid=42):
    responses.add(
        responses.GET,
        API_URL,
        json={"query": {"tokens": {"csrftoken": "abc+\\"}}},
        status=200,
    )
    responses.add(
        responses.POST,
        API_URL,
        json={"sense": {"id": sense_id}, "lastrevid": revid},
        status=200,
    )


# -- GET /term/<id>/add-sense ------------------------------------------------


def test_add_sense_form_requires_login(client, db, seed_languages):
    concept = make_concept()
    term = make_term(concept)
    resp = client.get(f"/term/{term.id}/add-sense")
    assert resp.status_code == 302
    assert "/login" in resp.location


def test_add_sense_form_renders_for_eligible_term(client, db, seed_languages, logged_in):
    concept = make_concept()
    term = make_term(concept, written_form="дугиница")
    resp = client.get(f"/term/{term.id}/add-sense?uselang=en")
    assert resp.status_code == 200
    assert b"\xd0\xb4\xd1\x83\xd0\xb3\xd0\xb8\xd0\xbd\xd0\xb8\xd1\x86\xd0\xb0" in resp.data  # "дугиница"


def test_add_sense_form_prefills_gloss_from_usage_note(client, db, seed_languages, logged_in):
    concept = make_concept()
    term = make_term(concept, usage_note="a friendly informal term")
    resp = client.get(f"/term/{term.id}/add-sense?uselang=en")
    assert b"a friendly informal term" in resp.data


def test_add_sense_form_404s_when_lifecycle_is_not_upstream(client, db, seed_languages, logged_in):
    concept = make_concept()
    term = make_term(concept, lifecycle="proposed")
    resp = client.get(f"/term/{term.id}/add-sense")
    assert resp.status_code == 404


def test_add_sense_form_404s_when_no_lexeme_id(client, db, seed_languages, logged_in):
    concept = make_concept()
    term = make_term(concept, lexeme_id=None)
    resp = client.get(f"/term/{term.id}/add-sense")
    assert resp.status_code == 404


def test_add_sense_form_404s_when_sense_already_set(client, db, seed_languages, logged_in):
    concept = make_concept()
    term = make_term(concept, sense_id="L1-S1")
    resp = client.get(f"/term/{term.id}/add-sense")
    assert resp.status_code == 404


# -- POST /term/<id>/add-sense: preview step (no write yet) -----------------


def test_submit_without_confirmed_shows_preview_and_writes_nothing(client, db, seed_languages, logged_in_with_token):
    concept = make_concept()
    term = make_term(concept)
    resp = client.post(f"/term/{term.id}/add-sense?uselang=en", data={"gloss": "нека дефиниција"})
    assert resp.status_code == 200
    assert "нека дефиниција".encode() in resp.data
    assert WikiEdit.query.count() == 0
    assert db.session.get(Term, term.id).sense_id is None


def test_submit_without_gloss_flashes_error_and_redirects(client, db, seed_languages, logged_in_with_token):
    concept = make_concept()
    term = make_term(concept)
    resp = client.post(f"/term/{term.id}/add-sense?uselang=en", data={"gloss": ""}, follow_redirects=True)
    assert b"Please enter a value" in resp.data
    assert WikiEdit.query.count() == 0


# -- POST /term/<id>/add-sense: confirmed step (real write) -----------------


@responses.activate
def test_confirmed_submit_writes_and_updates_term(client, db, seed_languages, logged_in_with_token):
    mock_add_sense(sense_id="L1-S1", revid=777)
    concept = make_concept()
    term = make_term(concept)

    resp = client.post(f"/term/{term.id}/add-sense", data={"gloss": "нека дефиниција", "confirmed": "1"})
    assert resp.status_code == 302

    updated = db.session.get(Term, term.id)
    assert updated.sense_id == "L1-S1"
    assert updated.upstream_ref == "L1-S1"

    wiki_edit = WikiEdit.query.first()
    assert wiki_edit.status == "success"
    assert wiki_edit.revid == 777
    assert wiki_edit.edit_kind == "sense"
    assert wiki_edit.target_entity == "L1"
    assert "Duga" in wiki_edit.summary


@responses.activate
def test_confirmed_submit_writes_audit_log_entries(client, db, seed_languages, logged_in_with_token):
    mock_add_sense(sense_id="L1-S1", revid=555)
    concept = make_concept()
    term = make_term(concept)
    client.post(f"/term/{term.id}/add-sense", data={"gloss": "нека дефиниција", "confirmed": "1"})

    actions = {entry.action for entry in AuditLog.query.all()}
    assert "wiki_edit_attempt" in actions
    assert "wiki_edit_success" in actions
    assert "link_term_sense" in actions

    sense_entry = AuditLog.query.filter_by(action="link_term_sense").first()
    assert json.loads(sense_entry.after_json)["sense_id"] == "L1-S1"


def test_confirmed_submit_blocked_by_kill_switch(client, app, db, seed_languages, logged_in_with_token):
    app.config["DUGA_WRITES_ENABLED"] = False
    concept = make_concept()
    term = make_term(concept)
    resp = client.post(f"/term/{term.id}/add-sense?uselang=en", data={"gloss": "x", "confirmed": "1"}, follow_redirects=True)
    assert b"temporarily disabled" in resp.data
    assert WikiEdit.query.count() == 0
    assert db.session.get(Term, term.id).sense_id is None


def test_confirmed_submit_blocked_by_per_user_rate_limit(client, app, db, seed_languages, logged_in_with_token):
    app.config["DUGA_MAX_WRITES_PER_HOUR_PER_USER"] = 1
    now = datetime.now(timezone.utc)
    db.session.add(
        WikiEdit(
            contributor="TestContributor", target_wiki="wikidata", target_entity="L999", edit_kind="sense",
            summary="prior edit", status="success", created_at=now,
        )
    )
    db.session.commit()

    concept = make_concept()
    term = make_term(concept)
    resp = client.post(f"/term/{term.id}/add-sense?uselang=en", data={"gloss": "x", "confirmed": "1"}, follow_redirects=True)
    assert b"Too many edits" in resp.data
    assert db.session.get(Term, term.id).sense_id is None


@responses.activate
def test_confirmed_submit_records_failure_without_updating_term(client, db, seed_languages, logged_in_with_token):
    responses.add(
        responses.GET, API_URL, json={"query": {"tokens": {"csrftoken": "abc"}}}, status=200,
    )
    responses.add(responses.POST, API_URL, json={"error": {"code": "permissiondenied", "info": "blocked"}}, status=200)

    concept = make_concept()
    term = make_term(concept)
    resp = client.post(f"/term/{term.id}/add-sense?uselang=en", data={"gloss": "x", "confirmed": "1"}, follow_redirects=True)
    assert b"edit failed" in resp.data

    assert db.session.get(Term, term.id).sense_id is None
    wiki_edit = WikiEdit.query.first()
    assert wiki_edit.status == "failed"
    assert "blocked" in wiki_edit.error


def test_confirmed_submit_without_stored_token_prompts_relogin(client, db, seed_languages, logged_in):
    concept = make_concept()
    term = make_term(concept)
    resp = client.post(f"/term/{term.id}/add-sense", data={"gloss": "x", "confirmed": "1"})
    assert resp.status_code == 302
    assert "/login" in resp.location
    assert WikiEdit.query.count() == 0


# -- term_detail.html trigger -------------------------------------------


def test_term_detail_shows_add_sense_link_when_eligible(client, db, seed_languages, logged_in):
    concept = make_concept()
    term = make_term(concept)
    resp = client.get(f"/sr/vocabulary/{term.id}?uselang=en")
    assert f"/term/{term.id}/add-sense".encode() in resp.data


def test_term_detail_hides_add_sense_link_when_sense_already_set(client, db, seed_languages, logged_in):
    concept = make_concept()
    term = make_term(concept, sense_id="L1-S1")
    resp = client.get(f"/sr/vocabulary/{term.id}?uselang=en")
    assert f"/term/{term.id}/add-sense".encode() not in resp.data
