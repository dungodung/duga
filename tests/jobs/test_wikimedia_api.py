import re

import pytest
import responses

from jobs.wikimedia_api import (
    WikimediaApiError,
    get_claims_batch,
    get_entities_batch,
    get_monthly_pageviews,
    get_raw_labels_and_descriptions,
)

API_URL = "https://www.wikidata.org/w/api.php"
PAGEVIEWS_PREFIX = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/sr.wikipedia/all-access/all-agents/"


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


# -- get_monthly_pageviews ---------------------------------------------------


@responses.activate
def test_get_monthly_pageviews_sums_items():
    responses.add(
        responses.GET,
        re.compile(re.escape(PAGEVIEWS_PREFIX) + r"Marsha_P\._Johnson/monthly/\d+/\d+"),
        json={"items": [{"views": 12345}]},
        status=200,
    )
    assert get_monthly_pageviews("sr", "Marsha P. Johnson", "test-agent") == 12345


@responses.activate
def test_get_monthly_pageviews_sums_multiple_items_defensively():
    responses.add(
        responses.GET,
        re.compile(re.escape(PAGEVIEWS_PREFIX) + r".+/monthly/\d+/\d+"),
        json={"items": [{"views": 100}, {"views": 50}]},
        status=200,
    )
    assert get_monthly_pageviews("sr", "Some Article", "test-agent") == 150


@responses.activate
def test_get_monthly_pageviews_returns_zero_on_404():
    responses.add(
        responses.GET,
        re.compile(re.escape(PAGEVIEWS_PREFIX) + r".+/monthly/\d+/\d+"),
        status=404,
    )
    assert get_monthly_pageviews("sr", "Too New Article", "test-agent") == 0


@responses.activate
def test_get_monthly_pageviews_raises_on_server_error():
    responses.add(
        responses.GET,
        re.compile(re.escape(PAGEVIEWS_PREFIX) + r".+/monthly/\d+/\d+"),
        status=500,
        body="Internal Server Error",
    )
    with pytest.raises(WikimediaApiError):
        get_monthly_pageviews("sr", "Some Article", "test-agent")


@responses.activate
def test_get_monthly_pageviews_encodes_title_with_spaces_and_dots():
    captured = {}

    def record(request):
        captured["url"] = request.url
        return (200, {}, '{"items": [{"views": 1}]}')

    responses.add_callback(
        responses.GET,
        re.compile(re.escape(PAGEVIEWS_PREFIX) + r".+"),
        callback=record,
    )
    get_monthly_pageviews("sr", "Marsha P. Johnson", "test-agent")
    assert "Marsha_P.%20Johnson" not in captured["url"]
    assert "Marsha_P._Johnson" in captured["url"]


# -- get_claims_batch -------------------------------------------------------


@responses.activate
def test_get_claims_batch_true_when_property_present():
    responses.add(
        responses.GET,
        API_URL,
        json={
            "entities": {
                "Q1": {
                    "id": "Q1",
                    "claims": {"P18": [{"mainsnak": {}}]},
                    "labels": {"en": {"value": "Has an image", "language": "en"}},
                }
            }
        },
        status=200,
    )
    result = get_claims_batch(API_URL, ["Q1"], ["P18"], "sr", "test-agent")
    assert result["Q1"] == {"claims": {"P18": True}, "label": "Has an image"}


@responses.activate
def test_get_claims_batch_false_when_property_absent():
    responses.add(
        responses.GET,
        API_URL,
        json={
            "entities": {
                "Q1": {
                    "id": "Q1",
                    "claims": {"P31": [{"mainsnak": {}}]},
                    "labels": {},
                }
            }
        },
        status=200,
    )
    result = get_claims_batch(API_URL, ["Q1"], ["P18"], "sr", "test-agent")
    assert result["Q1"] == {"claims": {"P18": False}, "label": None}


@responses.activate
def test_get_claims_batch_false_when_property_present_but_empty_list():
    responses.add(
        responses.GET,
        API_URL,
        json={"entities": {"Q1": {"id": "Q1", "claims": {"P18": []}, "labels": {}}}},
        status=200,
    )
    result = get_claims_batch(API_URL, ["Q1"], ["P18"], "sr", "test-agent")
    assert result["Q1"]["claims"]["P18"] is False


@responses.activate
def test_get_claims_batch_handles_missing_entity():
    responses.add(
        responses.GET,
        API_URL,
        json={"entities": {"Q999": {"id": "Q999", "missing": ""}}},
        status=200,
    )
    result = get_claims_batch(API_URL, ["Q999"], ["P18", "P373"], "sr", "test-agent")
    assert result["Q999"] == {"claims": {"P18": False, "P373": False}, "label": None}
