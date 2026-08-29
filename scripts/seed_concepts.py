"""Operator CLI: bulk-loads local vocabulary concepts and terms from a
reviewed JSON file.

SPEC.md section 5 calls the add-a-term flow "the conference seeding path
and... the highest-value flow in the product", and section 16 leaves the
seed list itself explicitly open: "which ~50 concepts, chosen with input
from the Wikidata WikiProject LGBT community, not unilaterally." This
script is the mechanism for that decision, deliberately without the
decision: no concept list ships in this repo. `data/seed_concepts.example.json`
documents the format; the real file is written after that conversation and
passed in by path.

What it will not do, on purpose:

- No `qid`/`lexeme_id` field. Everything is created lifecycle 'local'.
  Linking upstream belongs to the M7 promotion path in the web UI, which
  checks live that the target already exists (SPEC.md section 10); a seed
  file must not become a second, weaker way to claim a Wikidata item.
- No evidence, and no evidence_grade. SPEC.md section 8 computes the grade
  from citations people actually add, so a seeded term starts at
  'single_report' exactly like one typed into the add-a-term form.

Idempotent (guardrail 8): re-running the same file adds nothing. Concepts
match on local_label case-insensitively -- the same lookup the add-a-term
route uses -- and terms on (concept, language, written form).

Usage:
    python3 scripts/seed_concepts.py <file.json> --by <your-wiki-username> --dry-run
    python3 scripts/seed_concepts.py <file.json> --by <your-wiki-username>
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func  # noqa: E402

from app import create_app  # noqa: E402
from app.audit import log as audit_log  # noqa: E402
from app.blueprints.vocabulary.routes import VALID_REGISTERS  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Concept, Language, Term  # noqa: E402


class SeedError(Exception):
    """A problem with the file itself, reported before anything is written."""


def validate(payload, seeded_languages):
    """Checks the whole file before a single row is created, so a typo in
    the last entry doesn't leave the first half loaded."""
    if not isinstance(payload, dict) or not isinstance(payload.get("concepts"), list):
        raise SeedError('file must be a JSON object with a "concepts" list')

    problems = []
    for index, concept in enumerate(payload["concepts"]):
        where = f"concepts[{index}]"
        if not isinstance(concept, dict):
            problems.append(f"{where}: not an object")
            continue
        label = (concept.get("local_label") or "").strip()
        if not label:
            problems.append(f"{where}: local_label is required")
        for banned in ("qid", "lexeme_id", "sense_id", "lifecycle", "evidence_grade"):
            if banned in concept:
                problems.append(f"{where}: {banned!r} is not seedable -- see this script's docstring")
        for term_index, term in enumerate(concept.get("terms") or []):
            term_where = f"{where}.terms[{term_index}]"
            if not isinstance(term, dict):
                problems.append(f"{term_where}: not an object")
                continue
            if not (term.get("written_form") or "").strip():
                problems.append(f"{term_where}: written_form is required")
            language_code = term.get("language_code")
            if language_code not in seeded_languages:
                problems.append(
                    f"{term_where}: language_code {language_code!r} is not a seeded content language "
                    f"({', '.join(sorted(seeded_languages))})"
                )
            register = term.get("register", "unknown")
            if register not in VALID_REGISTERS:
                problems.append(
                    f"{term_where}: register {register!r} is not one of {', '.join(sorted(VALID_REGISTERS))}"
                )
            for banned in ("lexeme_id", "sense_id", "lifecycle", "evidence_grade", "evidence"):
                if banned in term:
                    problems.append(f"{term_where}: {banned!r} is not seedable -- see this script's docstring")

    if problems:
        raise SeedError("\n".join(problems))


def load(payload, by, dry_run=False):
    """Creates whatever isn't already there. Returns (concepts_created,
    terms_created, skipped)."""
    now = datetime.now(timezone.utc)
    concepts_created = terms_created = skipped = 0

    for entry in payload["concepts"]:
        label = entry["local_label"].strip()
        concept = Concept.query.filter(
            func.lower(Concept.local_label) == label.lower(), Concept.suppressed.is_(False)
        ).first()
        if concept is None:
            print(f"+ concept {label!r}")
            concepts_created += 1
            concept = Concept(local_label=label, created_by=by, created_at=now)
            db.session.add(concept)
            db.session.flush()
            audit_log(
                actor=by, action="create_concept", entity_type="concept", entity_id=concept.id,
                before=None, after={"local_label": label, "source": "seed_concepts"},
            )
        else:
            print(f"= concept {label!r} (exists)")
            skipped += 1

        for term_entry in entry.get("terms") or []:
            written_form = term_entry["written_form"].strip()
            language_code = term_entry["language_code"]
            existing = Term.query.filter_by(
                concept_id=concept.id, language_code=language_code, written_form=written_form
            ).first()
            if existing is not None:
                print(f"  = term {written_form!r} [{language_code}] (exists)")
                skipped += 1
                continue
            print(f"  + term {written_form!r} [{language_code}]")
            terms_created += 1
            term = Term(
                concept_id=concept.id,
                language_code=language_code,
                written_form=written_form,
                register=term_entry.get("register", "unknown"),
                usage_note=(term_entry.get("usage_note") or "").strip() or None,
                lifecycle="local",
                # SPEC.md section 8: the grade is computed from evidence
                # people add, so a seeded term starts where a typed one does.
                evidence_grade="single_report",
                created_by=by,
                created_at=now,
                updated_at=now,
            )
            db.session.add(term)
            db.session.flush()
            audit_log(
                actor=by, action="create_term", entity_type="term", entity_id=term.id,
                before=None,
                after={
                    "concept_id": concept.id, "language_code": language_code,
                    "written_form": written_form, "source": "seed_concepts",
                },
            )

    if dry_run:
        db.session.rollback()
    else:
        db.session.commit()
    return concepts_created, terms_created, skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", help="path to the reviewed JSON seed file")
    parser.add_argument("--by", required=True, help="your wiki username, recorded as created_by and in audit_log")
    parser.add_argument("--dry-run", action="store_true", help="validate and report, writing nothing")
    args = parser.parse_args()

    with open(args.path, encoding="utf-8") as fh:
        payload = json.load(fh)

    app = create_app(os.environ.get("FLASK_ENV", "production"))
    with app.app_context():
        seeded_languages = {row.code for row in Language.query.filter_by(seeded=True).all()}
        try:
            validate(payload, seeded_languages)
        except SeedError as exc:
            print(f"seed file rejected:\n{exc}", file=sys.stderr)
            sys.exit(1)

        concepts, terms, skipped = load(payload, args.by, args.dry_run)
        verb = "would create" if args.dry_run else "created"
        print(f"{verb} {concepts} concept(s) and {terms} term(s); {skipped} already present")


if __name__ == "__main__":
    main()
