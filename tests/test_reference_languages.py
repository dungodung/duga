"""The languages a contributor translates from: chosen on /account, shown
on the label/description edit form (tests/test_write_routes.py covers the
form)."""
import json

from app import reference_languages


def _stored(contributor):
    return json.loads(contributor.languages_json)["reference"]


# -- resolving what was typed or picked ------------------------------------


def test_a_picked_option_resolves_by_its_trailing_code():
    assert reference_languages.resolve(reference_languages.option_text("sr", "en"), "en") == "sr"


def test_a_bare_code_or_a_full_name_resolves_ignoring_case():
    assert reference_languages.resolve("DE", "en") == "de"
    assert reference_languages.resolve("german", "en") == "de"
    # The interface language's name, English's, or the autonym all work.
    assert reference_languages.resolve("немачки", "sr") == "de"
    assert reference_languages.resolve("Deutsch", "sr") == "de"


def test_nothing_resolves_from_nonsense_or_blank():
    assert reference_languages.resolve("Klingonish", "en") is None
    assert reference_languages.resolve("   ", "en") is None


def test_options_cover_every_wikidata_term_language_sorted_by_name():
    options = reference_languages.options("en")
    assert len(options) > 500
    assert "German — Deutsch (de)" in options
    # English needs no autonym beside it.
    assert "English (en)" in options
    assert options.index("English (en)") < options.index("German — Deutsch (de)") < options.index("Serbian — српски / srpski (sr)")


def test_a_contributor_who_never_chose_gets_english(logged_in):
    assert reference_languages.chosen(logged_in) == ["en"]


# -- /account --------------------------------------------------------------


def test_account_page_lists_the_languages_and_a_searchable_field(client, logged_in):
    body = client.get("/account?uselang=en").data.decode()
    assert 'id="reference-languages"' in body
    assert "Remove English" in body
    assert 'list="reference-language-options"' in body
    assert '<option value="German — Deutsch (de)">' in body


def test_adding_a_language_appends_it(client, db, logged_in):
    resp = client.post("/account/reference-languages/add", data={"language": "German — Deutsch (de)"})
    assert resp.status_code == 302
    assert resp.location.endswith("/account#reference-languages")
    assert _stored(logged_in) == ["en", "de"]


def test_adding_a_language_twice_keeps_one(client, db, logged_in):
    client.post("/account/reference-languages/add", data={"language": "de"})
    client.post("/account/reference-languages/add", data={"language": "German"})
    assert _stored(logged_in) == ["en", "de"]


def test_an_unknown_language_is_refused_with_a_message(client, db, logged_in):
    resp = client.post("/account/reference-languages/add?uselang=en", data={"language": "Klingonish"}, follow_redirects=True)
    assert "no language called “Klingonish”" in resp.data.decode()
    assert logged_in.languages_json is None


def test_no_more_than_five_languages(client, db, logged_in):
    for code in ("de", "fr", "es", "it", "nl"):
        client.post("/account/reference-languages/add", data={"language": code})
    assert _stored(logged_in) == ["en", "de", "fr", "es", "it"]

    body = client.get("/account?uselang=en").data.decode()
    assert "as many as you can choose" in body
    assert 'list="reference-language-options"' not in body


def test_removing_a_language_and_then_all_of_them(client, db, logged_in):
    client.post("/account/reference-languages/add", data={"language": "de"})
    client.post("/account/reference-languages/remove", data={"code": "en"})
    assert _stored(logged_in) == ["de"]

    client.post("/account/reference-languages/remove", data={"code": "de"})
    assert _stored(logged_in) == []
    # Removing every language is a choice, not a reset to English.
    assert reference_languages.chosen(logged_in) == []
    assert "None chosen" in client.get("/account?uselang=en").data.decode()


def test_choosing_languages_needs_a_login(client):
    resp = client.post("/account/reference-languages/add", data={"language": "de"})
    assert resp.status_code == 302
    assert "/login" in resp.location


def test_the_choice_keeps_whatever_else_languages_json_holds(db, logged_in):
    logged_in.languages_json = json.dumps({"other": 1})
    reference_languages.save(logged_in, ["de"])
    assert json.loads(logged_in.languages_json) == {"other": 1, "reference": ["de"]}
