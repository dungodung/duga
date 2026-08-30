import json
from datetime import datetime, timezone

import responses

from app.extensions import db
from app.models import AuditLog, Gap, GapOverride, Topic, WikiEdit

API_URL = "https://www.wikidata.org/w/api.php"


def make_gap(gap_type="no_label", project_code="wikidata", topic_qid="Q1", label="Some Topic", lang="sr"):
    now = datetime.now(timezone.utc)
    gap = Gap(
        topic_qid=topic_qid,
        language_code=lang,
        project_code=project_code,
        gap_type=gap_type,
        detector_key=f"wd_{gap_type}",
        scope_version_id=1,
        evidence_json=json.dumps({"label": label}),
        action_url=f"https://www.wikidata.org/wiki/{topic_qid}#labels",
        computed_at=now,
    )
    db.session.add(gap)
    db.session.commit()
    return gap


def mock_wikidata_write(revid=42):
    responses.add(
        responses.GET,
        API_URL,
        json={"query": {"tokens": {"csrftoken": "abc+\\"}}},
        status=200,
    )
    responses.add(responses.POST, API_URL, json={"entity": {"lastrevid": revid}}, status=200)


# -- GET /gap/<id>/edit -------------------------------------------------


def test_edit_form_requires_login(client, db, seed_languages):
    gap = make_gap()
    resp = client.get(f"/gap/{gap.id}/edit")
    assert resp.status_code == 302
    assert "/login" in resp.location


def test_edit_form_renders_for_editable_gap(client, db, seed_languages, logged_in):
    gap = make_gap(label="Marsha P. Johnson")
    resp = client.get(f"/gap/{gap.id}/edit?uselang=en")
    assert resp.status_code == 200
    assert b"Marsha P. Johnson" in resp.data


def test_edit_form_404s_for_wp_no_article_gap(client, db, seed_languages, logged_in):
    gap = make_gap(gap_type="no_article", project_code="wikipedia")
    resp = client.get(f"/gap/{gap.id}/edit")
    assert resp.status_code == 404


def test_edit_form_404s_for_suppressed_topic(client, db, seed_languages, logged_in):
    now = datetime.now(timezone.utc)
    db.session.add(
        Topic(qid="Q1", entity_class="human", is_human=True, is_living=True, first_seen=now, last_seen=now, suppressed=True)
    )
    gap = make_gap()
    resp = client.get(f"/gap/{gap.id}/edit")
    assert resp.status_code == 404


def test_edit_form_404s_for_overridden_gap(client, db, seed_languages, logged_in):
    gap = make_gap()
    db.session.add(
        GapOverride(
            topic_qid=gap.topic_qid, language_code=gap.language_code, project_code=gap.project_code,
            gap_type=gap.gap_type, status="declined", set_by="someone", set_at=datetime.now(timezone.utc),
        )
    )
    db.session.commit()
    resp = client.get(f"/gap/{gap.id}/edit")
    assert resp.status_code == 404


# -- POST /gap/<id>/edit: preview step (no write yet) --------------------


def test_submit_without_confirmed_shows_preview_and_writes_nothing(client, db, seed_languages, logged_in_with_token):
    gap = make_gap()
    resp = client.post(f"/gap/{gap.id}/edit?uselang=en", data={"value": "нова ознака"})
    assert resp.status_code == 200
    assert "нова ознака".encode() in resp.data
    assert WikiEdit.query.count() == 0
    assert Gap.query.count() == 1  # untouched


def test_submit_without_value_flashes_error_and_redirects(client, db, seed_languages, logged_in_with_token):
    gap = make_gap()
    resp = client.post(f"/gap/{gap.id}/edit?uselang=en", data={"value": ""}, follow_redirects=True)
    assert b"Please enter a value" in resp.data
    assert WikiEdit.query.count() == 0


# -- POST /gap/<id>/edit: confirmed step (real write) ---------------------


@responses.activate
def test_confirmed_submit_writes_and_removes_gap(client, db, seed_languages, logged_in_with_token):
    mock_wikidata_write(revid=777)
    gap = make_gap(gap_type="no_label")
    gap_id = gap.id

    resp = client.post(f"/gap/{gap_id}/edit", data={"value": "нова ознака", "confirmed": "1"})
    assert resp.status_code == 302

    assert Gap.query.filter_by(id=gap_id).count() == 0

    wiki_edit = WikiEdit.query.first()
    assert wiki_edit.status == "success"
    assert wiki_edit.revid == 777
    assert wiki_edit.edit_kind == "label"
    assert wiki_edit.target_entity == "Q1"
    assert "Duga" in wiki_edit.summary


@responses.activate
def test_confirmed_submit_for_description_gap_calls_set_description(client, db, seed_languages, logged_in_with_token):
    mock_wikidata_write()
    gap = make_gap(gap_type="no_description")
    resp = client.post(f"/gap/{gap.id}/edit", data={"value": "опис", "confirmed": "1"})
    assert resp.status_code == 302

    wiki_edit = WikiEdit.query.first()
    assert wiki_edit.edit_kind == "description"


@responses.activate
def test_confirmed_submit_writes_audit_log_entries(client, db, seed_languages, logged_in_with_token):
    mock_wikidata_write(revid=555)
    gap = make_gap()
    client.post(f"/gap/{gap.id}/edit", data={"value": "нова ознака", "confirmed": "1"})

    actions = {entry.action for entry in AuditLog.query.all()}
    assert "wiki_edit_attempt" in actions
    assert "wiki_edit_success" in actions

    success_entry = AuditLog.query.filter_by(action="wiki_edit_success").first()
    assert json.loads(success_entry.after_json)["revid"] == 555


def test_confirmed_submit_blocked_by_kill_switch(client, app, db, seed_languages, logged_in_with_token):
    app.config["DUGA_WRITES_ENABLED"] = False
    gap = make_gap()
    resp = client.post(f"/gap/{gap.id}/edit?uselang=en", data={"value": "x", "confirmed": "1"}, follow_redirects=True)
    assert b"temporarily disabled" in resp.data
    assert WikiEdit.query.count() == 0
    assert Gap.query.count() == 1


def test_confirmed_submit_blocked_by_per_user_rate_limit(client, app, db, seed_languages, logged_in_with_token):
    app.config["DUGA_MAX_WRITES_PER_HOUR_PER_USER"] = 1
    now = datetime.now(timezone.utc)
    db.session.add(
        WikiEdit(
            contributor="TestContributor", target_wiki="wikidata", target_entity="Q999", edit_kind="label",
            summary="prior edit", status="success", created_at=now,
        )
    )
    db.session.commit()

    gap = make_gap()
    resp = client.post(f"/gap/{gap.id}/edit?uselang=en", data={"value": "x", "confirmed": "1"}, follow_redirects=True)
    assert b"Too many edits" in resp.data
    assert Gap.query.count() == 1


@responses.activate
def test_confirmed_submit_records_failure_without_removing_gap(client, db, seed_languages, logged_in_with_token):
    responses.add(
        responses.GET, API_URL, json={"query": {"tokens": {"csrftoken": "abc"}}}, status=200,
    )
    responses.add(responses.POST, API_URL, json={"error": {"code": "permissiondenied", "info": "blocked"}}, status=200)

    gap = make_gap()
    resp = client.post(f"/gap/{gap.id}/edit?uselang=en", data={"value": "x", "confirmed": "1"}, follow_redirects=True)
    assert b"edit failed" in resp.data

    assert Gap.query.count() == 1  # not removed on failure
    wiki_edit = WikiEdit.query.first()
    assert wiki_edit.status == "failed"
    assert "blocked" in wiki_edit.error


def test_confirmed_submit_without_stored_token_prompts_relogin(client, db, seed_languages, logged_in):
    """logged_in (not logged_in_with_token) has no ContributorToken row."""
    gap = make_gap()
    resp = client.post(f"/gap/{gap.id}/edit", data={"value": "x", "confirmed": "1"})
    assert resp.status_code == 302
    assert "/login" in resp.location
    assert WikiEdit.query.count() == 0


# -- the English reference on the edit form ----------------------------------
#
# Someone writing a Serbian description is translating from the English
# one; without it they are guessing which "Mercury" the item is. Both
# strings are recorded by the detector, so showing them costs no API call
# at render time.


def _wikidata_gap(db, gap_type="no_description", evidence=None):
    from datetime import datetime, timezone

    from app.models import Gap

    gap = Gap(
        topic_qid="Q1", language_code="sr", project_code="wikidata", gap_type=gap_type,
        detector_key=f"wd_{gap_type}", scope_version_id=1,
        evidence_json=json.dumps(evidence or {}),
        action_url="https://www.wikidata.org/wiki/Q1", computed_at=datetime.now(timezone.utc),
    )
    db.session.add(gap)
    db.session.commit()
    return gap


def test_edit_form_shows_the_english_label_and_description(client, db, seed_languages, logged_in_with_token):
    gap = _wikidata_gap(db, evidence={
        "label": "Живa", "label_lang": "sr",
        "label_en": "Mercury", "description_en": "chemical element with symbol Hg",
    })

    body = client.get(f"/gap/{gap.id}/edit?uselang=en").data.decode()
    assert "On Wikidata in English:" in body
    assert "Mercury" in body
    assert "chemical element with symbol Hg" in body


def test_edit_form_does_not_repeat_the_label_it_already_shows(client, db, seed_languages, logged_in_with_token):
    """For a missing *label* the heading is already the English one, so
    repeating it in the reference block adds nothing."""
    gap = _wikidata_gap(db, gap_type="no_label", evidence={
        "label": "Mercury", "label_lang": "en", "description_en": "chemical element",
    })

    body = client.get(f"/gap/{gap.id}/edit?uselang=en").data.decode()
    reference = body.split('class="english-reference"')[1].split("</div>")[0]
    assert "chemical element" in reference
    assert "Mercury" not in reference


def test_edit_form_omits_the_block_entirely_when_nothing_was_recorded(client, db, seed_languages, logged_in_with_token):
    """Gap rows written before the detectors recorded this -- show nothing
    rather than an empty box. Detectors rewrite nightly, so it fills in."""
    gap = _wikidata_gap(db, evidence={"label": "Живa", "label_lang": "sr"})

    body = client.get(f"/gap/{gap.id}/edit?uselang=en").data.decode()
    assert "english-reference" not in body


def test_the_english_reference_survives_to_the_confirm_step(client, db, seed_languages, logged_in_with_token):
    gap = _wikidata_gap(db, evidence={
        "label": "Живa", "label_lang": "sr", "label_en": "Mercury",
        "description_en": "chemical element with symbol Hg",
    })

    body = client.post(f"/gap/{gap.id}/edit", data={"value": "хемијски елемент"}).data.decode()
    assert "chemical element with symbol Hg" in body


def test_the_english_text_is_marked_as_english(client, db, seed_languages, logged_in_with_token):
    """The page is being read in Serbian; the reference is not."""
    gap = _wikidata_gap(db, evidence={
        "label": "Живa", "label_lang": "sr", "label_en": "Mercury", "description_en": "chemical element",
    })

    body = client.get(f"/gap/{gap.id}/edit").data.decode()
    assert '<span lang="en" class="english-reference-label">Mercury</span>' in body
    assert '<span lang="en">chemical element</span>' in body
