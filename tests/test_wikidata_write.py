import json

import pytest
import responses

from app.wikidata_write import (
    ALLOWED_EDIT_KINDS,
    EDITABLE_GAP_TYPES,
    WikidataWriteError,
    add_sense,
    edit_summary,
    set_description,
    set_label,
)

API_URL = "https://www.wikidata.org/w/api.php"


def mock_csrf_and_write(write_response, action):
    responses.add(
        responses.GET,
        API_URL,
        json={"query": {"tokens": {"csrftoken": "abc123+\\"}}},
        status=200,
    )
    responses.add(responses.POST, API_URL, json=write_response, status=200)


def test_allowed_edit_kinds_is_exactly_label_description_and_sense():
    assert ALLOWED_EDIT_KINDS == {"label", "description", "sense"}


def test_editable_gap_types_maps_to_allowed_kinds():
    assert set(EDITABLE_GAP_TYPES.values()) <= ALLOWED_EDIT_KINDS


def test_edit_summary_names_duga_and_links_to_it():
    summary = edit_summary("label")
    assert "Duga" in summary
    assert "duga.toolforge.org" in summary


def test_edit_summary_rejects_unknown_kind():
    with pytest.raises(WikidataWriteError):
        edit_summary("claim")


@responses.activate
def test_set_label_returns_revid_and_summary():
    mock_csrf_and_write({"entity": {"lastrevid": 999}}, "wbsetlabel")
    revid, summary = set_label(API_URL, "fake-token", "Q1", "sr", "нова реч", "test-agent")
    assert revid == 999
    assert "Duga" in summary


@responses.activate
def test_set_description_returns_revid_and_summary():
    mock_csrf_and_write({"entity": {"lastrevid": 1000}}, "wbsetdescription")
    revid, summary = set_description(API_URL, "fake-token", "Q1", "sr", "опис", "test-agent")
    assert revid == 1000


@responses.activate
def test_set_label_raises_on_api_error_response():
    mock_csrf_and_write({"error": {"code": "badtoken", "info": "Invalid token"}}, "wbsetlabel")
    with pytest.raises(WikidataWriteError, match="Invalid token"):
        set_label(API_URL, "fake-token", "Q1", "sr", "реч", "test-agent")


@responses.activate
def test_set_label_raises_on_http_error():
    responses.add(
        responses.GET,
        API_URL,
        json={"query": {"tokens": {"csrftoken": "abc123+\\"}}},
        status=200,
    )
    responses.add(responses.POST, API_URL, body="Internal Server Error", status=500)
    with pytest.raises(WikidataWriteError):
        set_label(API_URL, "fake-token", "Q1", "sr", "реч", "test-agent")


@responses.activate
def test_set_label_never_sends_a_bot_parameter():
    """MediaWiki's action API treats a boolean param as true if merely
    present, regardless of its string value -- passing bot="0" would
    actually mark the edit as a bot edit. These are individual,
    human-confirmed edits and must never carry that flag at all."""
    captured = {}

    def record_write(request):
        captured["body"] = request.body
        return (200, {}, '{"entity": {"lastrevid": 1}}')

    responses.add(
        responses.GET,
        API_URL,
        json={"query": {"tokens": {"csrftoken": "abc123+\\"}}},
        status=200,
    )
    responses.add_callback(responses.POST, API_URL, callback=record_write)

    set_label(API_URL, "fake-token", "Q1", "sr", "реч", "test-agent")
    assert "bot" not in captured["body"]


@responses.activate
def test_csrf_token_request_uses_bearer_auth():
    captured = {}

    def record_token_request(request):
        captured["auth"] = request.headers.get("Authorization")
        return (200, {}, '{"query": {"tokens": {"csrftoken": "abc"}}}')

    responses.add_callback(responses.GET, API_URL, callback=record_token_request)
    responses.add(responses.POST, API_URL, json={"entity": {"lastrevid": 1}}, status=200)

    set_label(API_URL, "the-access-token", "Q1", "sr", "реч", "test-agent")
    assert captured["auth"] == "Bearer the-access-token"


# -- add_sense --------------------------------------------------------------


@responses.activate
def test_add_sense_returns_sense_id_revid_and_summary():
    mock_csrf_and_write({"sense": {"id": "L12345-S1"}, "lastrevid": 555}, "wbladdsense")
    sense_id, revid, summary = add_sense(API_URL, "fake-token", "L12345", "sr", "нека дефиниција", "test-agent")
    assert sense_id == "L12345-S1"
    assert revid == 555
    assert "Duga" in summary


@responses.activate
def test_add_sense_sends_entity_and_glosses_data():
    captured = {}

    def record_write(request):
        captured["body"] = request.body
        return (200, {}, '{"sense": {"id": "L12345-S1"}, "lastrevid": 1}')

    responses.add(
        responses.GET, API_URL,
        json={"query": {"tokens": {"csrftoken": "abc123+\\"}}},
        status=200,
    )
    responses.add_callback(responses.POST, API_URL, callback=record_write)

    add_sense(API_URL, "fake-token", "L12345", "sr", "нека дефиниција", "test-agent")

    assert "action=wbladdsense" in captured["body"]
    assert "entity=L12345" in captured["body"]
    from urllib.parse import parse_qs
    parsed = parse_qs(captured["body"])
    payload = json.loads(parsed["data"][0])
    assert payload == {"glosses": {"sr": {"language": "sr", "value": "нека дефиниција"}}}


@responses.activate
def test_add_sense_raises_on_api_error_response():
    mock_csrf_and_write({"error": {"code": "no-such-entity", "info": "No such entity"}}, "wbladdsense")
    with pytest.raises(WikidataWriteError, match="No such entity"):
        add_sense(API_URL, "fake-token", "L12345", "sr", "дефиниција", "test-agent")


@responses.activate
def test_add_sense_raises_on_http_error():
    responses.add(
        responses.GET, API_URL,
        json={"query": {"tokens": {"csrftoken": "abc123+\\"}}},
        status=200,
    )
    responses.add(responses.POST, API_URL, body="Internal Server Error", status=500)
    with pytest.raises(WikidataWriteError):
        add_sense(API_URL, "fake-token", "L12345", "sr", "дефиниција", "test-agent")


@responses.activate
def test_add_sense_raises_when_response_has_no_sense_id():
    mock_csrf_and_write({"lastrevid": 1}, "wbladdsense")
    with pytest.raises(WikidataWriteError, match="no sense id"):
        add_sense(API_URL, "fake-token", "L12345", "sr", "дефиниција", "test-agent")


@responses.activate
def test_add_sense_never_sends_a_bot_parameter():
    captured = {}

    def record_write(request):
        captured["body"] = request.body
        return (200, {}, '{"sense": {"id": "L12345-S1"}, "lastrevid": 1}')

    responses.add(
        responses.GET, API_URL,
        json={"query": {"tokens": {"csrftoken": "abc123+\\"}}},
        status=200,
    )
    responses.add_callback(responses.POST, API_URL, callback=record_write)

    add_sense(API_URL, "fake-token", "L12345", "sr", "дефиниција", "test-agent")
    assert "bot" not in captured["body"]
