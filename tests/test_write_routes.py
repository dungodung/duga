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


# -- GET /gap/<id>/edit: one step, Publish --------------------------------


def test_edit_form_publishes_in_one_step_and_says_so(client, db, seed_languages, logged_in_with_token):
    """No preview: Publish beside a note saying the edit goes out at once,
    from the person's own account, is the per-edit confirmation."""
    gap = make_gap()
    body = client.get(f"/gap/{gap.id}/edit?uselang=en").data.decode()
    assert 'class="button">Publish</button>' in body
    assert "from your account" in body
    assert "Preview" not in body


def test_submit_without_value_flashes_error_and_redirects(client, db, seed_languages, logged_in_with_token):
    gap = make_gap()
    resp = client.post(f"/gap/{gap.id}/edit?uselang=en", data={"value": ""}, follow_redirects=True)
    assert b"Please enter a value" in resp.data
    assert WikiEdit.query.count() == 0


# -- POST /gap/<id>/edit: Publish (real write) -----------------------------


@responses.activate
def test_publish_writes_and_removes_gap(client, db, seed_languages, logged_in_with_token):
    mock_wikidata_write(revid=777)
    gap = make_gap(gap_type="no_label")
    gap_id = gap.id

    resp = client.post(f"/gap/{gap_id}/edit", data={"value": "нова ознака"})
    assert resp.status_code == 302

    assert Gap.query.filter_by(id=gap_id).count() == 0

    wiki_edit = WikiEdit.query.first()
    assert wiki_edit.status == "success"
    assert wiki_edit.revid == 777
    assert wiki_edit.edit_kind == "label"
    assert wiki_edit.target_entity == "Q1"
    assert "Duga" in wiki_edit.summary


@responses.activate
def test_publish_for_description_gap_calls_set_description(client, db, seed_languages, logged_in_with_token):
    mock_wikidata_write()
    gap = make_gap(gap_type="no_description")
    resp = client.post(f"/gap/{gap.id}/edit", data={"value": "опис"})
    assert resp.status_code == 302

    wiki_edit = WikiEdit.query.first()
    assert wiki_edit.edit_kind == "description"


@responses.activate
def test_publish_writes_audit_log_entries(client, db, seed_languages, logged_in_with_token):
    mock_wikidata_write(revid=555)
    gap = make_gap()
    client.post(f"/gap/{gap.id}/edit", data={"value": "нова ознака"})

    actions = {entry.action for entry in AuditLog.query.all()}
    assert "wiki_edit_attempt" in actions
    assert "wiki_edit_success" in actions

    success_entry = AuditLog.query.filter_by(action="wiki_edit_success").first()
    assert json.loads(success_entry.after_json)["revid"] == 555


def test_publish_blocked_by_kill_switch(client, app, db, seed_languages, logged_in_with_token):
    app.config["DUGA_WRITES_ENABLED"] = False
    gap = make_gap()
    resp = client.post(f"/gap/{gap.id}/edit?uselang=en", data={"value": "x"}, follow_redirects=True)
    assert b"temporarily disabled" in resp.data
    assert WikiEdit.query.count() == 0
    assert Gap.query.count() == 1


def test_publish_blocked_by_per_user_rate_limit(client, app, db, seed_languages, logged_in_with_token):
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
    resp = client.post(f"/gap/{gap.id}/edit?uselang=en", data={"value": "x"}, follow_redirects=True)
    assert b"Too many edits" in resp.data
    assert Gap.query.count() == 1


@responses.activate
def test_publish_records_failure_without_removing_gap(client, db, seed_languages, logged_in_with_token):
    responses.add(
        responses.GET, API_URL, json={"query": {"tokens": {"csrftoken": "abc"}}}, status=200,
    )
    responses.add(responses.POST, API_URL, json={"error": {"code": "permissiondenied", "info": "blocked"}}, status=200)

    gap = make_gap()
    resp = client.post(f"/gap/{gap.id}/edit?uselang=en", data={"value": "x"}, follow_redirects=True)
    assert b"edit failed" in resp.data

    assert Gap.query.count() == 1  # not removed on failure
    wiki_edit = WikiEdit.query.first()
    assert wiki_edit.status == "failed"
    assert "blocked" in wiki_edit.error


def test_publish_without_stored_token_prompts_relogin(client, db, seed_languages, logged_in):
    """logged_in (not logged_in_with_token) has no ContributorToken row."""
    gap = make_gap()
    resp = client.post(f"/gap/{gap.id}/edit", data={"value": "x"})
    assert resp.status_code == 302
    assert "/login" in resp.location
    assert WikiEdit.query.count() == 0


# -- what Wikidata already says, on the edit form -----------------------------
#
# Someone writing a Serbian description is translating from another
# language's; without it they are guessing which "Mercury" the item is.
# English, recorded by the detector, unless the contributor chose other
# languages on their account page, which are looked up live. The
# `wikidata_terms_offline` fixture stands in for that lookup.


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
    assert "Already on Wikidata" in body
    assert "<dt>English</dt>" in body
    assert "Mercury" in body
    assert "chemical element with symbol Hg" in body


def test_edit_form_shows_the_label_even_when_it_repeats_the_heading(client, db, seed_languages, logged_in_with_token, wikidata_terms_offline):
    """Every chosen language shows its label and its description, so the
    rows line up and none looks as if its label were missing."""
    _choose(logged_in_with_token, "en", "de")
    wikidata_terms_offline.terms = {
        "en": {"label": "Mercury", "description": "chemical element"},
        "de": {"label": "Quecksilber", "description": "chemisches Element"},
    }
    gap = _wikidata_gap(db, gap_type="no_label", evidence={"label": "Mercury", "label_lang": "en"})

    body = client.get(f"/gap/{gap.id}/edit?uselang=en").data.decode()
    reference = body.split('class="wikidata-reference"')[1].split("</div>")[0]
    assert 'class="wikidata-reference-label">Mercury</span>' in reference
    assert "chemical element" in reference


def test_the_stored_english_fallback_keeps_the_label_too(client, db, seed_languages, logged_in_with_token):
    gap = _wikidata_gap(db, gap_type="no_label", evidence={
        "label": "Mercury", "label_lang": "en", "description_en": "chemical element",
    })

    body = client.get(f"/gap/{gap.id}/edit?uselang=en").data.decode()
    reference = body.split('class="wikidata-reference"')[1].split("</div>")[0]
    assert 'class="wikidata-reference-label">Mercury</span>' in reference
    assert "chemical element" in reference


def test_edit_form_omits_the_block_entirely_when_nothing_was_recorded(client, db, seed_languages, logged_in_with_token):
    """Gap rows written before the detectors recorded this -- show nothing
    rather than an empty box. Detectors rewrite nightly, so it fills in."""
    gap = _wikidata_gap(db, evidence={"label": "Живa", "label_lang": "sr"})

    body = client.get(f"/gap/{gap.id}/edit?uselang=en").data.decode()
    assert "wikidata-reference-heading" not in body


def test_the_english_text_is_marked_as_english(client, db, seed_languages, logged_in_with_token):
    """The page is being read in Serbian; the reference is not."""
    gap = _wikidata_gap(db, evidence={
        "label": "Живa", "label_lang": "sr", "label_en": "Mercury", "description_en": "chemical element",
    })

    body = client.get(f"/gap/{gap.id}/edit").data.decode()
    assert '<span lang="en" dir="auto" class="wikidata-reference-label">Mercury</span>' in body
    assert '<span lang="en" dir="auto">chemical element</span>' in body


def _choose(contributor, *codes):
    from app import reference_languages

    reference_languages.save(contributor, codes)
    db.session.commit()


def test_edit_form_shows_each_chosen_language_in_order(client, db, seed_languages, logged_in_with_token, wikidata_terms_offline):
    _choose(logged_in_with_token, "de", "en")
    wikidata_terms_offline.terms = {
        "de": {"label": "Quecksilber", "description": "chemisches Element"},
        "en": {"label": "mercury", "description": "chemical element with symbol Hg"},
    }
    gap = _wikidata_gap(db, evidence={"label": "Живa", "label_lang": "sr"})

    body = client.get(f"/gap/{gap.id}/edit?uselang=en").data.decode()
    assert wikidata_terms_offline.calls == [("Q1", ["de", "en"])]
    assert body.index("<dt>German</dt>") < body.index("<dt>English</dt>")
    assert '<span lang="de" dir="auto" class="wikidata-reference-label">Quecksilber</span>' in body
    assert "chemical element with symbol Hg" in body


def test_edit_form_never_asks_for_the_language_being_written(client, db, seed_languages, logged_in_with_token, wikidata_terms_offline):
    _choose(logged_in_with_token, "sr", "de")
    wikidata_terms_offline.terms = {"de": {"label": "Quecksilber", "description": None}}
    gap = _wikidata_gap(db)

    client.get(f"/gap/{gap.id}/edit?uselang=en")
    assert wikidata_terms_offline.calls == [("Q1", ["de"])]


def test_edit_form_says_which_of_label_and_description_is_missing(client, db, seed_languages, logged_in_with_token, wikidata_terms_offline):
    _choose(logged_in_with_token, "de", "hr", "zu")
    wikidata_terms_offline.terms = {
        "de": {"label": None, "description": None},
        "hr": {"label": "živa", "description": None},
        "zu": {"label": None, "description": "into"},
    }
    gap = _wikidata_gap(db)

    body = client.get(f"/gap/{gap.id}/edit?uselang=en").data.decode()
    reference = body.split('class="wikidata-reference"')[1].split("</div>")[0]
    rows = reference.split("<dt>")[1:]
    assert "no label" in rows[0] and "no description" in rows[0]
    assert "živa" in rows[1] and "no description" in rows[1] and "no label" not in rows[1]
    assert "no label" in rows[2] and "into" in rows[2] and "no description" not in rows[2]


def test_edit_form_falls_back_to_stored_english_when_wikidata_is_unreachable(client, db, seed_languages, logged_in_with_token, wikidata_terms_offline):
    """A slow Wikidata costs the page its extra languages, never the form."""
    _choose(logged_in_with_token, "de", "en")
    gap = _wikidata_gap(db, evidence={"label": "Живa", "label_lang": "sr", "description_en": "chemical element"})

    resp = client.get(f"/gap/{gap.id}/edit?uselang=en")
    body = resp.data.decode()
    assert resp.status_code == 200
    assert "chemical element" in body
    assert "<dt>German</dt>" not in body
    assert 'name="value"' in body


def test_edit_form_with_no_languages_chosen_shows_none_and_links_to_the_setting(client, db, seed_languages, logged_in_with_token, wikidata_terms_offline):
    _choose(logged_in_with_token)
    gap = _wikidata_gap(db, evidence={"label": "Живa", "label_lang": "sr", "description_en": "chemical element"})

    body = client.get(f"/gap/{gap.id}/edit?uselang=en").data.decode()
    assert wikidata_terms_offline.calls == []
    assert "chemical element" not in body
    assert 'href="/account#reference-languages"' in body



# -- coming back to the gap list as it was ------------------------------------


def test_edit_here_link_carries_the_lists_filters_and_page(client, db, seed_languages, logged_in_with_token):
    from urllib.parse import parse_qs, urlsplit

    gap = make_gap()
    body = client.get("/sr/gaps?project=wikidata&type=no_label&uselang=en").data.decode()
    href = body.split('class="button gap-primary" href="')[1].split('"')[0].replace("&amp;", "&")
    assert urlsplit(href).path == f"/gap/{gap.id}/edit"
    assert parse_qs(urlsplit(href).query)["next"] == ["/sr/gaps?project=wikidata&type=no_label&uselang=en"]


@responses.activate
def test_publish_returns_to_the_list_as_it_was(client, db, seed_languages, logged_in_with_token):
    mock_wikidata_write()
    gap = make_gap()
    back = "/sr/gaps?project=wikidata&type=no_label&page=3"

    form = client.get(f"/gap/{gap.id}/edit", query_string={"next": back}).data.decode()
    assert '<input type="hidden" name="next" value="/sr/gaps?project=wikidata&amp;type=no_label&amp;page=3">' in form
    assert '<a href="/sr/gaps?project=wikidata&amp;type=no_label&amp;page=3">Back to the gap list</a>' in form

    resp = client.post(f"/gap/{gap.id}/edit", data={"value": "нова ознака", "next": back})
    assert resp.status_code == 302
    assert resp.location == back


def test_a_failed_publish_also_returns_to_the_list_as_it_was(client, app, db, seed_languages, logged_in_with_token):
    app.config["DUGA_WRITES_ENABLED"] = False
    gap = make_gap()
    back = "/sr/gaps?page=2"
    resp = client.post(f"/gap/{gap.id}/edit", data={"value": "x", "next": back})
    assert resp.location == back


def test_an_empty_value_keeps_the_way_back(client, db, seed_languages, logged_in_with_token):
    gap = make_gap()
    resp = client.post(f"/gap/{gap.id}/edit", data={"value": "", "next": "/sr/gaps?page=2"})
    assert resp.location == f"/gap/{gap.id}/edit?next=/sr/gaps?page%3D2"


def test_publish_never_redirects_off_site(client, app, db, seed_languages, logged_in_with_token):
    app.config["DUGA_WRITES_ENABLED"] = False
    gap = make_gap()
    for evil in ("https://evil.example/", "//evil.example/", "/\\evil.example/"):
        resp = client.post(f"/gap/{gap.id}/edit", data={"value": "x", "next": evil})
        assert resp.location == "/sr/gaps", evil


# -- two in one: the other missing term, while you're here ---------------------


def _label_and_description_gaps():
    return make_gap(gap_type="no_label"), make_gap(gap_type="no_description")


def test_edit_form_offers_the_description_when_it_is_missing_too(client, db, seed_languages, logged_in_with_token):
    label_gap, _ = _label_and_description_gaps()
    body = client.get(f"/gap/{label_gap.id}/edit?uselang=en").data.decode()
    assert "add a description too?" in body
    assert 'name="also_value"' in body
    assert "one for each field you fill in" in body


def test_edit_form_offers_the_label_from_the_description_side_too(client, db, seed_languages, logged_in_with_token):
    _, description_gap = _label_and_description_gaps()
    body = client.get(f"/gap/{description_gap.id}/edit?uselang=en").data.decode()
    assert "add a label too?" in body


def test_edit_form_offers_nothing_extra_when_only_one_is_missing(client, db, seed_languages, logged_in_with_token):
    gap = make_gap(gap_type="no_label")
    body = client.get(f"/gap/{gap.id}/edit?uselang=en").data.decode()
    assert 'name="also_value"' not in body
    assert "one for each field you fill in" not in body


def test_a_hidden_companion_is_not_offered(client, db, seed_languages, logged_in_with_token):
    label_gap, _ = _label_and_description_gaps()
    db.session.add(GapOverride(
        topic_qid="Q1", language_code="sr", project_code="wikidata", gap_type="no_description",
        status="declined", set_by="someone", set_at=datetime.now(timezone.utc),
    ))
    db.session.commit()
    body = client.get(f"/gap/{label_gap.id}/edit?uselang=en").data.decode()
    assert 'name="also_value"' not in body


@responses.activate
def test_publishing_both_makes_two_edits_and_closes_both_gaps(client, db, seed_languages, logged_in_with_token):
    mock_wikidata_write()
    label_gap, _ = _label_and_description_gaps()

    resp = client.post(f"/gap/{label_gap.id}/edit?uselang=en", data={"value": "ознака", "also_value": "опис"}, follow_redirects=True)
    assert "Both saved to Wikidata" in resp.data.decode()
    assert Gap.query.count() == 0
    edits = WikiEdit.query.order_by(WikiEdit.id).all()
    assert [(e.edit_kind, e.status) for e in edits] == [("label", "success"), ("description", "success")]
    posted = [c.request.body for c in responses.calls if c.request.method == "POST"]
    assert "wbsetlabel" in posted[0] and "wbsetdescription" in posted[1]


@responses.activate
def test_leaving_the_second_field_empty_makes_one_edit(client, db, seed_languages, logged_in_with_token):
    mock_wikidata_write()
    label_gap, description_gap = _label_and_description_gaps()

    client.post(f"/gap/{label_gap.id}/edit", data={"value": "ознака", "also_value": "  "})
    assert WikiEdit.query.count() == 1
    assert [g.id for g in Gap.query.all()] == [description_gap.id]


@responses.activate
def test_when_the_second_edit_fails_the_first_still_counts(client, db, seed_languages, logged_in_with_token):
    responses.add(responses.GET, API_URL, json={"query": {"tokens": {"csrftoken": "abc"}}}, status=200)
    responses.add(responses.POST, API_URL, json={"entity": {"lastrevid": 1}}, status=200)
    responses.add(responses.POST, API_URL, json={"error": {"code": "permissiondenied", "info": "blocked"}}, status=200)
    label_gap, description_gap = _label_and_description_gaps()

    resp = client.post(f"/gap/{label_gap.id}/edit?uselang=en", data={"value": "ознака", "also_value": "опис"}, follow_redirects=True)
    body = resp.data.decode()
    assert "The first edit was saved to Wikidata, but the second wasn" in body
    assert "blocked" in body
    assert [g.id for g in Gap.query.all()] == [description_gap.id]


@responses.activate
def test_the_second_edit_respects_the_rate_limit_on_its_own(client, app, db, seed_languages, logged_in_with_token):
    """The first edit may use up the last of the hour's allowance."""
    mock_wikidata_write()
    app.config["DUGA_MAX_WRITES_PER_HOUR_PER_USER"] = 1
    label_gap, description_gap = _label_and_description_gaps()

    resp = client.post(f"/gap/{label_gap.id}/edit?uselang=en", data={"value": "ознака", "also_value": "опис"}, follow_redirects=True)
    assert "Too many edits recently" in resp.data.decode()
    assert WikiEdit.query.count() == 1
    assert [g.id for g in Gap.query.all()] == [description_gap.id]


@responses.activate
def test_a_published_label_reaches_the_items_other_gaps_at_once(client, db, seed_languages, logged_in_with_token):
    """So a missing Wikipedia article offers "Fix on Wikipedia" straight
    after the label is added, not after tonight's detector run."""
    mock_wikidata_write()
    label_gap = make_gap(gap_type="no_label", label="Mary Daly")
    article = make_gap(gap_type="no_article", project_code="wikipedia", label="Mary Daly")
    article.evidence_json = json.dumps({"label": "Mary Daly", "label_lang": "en"})
    other_language = make_gap(gap_type="no_article", project_code="wikipedia", label="Mary Daly", lang="fr")
    db.session.commit()

    client.post(f"/gap/{label_gap.id}/edit", data={"value": "Мери Дејли"})

    evidence = json.loads(db.session.get(Gap, article.id).evidence_json)
    assert evidence == {"label": "Мери Дејли", "label_lang": "sr", "label_en": "Mary Daly"}
    assert json.loads(db.session.get(Gap, other_language.id).evidence_json)["label"] == "Mary Daly"
    body = client.get("/sr/gaps?uselang=en").data.decode()
    assert "Fix on Wikipedia" in body
