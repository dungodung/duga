from ..extensions import db


class ContributorToken(db.Model):
    """OAuth access/refresh tokens for one contributor, encrypted at rest
    (app/token_crypto.py) -- never in the session cookie. This is the one
    place M6 reverses M4's original design ("access/refresh tokens...
    never persisted"): a write happens in a *second* request, after the
    user has previewed and confirmed, so something has to hold a usable
    credential between those two requests. Kept in its own table rather
    than columns on `contributor` so a normal query/dump of contributor
    rows for display never has encrypted token material sitting next to it.

    Not part of SPEC.md section 7's DDL (which predates M6) -- this is
    implementation detail below that section's abstraction level, not a
    deviation from anything specified there.
    """

    __tablename__ = "contributor_token"

    contributor_id = db.Column(db.Integer, db.ForeignKey("contributor.id"), primary_key=True)
    access_token_encrypted = db.Column(db.Text, nullable=False)
    refresh_token_encrypted = db.Column(db.Text, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False)
