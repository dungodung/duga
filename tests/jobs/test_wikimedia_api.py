import responses

from jobs.wikimedia_api import get_entities_batch, get_raw_labels_and_descriptions

API_URL = "https://www.wikidata.org/w/api.php"


@responses.activate
def test_get_entities_batch_uses_content_language_label_when_present():
    responses.add(
        responses.GET,
        API_URL,
        json={
            "entities": {
                "Q1": {
                    "id": "Q1",
                    "sitelinks": {},
                    "labels": {
                        "sr": {"value": "Пример", "language": "sr"},
                        "en": {"value": "Example", "language": "en"},
                    },
                }
            }
        },
        status=200,
    )
    result = get_entities_batch(API_URL, ["Q1"], "sr", "test-agent")
    assert result["Q1"]["label"] == "Пример"


@responses.activate
def test_get_entities_batch_falls_back_to_english_when_content_language_label_missing():
    responses.add(
        responses.GET,
        API_URL,
        json={
            "entities": {
                "Q1": {
                    "id": "Q1",
                    "sitelinks": {},
                    # No "sr" key at all -- MediaWiki's own fallback chain
                    # for sr doesn't always reach "en".
                    "labels": {"en": {"value": "Example", "language": "en"}},
                }
            }
        },
        status=200,
    )
    result = get_entities_batch(API_URL, ["Q1"], "sr", "test-agent")
    assert result["Q1"]["label"] == "Example"


@responses.activate
def test_get_entities_batch_label_is_none_when_neither_language_has_one():
    responses.add(
        responses.GET,
        API_URL,
        json={"entities": {"Q1": {"id": "Q1", "sitelinks": {}, "labels": {}}}},
        status=200,
    )
    result = get_entities_batch(API_URL, ["Q1"], "sr", "test-agent")
    assert result["Q1"]["label"] is None


@responses.activate
def test_get_entities_batch_requests_content_language_and_english(monkeypatch):
    captured = {}

    def record_request(request):
        captured["url"] = request.url
        return (200, {}, '{"entities": {}}')

    responses.add_callback(responses.GET, API_URL, callback=record_request)
    get_entities_batch(API_URL, ["Q1"], "sr", "test-agent")
    assert "languages=sr%7Cen" in captured["url"]


@responses.activate
def test_get_entities_batch_does_not_duplicate_english_when_content_language_is_english():
    captured = {}

    def record_request(request):
        captured["url"] = request.url
        return (200, {}, '{"entities": {}}')

    responses.add_callback(responses.GET, API_URL, callback=record_request)
    get_entities_batch(API_URL, ["Q1"], "en", "test-agent")
    assert "languages=en&" in captured["url"]


# -- get_raw_labels_and_descriptions ---------------------------------------


@responses.activate
def test_get_raw_labels_does_not_request_languagefallback():
    captured = {}

    def record_request(request):
        captured["url"] = request.url
        return (200, {}, '{"entities": {}}')

    responses.add_callback(responses.GET, API_URL, callback=record_request)
    get_raw_labels_and_descriptions(API_URL, ["Q1"], "sr", "test-agent")
    assert "languagefallback" not in captured["url"]
    assert "languages=sr%7Cen" in captured["url"]


@responses.activate
def test_get_raw_labels_separates_genuine_per_language_values():
    responses.add(
        responses.GET,
        API_URL,
        json={
            "entities": {
                "Q1": {
                    "id": "Q1",
                    "labels": {"en": {"value": "English label", "language": "en"}},
                    "descriptions": {
                        "sr": {"value": "Српски опис", "language": "sr"},
                        "en": {"value": "English description", "language": "en"},
                    },
                }
            }
        },
        status=200,
    )
    result = get_raw_labels_and_descriptions(API_URL, ["Q1"], "sr", "test-agent")
    assert result["Q1"] == {
        "label_language": None,
        "label_en": "English label",
        "description_language": "Српски опис",
        "description_en": "English description",
    }


@responses.activate
def test_get_raw_labels_handles_missing_entity():
    responses.add(
        responses.GET,
        API_URL,
        json={"entities": {"Q999": {"id": "Q999", "missing": ""}}},
        status=200,
    )
    result = get_raw_labels_and_descriptions(API_URL, ["Q999"], "sr", "test-agent")
    assert result["Q999"] == {
        "label_language": None,
        "label_en": None,
        "description_language": None,
        "description_en": None,
    }
