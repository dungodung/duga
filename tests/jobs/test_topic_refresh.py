from datetime import datetime, timezone

import pytest
import responses

from app.extensions import db
from app.models import ScopeRule, ScopeVersion, Topic, TopicRule
from jobs import topic_refresh

WDQS_URL = "https://query.wikidata.org/sparql"


def make_active_scope_version(*rules):
    version = ScopeVersion(
        source_page="Wikidata:WikiProject LGBT/Duga/scope",
        revision_id=1,
        raw_json="{}",
        fetched_at=datetime.now(timezone.utc),
        active=True,
    )
    db.session.add(version)
    db.session.flush()
    for rule in rules:
        rule.scope_version_id = version.id
        db.session.add(rule)
    db.session.commit()
    return version


def sparql_json(*qids_with_dod):
    """qids_with_dod: list of (qid, has_death_date) tuples."""
    bindings = []
    for qid, has_dod in qids_with_dod:
        row = {"item": {"type": "uri", "value": f"http://www.wikidata.org/entity/{qid}"}}
        if has_dod:
            row["dod"] = {"type": "literal", "value": "1990-01-01T00:00:00Z"}
        bindings.append(row)
    return {"head": {"vars": ["item", "dod"]}, "results": {"bindings": bindings}}


# -- resolve_rule / requires_reference enforcement ------------------------


def test_resolve_rule_refuses_unreferenced_human_rule(app):
    rule = ScopeRule(
        rule_key="unsafe",
        label="Unsafe",
        entity_class="human",
        requires_reference=True,
        risk_level="high",
        sparql_fragment="?item wdt:P31 wd:Q5 . ?item wdt:P91 wd:Q6636.",  # no prov:wasDerivedFrom
    )
    with pytest.raises(topic_refresh.ScopeRuleRefused):
        topic_refresh.resolve_rule(rule, app)


@responses.activate
def test_resolve_rule_computes_is_living_from_death_date(app):
    responses.add(responses.GET, WDQS_URL, json=sparql_json(("Q1", False), ("Q2", True)), status=200)
    rule = ScopeRule(
        rule_key="person_orientation_sourced",
        label="Sourced orientation",
        entity_class="human",
        requires_reference=True,
        risk_level="high",
        sparql_fragment="?item wdt:P31 wd:Q5 . ?item p:P91 ?st . ?st prov:wasDerivedFrom ?ref .",
    )
    result = topic_refresh.resolve_rule(rule, app)
    assert result == {"Q1": True, "Q2": False}


# -- run() end to end (mocked WDQS, real DB) ------------------------------


@responses.activate
def test_run_populates_topic_and_topic_rule(app):
    responses.add(responses.GET, WDQS_URL, json=sparql_json(("Q1", False)), status=200)
    responses.add(
        responses.GET,
        WDQS_URL,
        json={
            "head": {"vars": ["item"]},
            "results": {"bindings": [{"item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q42"}}]},
        },
        status=200,
    )

    human_rule = ScopeRule(
        rule_key="person_orientation_sourced",
        label="Sourced orientation",
        entity_class="human",
        requires_reference=True,
        risk_level="high",
        sparql_fragment="?item wdt:P31 wd:Q5 . ?item p:P91 ?st . ?st prov:wasDerivedFrom ?ref .",
    )
    org_rule = ScopeRule(
        rule_key="org_lgbt",
        label="LGBT+ organisations",
        entity_class="organisation",
        requires_reference=False,
        risk_level="low",
        sparql_fragment="?item wdt:P31/wdt:P279* wd:Q6458277 .",
    )
    make_active_scope_version(human_rule, org_rule)

    topic_refresh.run(app)

    q1 = db.session.get(Topic, "Q1")
    assert q1.is_human is True
    assert q1.is_living is True
    assert q1.entity_class == "human"

    q42 = db.session.get(Topic, "Q42")
    assert q42.is_human is False
    assert q42.entity_class == "organisation"

    rule_keys = {tr.rule_key for tr in TopicRule.query.filter_by(topic_qid="Q1").all()}
    assert rule_keys == {"person_orientation_sourced"}


@responses.activate
def test_run_is_idempotent_and_preserves_first_seen(app):
    responses.add(responses.GET, WDQS_URL, json=sparql_json(("Q1", False)), status=200)
    responses.add(responses.GET, WDQS_URL, json=sparql_json(("Q1", False)), status=200)

    rule = ScopeRule(
        rule_key="person_orientation_sourced",
        label="Sourced orientation",
        entity_class="human",
        requires_reference=True,
        risk_level="high",
        sparql_fragment="?item wdt:P31 wd:Q5 . ?item p:P91 ?st . ?st prov:wasDerivedFrom ?ref .",
    )
    make_active_scope_version(rule)

    topic_refresh.run(app)
    first_seen_1 = db.session.get(Topic, "Q1").first_seen

    topic_refresh.run(app)
    topic = db.session.get(Topic, "Q1")

    assert topic.first_seen == first_seen_1
    assert TopicRule.query.filter_by(topic_qid="Q1").count() == 1


def test_run_exits_loudly_with_no_active_scope_version(app):
    with pytest.raises(SystemExit):
        topic_refresh.run(app)


@responses.activate
def test_run_never_unsuppresses_a_suppressed_topic(app):
    responses.add(responses.GET, WDQS_URL, json=sparql_json(("Q1", False)), status=200)
    rule = ScopeRule(
        rule_key="person_orientation_sourced",
        label="Sourced orientation",
        entity_class="human",
        requires_reference=True,
        risk_level="high",
        sparql_fragment="?item wdt:P31 wd:Q5 . ?item p:P91 ?st . ?st prov:wasDerivedFrom ?ref .",
    )
    make_active_scope_version(rule)

    now = datetime.now(timezone.utc)
    db.session.add(
        Topic(
            qid="Q1",
            entity_class="human",
            is_human=True,
            is_living=True,
            first_seen=now,
            last_seen=now,
            suppressed=True,
            suppressed_reason="operator decision",
        )
    )
    db.session.commit()

    topic_refresh.run(app)

    topic = db.session.get(Topic, "Q1")
    assert topic.suppressed is True
    assert topic.suppressed_reason == "operator decision"


# -- partial failure: a rule that could not be checked keeps its rows -------
#
# From the 2026-09-01 incident: WDQS returned a truncated 865KB body,
# json.JSONDecodeError escaped every handler, and the job died before
# touching the database. Typing that error as WikimediaApiError (so the
# per-rule handler catches it) is only safe if a skipped rule's topic_rule
# rows survive -- otherwise the fix would trade a loud crash for the silent
# deletion of ~7,000 associations the UI reads to explain scope.


@responses.activate
def test_a_failed_rule_keeps_its_previous_topic_rule_rows(app):
    concept = ScopeRule(
        rule_key="lgbt_concept",
        label="Concepts",
        entity_class="concept",
        requires_reference=False,
        risk_level="low",
        sparql_fragment="?item wdt:P31 wd:Q17884.",
    )
    people = ScopeRule(
        rule_key="person_orientation_sourced",
        label="Sourced orientation",
        entity_class="human",
        requires_reference=True,
        risk_level="high",
        sparql_fragment="?item wdt:P31 wd:Q5 . ?item p:P91 ?st . ?st prov:wasDerivedFrom ?ref .",
    )
    make_active_scope_version(concept, people)

    # First run: both rules resolve.
    responses.add(responses.GET, WDQS_URL, json=sparql_json(("Q1", False)), status=200)
    responses.add(responses.GET, WDQS_URL, json=sparql_json(("Q2", True)), status=200)
    topic_refresh.run(app)
    assert TopicRule.query.filter_by(rule_key="person_orientation_sourced").count() == 1

    # Second run: the people rule comes back truncated.
    responses.reset()
    responses.add(responses.GET, WDQS_URL, json=sparql_json(("Q1", False)), status=200)
    responses.add(responses.GET, WDQS_URL, body='{"head": {"vars": ["item"', status=200)
    responses.add(responses.GET, WDQS_URL, body='{"head": {"vars": ["item"', status=200)

    with pytest.raises(SystemExit) as exc:
        topic_refresh.run(app)
    assert exc.value.code == 1

    # The rule that worked is rewritten; the one that failed keeps yesterday's
    # answer rather than silently becoming "matches nothing".
    assert TopicRule.query.filter_by(rule_key="lgbt_concept").count() == 1
    assert TopicRule.query.filter_by(rule_key="person_orientation_sourced").count() == 1
    assert db.session.get(Topic, "Q2") is not None


@responses.activate
def test_a_truncated_wdqs_body_is_a_skipped_rule_not_a_crash(app):
    """The exact 2026-09-01 shape: a clean HTTP 200 whose body stops
    mid-string. It must reach the per-rule handler as a WikimediaApiError."""
    rule = ScopeRule(
        rule_key="lgbt_concept",
        label="Concepts",
        entity_class="concept",
        requires_reference=False,
        risk_level="low",
        sparql_fragment="?item wdt:P31 wd:Q17884.",
    )
    make_active_scope_version(rule)
    for _ in range(2):  # both attempts truncated
        responses.add(responses.GET, WDQS_URL, body='{"head": {"vars": ["item"', status=200)

    with pytest.raises(SystemExit) as exc:
        topic_refresh.run(app)
    assert exc.value.code == 1


@responses.activate
def test_a_truncated_body_is_retried_once_and_can_succeed(app):
    rule = ScopeRule(
        rule_key="lgbt_concept",
        label="Concepts",
        entity_class="concept",
        requires_reference=False,
        risk_level="low",
        sparql_fragment="?item wdt:P31 wd:Q17884.",
    )
    make_active_scope_version(rule)
    responses.add(responses.GET, WDQS_URL, body='{"head": {"vars": ["item"', status=200)
    responses.add(responses.GET, WDQS_URL, json=sparql_json(("Q1", False)), status=200)

    topic_refresh.run(app)  # no SystemExit: the retry carried it
    assert TopicRule.query.filter_by(rule_key="lgbt_concept").count() == 1
