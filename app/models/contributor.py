from ..extensions import db


class Contributor(db.Model):
    """A logged-in Wikimedia account that has used Duga. Created on first
    login (SPEC.md section 9); keyed by wiki_username, which is what the
    OAuth profile gives us and what the product actually displays. No
    Duga-local passwords, ever -- identity comes entirely from Wikimedia
    OAuth."""

    __tablename__ = "contributor"

    id = db.Column(db.Integer, primary_key=True)
    wiki_username = db.Column(db.String(255), nullable=False, unique=True)
    # Opt-out (SPEC.md section 9): defaults to public, presented prominently
    # at first login, and changing it applies retroactively -- there is no
    # per-contribution attribution flag to update, display always consults
    # this one field.
    display_public = db.Column(db.Boolean, nullable=False, default=True)
    languages_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False)
    last_seen_at = db.Column(db.DateTime, nullable=True)
