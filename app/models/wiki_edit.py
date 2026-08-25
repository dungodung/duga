from sqlalchemy.dialects import mysql

from ..extensions import db


class WikiEdit(db.Model):
    """SPEC.md section 7: one row per attempted write to a wiki, before and
    after (guardrail 11). A row is created with status='pending' before the
    Wikidata API call is even made, so a crash mid-write still leaves a
    record that something was attempted."""

    __tablename__ = "wiki_edit"

    id = db.Column(db.Integer().with_variant(mysql.BIGINT(), "mysql"), primary_key=True)
    contributor = db.Column(db.String(255), nullable=False)
    target_wiki = db.Column(db.String(64), nullable=False)
    target_entity = db.Column(db.String(64), nullable=False)
    edit_kind = db.Column(db.String(64), nullable=False)  # label | description | lexeme | sense
    summary = db.Column(db.Text, nullable=False)
    revid = db.Column(db.Integer().with_variant(mysql.BIGINT(), "mysql"), nullable=True)
    status = db.Column(
        db.Enum("pending", "success", "failed", "blocked", name="wiki_edit_status"), nullable=False
    )
    error = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False)

    __table_args__ = (
        db.Index("ix_wiki_edit_contributor_created", "contributor", "created_at"),
        db.Index("ix_wiki_edit_created_at", "created_at"),
    )
