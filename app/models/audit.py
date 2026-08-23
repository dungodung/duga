from sqlalchemy.dialects import mysql

from ..extensions import db


class AuditLog(db.Model):
    """Every write Duga makes to its own state (contributor rows, later
    edit/override/suppression actions) gets one row here, before and after
    (SPEC.md guardrail 11). before_json/after_json hold whatever the
    calling code considers the relevant before/after state -- there is no
    fixed shape, since what's worth recording differs per action."""

    __tablename__ = "audit_log"

    id = db.Column(db.Integer().with_variant(mysql.BIGINT(), "mysql"), primary_key=True)
    actor = db.Column(db.String(255), nullable=False)
    action = db.Column(db.String(64), nullable=False)
    entity_type = db.Column(db.String(32), nullable=False)
    entity_id = db.Column(db.String(64), nullable=False)
    # MEDIUMTEXT on MySQL/MariaDB (matches SPEC.md section 7's DDL exactly);
    # plain TEXT elsewhere (e.g. SQLite in tests), which has no size cap.
    before_json = db.Column(db.Text().with_variant(mysql.MEDIUMTEXT(), "mysql"), nullable=True)
    after_json = db.Column(db.Text().with_variant(mysql.MEDIUMTEXT(), "mysql"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False)

    __table_args__ = (
        db.Index("ix_audit_log_entity", "entity_type", "entity_id"),
        db.Index("ix_audit_log_created_at", "created_at"),
    )
