"""SPEC.md S5: attribution is opt-out per contributor, and no display path
should assume a plain-text username column is safe to render as-is --
someone may have opted out since the row was written, or the row may
predate any Contributor row existing for that username at all. Every place
that would otherwise print created_by/added_by/contributor must go through
this first.
"""
from .models import Contributor


def public_name(username):
    """Returns `username` if that contributor exists and has opted into
    public display, else None. Callers render None as generic/anonymous --
    per guardrail 12 ("when in doubt about a sensitive display decision,
    show less"), a username with no matching Contributor row (data that
    predates login, or an edge case) is treated as not-public, not as
    public-by-default.
    """
    contributor = Contributor.query.filter_by(wiki_username=username).first()
    if contributor and contributor.display_public:
        return username
    return None
