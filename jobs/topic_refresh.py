"""Toolforge job: resolves the active scope_version's rules to topics via
WDQS and writes the `topic`/`topic_rule` tables (SPEC.md section 4, 7, 11).

Run via: python3 jobs/topic_refresh.py
Idempotent (SPEC.md guardrail 8): for the active scope_version, topic_rule
rows are fully replaced each run to reflect exactly what WDQS returns now;
`topic` rows persist across runs (first_seen never moves, last_seen does),
and this job never touches `suppressed`/`suppressed_*` -- those are set only
by an operator/contributor action, never by re-detection.

SPEC.md section 3, S2: a scope rule matching people via an identity property
MUST require a reference on that statement, and this must be enforced in
code, not merely trusted from the rule's `requires_reference` flag (section
6). Enforcement here is static: if a rule claims requires_reference=True but
its SPARQL fragment contains no `prov:wasDerivedFrom` reference-provenance
pattern, the rule is refused and skipped entirely -- silently as far as any
topic list is concerned (S2), loudly in this job's own log (guardrail 9).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone  # noqa: E402

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import ScopeVersion, Topic, TopicRule  # noqa: E402
from jobs.wikimedia_api import WikimediaApiError, qid_from_uri, run_sparql  # noqa: E402

# A soft cap to stay inside WDQS's public 60s budget (SPEC.md section 4).
# Chunking by entity class for rules that legitimately exceed this is an
# open question (SPEC.md section 16), deliberately deferred past M1.
ROW_LIMIT = 20000

REFERENCE_PATTERN = "prov:wasDerivedFrom"


class ScopeRuleRefused(RuntimeError):
    """A rule claims requires_reference=True without actually filtering on a
    reference in its SPARQL -- refused per SPEC.md section 3, S2."""


def build_query(rule) -> str:
    if rule.entity_class == "human":
        return (
            "SELECT DISTINCT ?item ?dod WHERE { "
            f"{rule.sparql_fragment} "
            "OPTIONAL { ?item wdt:P570 ?dod } "
            f"}} LIMIT {ROW_LIMIT}"
        )
    return f"SELECT DISTINCT ?item WHERE {{ {rule.sparql_fragment} }} LIMIT {ROW_LIMIT}"


def resolve_rule(rule, app):
    """Returns {qid: is_living_or_None} for one scope_rule. Raises
    ScopeRuleRefused or WikimediaApiError -- callers decide how to log/skip."""
    if rule.requires_reference and REFERENCE_PATTERN not in rule.sparql_fragment:
        raise ScopeRuleRefused(
            f"rule {rule.rule_key!r} has requires_reference=True but its "
            f"sparql_fragment has no {REFERENCE_PATTERN} pattern -- refusing "
            "to run it (SPEC.md section 3, S2)"
        )

    rows = run_sparql(
        app.config["DUGA_WDQS_ENDPOINT"],
        build_query(rule),
        app.config["DUGA_USER_AGENT"],
    )
    if len(rows) >= ROW_LIMIT:
        print(
            f"topic_refresh: WARNING rule {rule.rule_key!r} hit the "
            f"{ROW_LIMIT}-row limit -- results are likely truncated",
            file=sys.stderr,
        )

    is_living_by_qid = {}
    for row in rows:
        qid = qid_from_uri(row["item"])
        has_death_date = rule.entity_class == "human" and row.get("dod")
        # A qid can appear once per death-date statement; once we've seen
        # one bound death date it's not living, and that never flips back.
        is_living_by_qid[qid] = is_living_by_qid.get(qid, True) and not has_death_date
    return is_living_by_qid


def run(app=None):
    app = app or create_app(os.environ.get("FLASK_ENV", "production"))
    with app.app_context():
        active_version = ScopeVersion.query.filter_by(active=True).first()
        if active_version is None:
            print(
                "topic_refresh: no active scope_version -- run scope_fetch and "
                "activate one with scripts/activate_scope_version.py first",
                file=sys.stderr,
            )
            sys.exit(1)

        now = datetime.now(timezone.utc)
        # qid -> {"entity_class": ..., "is_living": ..., "rule_keys": {...}}
        topics = {}
        failures = []

        for rule in active_version.rules:
            try:
                is_living_by_qid = resolve_rule(rule, app)
            except (ScopeRuleRefused, WikimediaApiError) as exc:
                print(f"topic_refresh: skipping rule {rule.rule_key!r}: {exc}", file=sys.stderr)
                failures.append(rule.rule_key)
                continue

            for qid, is_living in is_living_by_qid.items():
                entry = topics.setdefault(
                    qid, {"entity_class": rule.entity_class, "is_living": False, "rule_keys": set()}
                )
                entry["entity_class"] = rule.entity_class
                entry["is_living"] = is_living
                entry["rule_keys"].add(rule.rule_key)

        for qid, info in topics.items():
            topic = db.session.get(Topic, qid)
            if topic is None:
                topic = Topic(qid=qid, first_seen=now, suppressed=False)
                db.session.add(topic)
            topic.entity_class = info["entity_class"]
            topic.is_human = info["entity_class"] == "human"
            topic.is_living = info["is_living"]
            topic.last_seen = now

        TopicRule.query.filter_by(scope_version_id=active_version.id).delete()
        for qid, info in topics.items():
            for rule_key in info["rule_keys"]:
                db.session.add(
                    TopicRule(topic_qid=qid, rule_key=rule_key, scope_version_id=active_version.id)
                )

        db.session.commit()
        print(
            f"topic_refresh: scope_version {active_version.id}: "
            f"{len(topics)} topics from {len(active_version.rules) - len(failures)}/"
            f"{len(active_version.rules)} rules"
            + (f" ({len(failures)} rule(s) skipped: {failures})" if failures else "")
        )
        if failures:
            sys.exit(1)


if __name__ == "__main__":
    try:
        run()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 -- a job must fail loudly, never swallow errors
        print(f"topic_refresh FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
