"""SPEC.md section 8: evidence grading. Grades are ranked
documented > organisational > community > single_report; a term's stored
evidence_grade is always the *best* grade currently justified by its
term_evidence/term_assertion rows, recomputed here whenever either changes.
Stored rather than computed purely at read time so list views don't need a
join+count per row -- but the source of truth is always these rows, never a
value someone typed into evidence_grade directly (community explicitly
never is, per spec; the same rule is applied uniformly here).
"""
from flask import current_app

DOCUMENTED_KINDS = {"publication", "style_guide", "dictionary", "law"}
ORGANISATIONAL_KINDS = {"organisation"}


def recompute_evidence_grade(term) -> str:
    """Recomputes and assigns term.evidence_grade in place. Caller is
    responsible for committing."""
    kinds = {e.kind for e in term.evidence}

    if kinds & DOCUMENTED_KINDS:
        grade = "documented"
    elif kinds & ORGANISATIONAL_KINDS:
        grade = "organisational"
    else:
        threshold = current_app.config["DUGA_COMMUNITY_ASSERTION_THRESHOLD"]
        agree_count = sum(1 for a in term.assertions if a.agrees)
        grade = "community" if agree_count >= threshold else "single_report"

    term.evidence_grade = grade
    return grade
