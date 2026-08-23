from sqlalchemy.dialects import mysql

from ..extensions import db


class ScopeVersion(db.Model):
    """One fetched revision of the on-wiki scope definition page. See
    SPEC.md section 6: a new version never auto-activates -- it lands with
    active=False and an operator promotes it (scripts/activate_scope_version.py).
    """

    __tablename__ = "scope_version"

    id = db.Column(db.Integer, primary_key=True)
    source_page = db.Column(db.String(255), nullable=False)
    revision_id = db.Column(db.BigInteger, nullable=False)
    # MEDIUMTEXT on MySQL/MariaDB (matches SPEC.md section 7's DDL exactly);
    # plain TEXT elsewhere (e.g. SQLite in tests), which has no size cap.
    raw_json = db.Column(db.Text().with_variant(mysql.MEDIUMTEXT(), "mysql"), nullable=False)
    fetched_at = db.Column(db.DateTime, nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=False)
    activated_at = db.Column(db.DateTime, nullable=True)
    activated_by = db.Column(db.String(255), nullable=True)

    # order_by matters beyond cosmetics: topic_refresh.py iterates these to
    # query WDQS per rule, and later rules can overwrite an earlier rule's
    # entity_class for the same topic (SPEC.md docs/architecture.md notes
    # "last rule wins") -- that resolution must be deterministic.
    rules = db.relationship(
        "ScopeRule", backref="scope_version", cascade="all, delete-orphan", order_by="ScopeRule.id"
    )

    __table_args__ = (db.UniqueConstraint("source_page", "revision_id"),)


class ScopeRule(db.Model):
    """One rule within a scope_version -- see SPEC.md section 6's JSON
    format. requires_reference is trusted here only as *metadata*; the
    actual reference enforcement for humans (SPEC.md section 3, S2) happens
    in code in jobs/topic_refresh.py, never by trusting this flag alone.
    """

    __tablename__ = "scope_rule"

    id = db.Column(db.Integer, primary_key=True)
    scope_version_id = db.Column(
        db.Integer, db.ForeignKey("scope_version.id"), nullable=False
    )
    rule_key = db.Column(db.String(64), nullable=False)
    label = db.Column(db.String(255), nullable=False)
    entity_class = db.Column(db.String(32), nullable=False)
    requires_reference = db.Column(db.Boolean, nullable=False, default=False)
    risk_level = db.Column(
        db.Enum("low", "medium", "high", name="risk_level"), nullable=False, default="medium"
    )
    rationale = db.Column(db.Text, nullable=True)
    sparql_fragment = db.Column(db.Text, nullable=False)

    __table_args__ = (db.UniqueConstraint("scope_version_id", "rule_key"),)
