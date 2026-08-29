import json
from datetime import datetime, timezone

from app.extensions import db
from app.models import AuditLog, Concept, Term, TermAssertion, TermEvidence


def make_concept(local_label="genderqueer", suppressed=False, created_by="Someone"):
    concept = Concept(
        local_label=local_label, created_by=created_by, created_at=datetime.now(timezone.utc), suppressed=suppressed
    )
    db.session.add(concept)
    db.session.flush()
    return concept


def make_term(concept, lang="sr", written_form="реч", suppressed=False, created_by="Someone", register="unknown"):
    now = datetime.now(timezone.utc)
    term = Term(
        concept_id=concept.id,
        language_code=lang,
        written_form=written_form,
        register=register,
        evidence_grade="single_report",
        lifecycle="local",
        created_by=created_by,
        created_at=now,
        updated_at=now,
        suppressed=suppressed,
    )
    db.session.add(term)
    db.session.commit()
    return term


# -- GET /<lang>/vocabulary --------------------------------------------------


def test_list_terms_shows_existing_terms(client, db, seed_languages):
    concept = make_concept()
    make_term(concept)
    resp = client.get("/sr/vocabulary?uselang=en")
    assert resp.status_code == 200
    assert "реч".encode() in resp.data
    assert b"genderqueer" in resp.data


def test_list_terms_empty_state(client, seed_languages):
    resp = client.get("/sr/vocabulary?uselang=en")
    assert resp.status_code == 200
    assert b"No terms yet" in resp.data


def test_list_terms_shows_add_form_when_logged_in(client, seed_languages, logged_in):
    resp = client.get("/sr/vocabulary?uselang=en")
    assert b'name="written_form"' in resp.data


def test_list_terms_shows_login_prompt_when_logged_out(client, seed_languages):
    resp = client.get("/sr/vocabulary?uselang=en")
    assert b'name="written_form"' not in resp.data
    assert b"Log in to add a term" in resp.data


def test_list_terms_404s_for_unseeded_language(client, seed_languages):
    resp = client.get("/xx/vocabulary")
    assert resp.status_code == 404


def test_list_terms_excludes_suppressed_terms(client, db, seed_languages):
    concept = make_concept()
    make_term(concept, written_form="потиснуто", suppressed=True)
    resp = client.get("/sr/vocabulary?uselang=en")
    assert "потиснуто".encode() not in resp.data


def test_list_terms_excludes_terms_of_a_suppressed_concept(client, db, seed_languages):
    concept = make_concept(local_label="suppressed concept", suppressed=True)
    make_term(concept, written_form="скривено")
    resp = client.get("/sr/vocabulary?uselang=en")
    assert "скривено".encode() not in resp.data


# -- POST /<lang>/vocabulary/add ---------------------------------------------


def test_add_term_requires_login(client, seed_languages):
    resp = client.post("/sr/vocabulary/add", data={"concept_label": "x", "written_form": "y"})
    assert resp.status_code == 302
    assert "/login" in resp.location


def test_add_term_creates_new_concept_and_term(client, seed_languages, logged_in):
    resp = client.post(
        "/sr/vocabulary/add",
        data={"concept_label": "New Concept", "written_form": "нова реч", "register": "neutral"},
    )
    assert resp.status_code == 302

    term = Term.query.filter_by(written_form="нова реч").first()
    assert term is not None
    assert term.register == "neutral"
    assert term.created_by == "TestContributor"
    assert term.concept.local_label == "New Concept"


def test_add_term_reuses_existing_concept_case_insensitively(client, db, seed_languages, logged_in):
    existing = make_concept(local_label="Genderqueer")
    client.post(
        "/sr/vocabulary/add",
        data={"concept_label": "genderqueer", "written_form": "реч"},
    )
    term = Term.query.filter_by(written_form="реч").first()
    assert term.concept_id == existing.id
    assert Concept.query.count() == 1


def test_add_term_rejects_missing_fields(client, seed_languages, logged_in):
    resp = client.post(
        "/sr/vocabulary/add?uselang=en",
        data={"concept_label": "", "written_form": ""},
        follow_redirects=True,
    )
    assert b"Please fill in both" in resp.data
    assert Term.query.count() == 0


def test_add_term_rejects_duplicate(client, db, seed_languages, logged_in):
    concept = make_concept()
    existing = make_term(concept, written_form="постојећа")
    resp = client.post(
        "/sr/vocabulary/add?uselang=en",
        data={"concept_label": concept.local_label, "written_form": "постојећа"},
        follow_redirects=True,
    )
    assert b"already exists" in resp.data
    assert Term.query.count() == 1


def test_add_term_writes_audit_log(client, seed_languages, logged_in):
    client.post("/sr/vocabulary/add", data={"concept_label": "Audited", "written_form": "нова"})
    entry = AuditLog.query.filter_by(action="create_term").first()
    assert entry is not None
    assert entry.actor == "TestContributor"


# -- GET /<lang>/vocabulary/<id> ---------------------------------------------


def test_term_detail_renders(client, db, seed_languages):
    concept = make_concept()
    term = make_term(concept)
    resp = client.get(f"/sr/vocabulary/{term.id}?uselang=en")
    assert resp.status_code == 200
    assert "реч".encode() in resp.data


def test_term_detail_404s_for_suppressed_term(client, db, seed_languages):
    concept = make_concept()
    term = make_term(concept, suppressed=True)
    resp = client.get(f"/sr/vocabulary/{term.id}")
    assert resp.status_code == 404


def test_term_detail_404s_for_wrong_language(client, db, seed_languages):
    concept = make_concept()
    term = make_term(concept, lang="sr")
    resp = client.get(f"/fr/vocabulary/{term.id}")
    assert resp.status_code == 404


def test_term_detail_respects_attribution_opt_out(client, db, seed_languages):
    from app.models import Contributor

    db.session.add(
        Contributor(wiki_username="Private", display_public=False, created_at=datetime.now(timezone.utc))
    )
    db.session.commit()
    concept = make_concept()
    term = make_term(concept, created_by="Private")
    resp = client.get(f"/sr/vocabulary/{term.id}?uselang=en")
    assert b"Private" not in resp.data
    assert b"opted out" in resp.data


# -- POST /term/<id>/evidence -------------------------------------------------


def test_add_evidence_requires_login(client, db, seed_languages):
    concept = make_concept()
    term = make_term(concept)
    resp = client.post(f"/term/{term.id}/evidence", data={"kind": "law", "citation": "x"})
    assert resp.status_code == 302
    assert "/login" in resp.location


def test_add_evidence_upgrades_grade_and_audit_logs(client, db, seed_languages, logged_in):
    concept = make_concept()
    term = make_term(concept)
    resp = client.post(
        f"/term/{term.id}/evidence",
        data={"kind": "law", "citation": "Some law text", "url": "https://example.org", "year": "2020"},
    )
    assert resp.status_code == 302

    db.session.refresh(term)
    assert term.evidence_grade == "documented"
    assert TermEvidence.query.filter_by(term_id=term.id).count() == 1

    entry = AuditLog.query.filter_by(action="add_term_evidence").first()
    assert entry is not None
    assert json.loads(entry.after_json)["evidence_grade"] == "documented"


def test_add_evidence_rejects_invalid_kind(client, db, seed_languages, logged_in):
    concept = make_concept()
    term = make_term(concept)
    client.post(f"/term/{term.id}/evidence", data={"kind": "not-a-real-kind", "citation": "x"})
    assert TermEvidence.query.count() == 0


def test_add_evidence_404s_for_suppressed_term(client, db, seed_languages, logged_in):
    concept = make_concept()
    term = make_term(concept, suppressed=True)
    resp = client.post(f"/term/{term.id}/evidence", data={"kind": "law", "citation": "x"})
    assert resp.status_code == 404


# -- POST /term/<id>/assert ---------------------------------------------------


def test_assert_term_requires_login(client, db, seed_languages):
    concept = make_concept()
    term = make_term(concept)
    resp = client.post(f"/term/{term.id}/assert", data={"agrees": "agree"})
    assert resp.status_code == 302
    assert "/login" in resp.location


def test_assert_term_creates_assertion_and_recomputes_grade(client, db, seed_languages, logged_in):
    concept = make_concept()
    term = make_term(concept)
    # Push over the default threshold of 3 with two other contributors first.
    db.session.add(TermAssertion(term_id=term.id, contributor="A", agrees=True, created_at=datetime.now(timezone.utc)))
    db.session.add(TermAssertion(term_id=term.id, contributor="B", agrees=True, created_at=datetime.now(timezone.utc)))
    db.session.commit()

    resp = client.post(f"/term/{term.id}/assert", data={"agrees": "agree"})
    assert resp.status_code == 302

    db.session.refresh(term)
    assert term.evidence_grade == "community"
    assert TermAssertion.query.filter_by(term_id=term.id, contributor="TestContributor").count() == 1


def test_assert_term_upserts_rather_than_duplicating(client, db, seed_languages, logged_in):
    concept = make_concept()
    term = make_term(concept)
    client.post(f"/term/{term.id}/assert", data={"agrees": "agree"})
    client.post(f"/term/{term.id}/assert", data={"agrees": "disagree", "note": "changed my mind"})

    assertions = TermAssertion.query.filter_by(term_id=term.id, contributor="TestContributor").all()
    assert len(assertions) == 1
    assert assertions[0].agrees is False
    assert assertions[0].note == "changed my mind"


# -- GET /concept/<id> ---------------------------------------------------


def test_concept_detail_lists_terms_across_languages(client, db, seed_languages):
    concept = make_concept()
    make_term(concept, lang="sr", written_form="реч")
    make_term(concept, lang="fr", written_form="mot")
    resp = client.get(f"/concept/{concept.id}?uselang=en")
    assert resp.status_code == 200
    assert "реч".encode() in resp.data
    assert b"mot" in resp.data


def test_concept_detail_404s_for_suppressed_concept(client, db, seed_languages):
    concept = make_concept(suppressed=True)
    resp = client.get(f"/concept/{concept.id}")
    assert resp.status_code == 404


def test_concept_detail_excludes_suppressed_terms(client, db, seed_languages):
    concept = make_concept()
    make_term(concept, lang="sr", written_form="видљиво")
    make_term(concept, lang="fr", written_form="caché", suppressed=True)
    resp = client.get(f"/concept/{concept.id}?uselang=en")
    assert "видљиво".encode() in resp.data
    assert b"cach\xc3\xa9" not in resp.data


def test_add_term_form_prefills_the_concept_from_the_gap_list_link(client, db, seed_languages, logged_in):
    """The gap list's "add a word for this" link carries the topic name
    through, so nobody retypes it -- SPEC.md section 12 puts a 60-second
    phone budget on this flow."""
    resp = client.get("/sr/vocabulary?concept=genderqueer&uselang=en")
    assert resp.status_code == 200
    assert b'id="concept_label"' in resp.data
    assert b'value="genderqueer"' in resp.data


def test_add_term_form_is_empty_without_the_prefill(client, db, seed_languages, logged_in):
    resp = client.get("/sr/vocabulary?uselang=en")
    assert b'value=""' in resp.data or b'name="concept_label" list="concept-suggestions" value=""' in resp.data


def test_prefill_is_display_only_and_does_not_create_anything(client, db, seed_languages, logged_in):
    """Visiting the prefilled URL must not create a concept -- only the
    POST does."""
    client.get("/sr/vocabulary?concept=genderqueer")
    assert Concept.query.count() == 0


def test_term_written_form_is_marked_with_its_own_language(client, db, seed_languages):
    """Interface and content language are independent (SPEC.md section 13),
    so a screen reader needs to be told which language the word is in."""
    concept = make_concept()
    term = make_term(concept, lang="sr", written_form="родно квир")

    body = client.get("/sr/vocabulary?uselang=en").data.decode()
    assert f'lang="sr">родно квир</a>' in body

    detail = client.get(f"/sr/vocabulary/{term.id}?uselang=en").data.decode()
    assert '<h1 lang="sr">родно квир</h1>' in detail
