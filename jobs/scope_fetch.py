"""Toolforge job: pulls the on-wiki scope definition page (SPEC.md section 6),
versions it into scope_version/scope_rule, and never auto-activates it -- an
operator promotes a version explicitly via scripts/activate_scope_version.py.

Run via: python3 jobs/scope_fetch.py
Idempotent (SPEC.md guardrail 8): re-fetching the same (page, revision_id)
is a no-op.
"""
import os
import sys

# Running this file directly (as Toolforge jobs do) puts jobs/ on sys.path,
# not the repo root -- without this, `from app import ...` below fails with
# ModuleNotFoundError exactly like the pytest console-script issue this repo
# already hit once (see pyproject.toml).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json  # noqa: E402
import re  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import ScopeRule, ScopeVersion  # noqa: E402
from jobs.wikimedia_api import fetch_page_wikitext  # noqa: E402

SCOPE_BLOCK_RE = re.compile(
    r"<!--\s*DUGA-SCOPE-START\s*-->(.*?)<!--\s*DUGA-SCOPE-END\s*-->", re.DOTALL
)
SYNTAXHIGHLIGHT_RE = re.compile(r"<syntaxhighlight[^>]*>(.*?)</syntaxhighlight>", re.DOTALL)

REQUIRED_RULE_KEYS = {
    "key",
    "label",
    "entity_class",
    "requires_reference",
    "risk_level",
    "rationale",
    "sparql_fragment",
}
VALID_RISK_LEVELS = {"low", "medium", "high"}


class ScopeDefinitionError(ValueError):
    """The on-wiki page exists but its content doesn't parse as a valid scope definition."""


def extract_scope_json(wikitext: str) -> str:
    match = SCOPE_BLOCK_RE.search(wikitext)
    if not match:
        raise ScopeDefinitionError(
            "No <!-- DUGA-SCOPE-START --> ... <!-- DUGA-SCOPE-END --> block "
            "found on the scope page -- see docs/scope-definition.md"
        )
    block = match.group(1)
    highlight_match = SYNTAXHIGHLIGHT_RE.search(block)
    if highlight_match:
        block = highlight_match.group(1)
    return block.strip()


def parse_and_validate(raw_json: str) -> dict:
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ScopeDefinitionError(f"Scope definition is not valid JSON: {exc}") from exc

    if not isinstance(data, dict) or "version" not in data or "rules" not in data:
        raise ScopeDefinitionError(
            "Scope definition must be a JSON object with 'version' and 'rules'"
        )
    if not isinstance(data["rules"], list) or not data["rules"]:
        raise ScopeDefinitionError("Scope definition must have a non-empty 'rules' list")

    seen_keys = set()
    for rule in data["rules"]:
        missing = REQUIRED_RULE_KEYS - rule.keys()
        if missing:
            raise ScopeDefinitionError(
                f"Rule {rule.get('key', '?')!r} is missing fields: {sorted(missing)}"
            )
        if rule["risk_level"] not in VALID_RISK_LEVELS:
            raise ScopeDefinitionError(
                f"Rule {rule['key']!r} has invalid risk_level {rule['risk_level']!r}"
            )
        if rule["key"] in seen_keys:
            raise ScopeDefinitionError(f"Duplicate rule key {rule['key']!r} in scope definition")
        seen_keys.add(rule["key"])

    return data


def run(app=None):
    app = app or create_app(os.environ.get("FLASK_ENV", "production"))
    with app.app_context():
        source_page = app.config["DUGA_SCOPE_PAGE"]
        revision_id, wikitext = fetch_page_wikitext(
            app.config["DUGA_WIKIDATA_API"], source_page, app.config["DUGA_USER_AGENT"]
        )

        existing = ScopeVersion.query.filter_by(
            source_page=source_page, revision_id=revision_id
        ).first()
        if existing:
            print(
                f"scope_fetch: revision {revision_id} of {source_page!r} "
                f"already stored (scope_version id={existing.id}); nothing to do"
            )
            return existing

        raw_json = extract_scope_json(wikitext)
        data = parse_and_validate(raw_json)

        version = ScopeVersion(
            source_page=source_page,
            revision_id=revision_id,
            raw_json=raw_json,
            fetched_at=datetime.now(timezone.utc),
            active=False,
        )
        db.session.add(version)
        db.session.flush()  # assigns version.id for the rules below

        for rule in data["rules"]:
            db.session.add(
                ScopeRule(
                    scope_version_id=version.id,
                    rule_key=rule["key"],
                    label=rule["label"],
                    entity_class=rule["entity_class"],
                    requires_reference=bool(rule["requires_reference"]),
                    risk_level=rule["risk_level"],
                    rationale=rule.get("rationale"),
                    sparql_fragment=rule["sparql_fragment"],
                )
            )

        db.session.commit()
        print(
            f"scope_fetch: stored scope_version {version.id} (revision "
            f"{revision_id}, {len(data['rules'])} rules), inactive -- "
            f"activate with scripts/activate_scope_version.py"
        )
        return version


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:  # noqa: BLE001 -- a job must fail loudly, never swallow errors
        print(f"scope_fetch FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
