from ..extensions import db


class Topic(db.Model):
    """A Wikidata item Duga is tracking as in-scope. Rows persist even when a
    topic stops matching any active rule -- last_seen simply stops advancing
    -- so history/suppression survive scope churn (SPEC.md section 7)."""

    __tablename__ = "topic"

    qid = db.Column(db.String(16), primary_key=True)
    entity_class = db.Column(db.String(32), nullable=False)
    is_human = db.Column(db.Boolean, nullable=False, default=False)
    is_living = db.Column(db.Boolean, nullable=False, default=False)
    first_seen = db.Column(db.DateTime, nullable=False)
    last_seen = db.Column(db.DateTime, nullable=False)
    suppressed = db.Column(db.Boolean, nullable=False, default=False, index=True)
    suppressed_reason = db.Column(db.Text, nullable=True)
    suppressed_at = db.Column(db.DateTime, nullable=True)
    suppressed_by = db.Column(db.String(255), nullable=True)

    __table_args__ = (db.Index("ix_topic_is_living", "is_living"),)


class TopicRule(db.Model):
    """Which scope_rule(s), under which scope_version, currently match a
    topic. topic_refresh.py fully replaces the rows for the active
    scope_version_id on every run (SPEC.md guardrail 8: idempotent jobs) --
    it never touches rows from an inactive/superseded scope_version_id."""

    __tablename__ = "topic_rule"

    topic_qid = db.Column(db.String(16), db.ForeignKey("topic.qid"), primary_key=True)
    rule_key = db.Column(db.String(64), primary_key=True)
    scope_version_id = db.Column(db.Integer, primary_key=True)
