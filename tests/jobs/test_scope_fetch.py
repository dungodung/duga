import json

import pytest
import responses

from app.models import ScopeRule, ScopeVersion
from jobs import scope_fetch

SAMPLE_RULES_JSON = json.dumps(
    {
        "version": "2026-08-23",
        "rules": [
            {
                "key": "person_orientation_sourced",
                "label": "People with a referenced sexual orientation statement",
                "entity_class": "human",
                "requires_reference": True,
                "risk_level": "high",
                "rationale": "Only sourced, self-identified or well-documented claims.",
                "sparql_fragment": (
                    "?item wdt:P31 wd:Q5 . ?item p:P91 ?st . "
                    "?st prov:wasDerivedFrom ?ref ."
                ),
            },
            {
                "key": "org_lgbt",
                "label": "LGBT+ organisations",
                "entity_class": "organisation",
                "requires_reference": False,
                "risk_level": "low",
                "rationale": "Organisations are not persons; no outing risk.",
                "sparql_fragment": "?item wdt:P31/wdt:P279* wd:Q6458277 .",
            },
        ],
    }
)


def wikitext_with_scope_block(json_text, wrap_syntaxhighlight=True):
    body = f'<syntaxhighlight lang="json">\n{json_text}\n</syntaxhighlight>' if wrap_syntaxhighlight else json_text
    return f"Some intro prose.\n\n<!-- DUGA-SCOPE-START -->\n{body}\n<!-- DUGA-SCOPE-END -->\n\nMore prose."


def mock_wikitext_response(title, revid, wikitext):
    responses.add(
        responses.GET,
        "https://www.wikidata.org/w/api.php",
        json={
            "query": {
                "pages": [
                    {
                        "title": title,
                        "revisions": [{"revid": revid, "slots": {"main": {"content": wikitext}}}],
                    }
                ]
            }
        },
        status=200,
    )


# -- extract_scope_json --------------------------------------------------


def test_extract_scope_json_unwraps_syntaxhighlight():
    wikitext = wikitext_with_scope_block(SAMPLE_RULES_JSON)
    extracted = scope_fetch.extract_scope_json(wikitext)
    assert json.loads(extracted) == json.loads(SAMPLE_RULES_JSON)


def test_extract_scope_json_works_without_syntaxhighlight():
    wikitext = wikitext_with_scope_block(SAMPLE_RULES_JSON, wrap_syntaxhighlight=False)
    extracted = scope_fetch.extract_scope_json(wikitext)
    assert json.loads(extracted) == json.loads(SAMPLE_RULES_JSON)


def test_extract_scope_json_missing_markers_raises():
    with pytest.raises(scope_fetch.ScopeDefinitionError):
        scope_fetch.extract_scope_json("no markers here at all")


# -- parse_and_validate ---------------------------------------------------


def test_parse_and_validate_accepts_well_formed_scope():
    data = scope_fetch.parse_and_validate(SAMPLE_RULES_JSON)
    assert data["version"] == "2026-08-23"
    assert len(data["rules"]) == 2


def test_parse_and_validate_rejects_invalid_json():
    with pytest.raises(scope_fetch.ScopeDefinitionError):
        scope_fetch.parse_and_validate("{not json")


def test_parse_and_validate_rejects_missing_rules_list():
    with pytest.raises(scope_fetch.ScopeDefinitionError):
        scope_fetch.parse_and_validate(json.dumps({"version": "x"}))


def test_parse_and_validate_rejects_rule_missing_fields():
    bad = json.dumps({"version": "x", "rules": [{"key": "a"}]})
    with pytest.raises(scope_fetch.ScopeDefinitionError):
        scope_fetch.parse_and_validate(bad)


def test_parse_and_validate_rejects_bad_risk_level():
    rules = json.loads(SAMPLE_RULES_JSON)
    rules["rules"][0]["risk_level"] = "extreme"
    with pytest.raises(scope_fetch.ScopeDefinitionError):
        scope_fetch.parse_and_validate(json.dumps(rules))


def test_parse_and_validate_rejects_duplicate_rule_keys():
    rules = json.loads(SAMPLE_RULES_JSON)
    rules["rules"][1]["key"] = rules["rules"][0]["key"]
    with pytest.raises(scope_fetch.ScopeDefinitionError):
        scope_fetch.parse_and_validate(json.dumps(rules))


# -- run() end to end (mocked Wikidata API, real DB) ----------------------


@responses.activate
def test_run_stores_an_inactive_scope_version_with_its_rules(app):
    mock_wikitext_response(
        app.config["DUGA_SCOPE_PAGE"], 111, wikitext_with_scope_block(SAMPLE_RULES_JSON)
    )

    version = scope_fetch.run(app)

    assert version.active is False
    assert version.revision_id == 111
    stored = ScopeRule.query.filter_by(scope_version_id=version.id).all()
    assert {r.rule_key for r in stored} == {"person_orientation_sourced", "org_lgbt"}


@responses.activate
def test_run_is_idempotent_for_the_same_revision(app):
    mock_wikitext_response(
        app.config["DUGA_SCOPE_PAGE"], 222, wikitext_with_scope_block(SAMPLE_RULES_JSON)
    )
    mock_wikitext_response(
        app.config["DUGA_SCOPE_PAGE"], 222, wikitext_with_scope_block(SAMPLE_RULES_JSON)
    )

    first = scope_fetch.run(app)
    second = scope_fetch.run(app)

    assert first.id == second.id
    assert ScopeVersion.query.count() == 1
