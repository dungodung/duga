from sqlalchemy.dialects import mysql

from ..extensions import db


class Detector(db.Model):
    """One gap-detector job's self-reported identity and health. Each
    detector job upserts its own row (by detector_key) on every run and
    updates last_run_at/last_status -- SPEC.md guardrail 9: a failed
    detector must show as stale in the UI, never silently serve old gap
    rows as though they were current."""

    __tablename__ = "detector"

    id = db.Column(db.Integer, primary_key=True)
    detector_key = db.Column(db.String(64), nullable=False, unique=True)
    project_code = db.Column(db.String(32), nullable=False)
    gap_type = db.Column(db.String(64), nullable=False)
    maturity = db.Column(
        db.Enum("stable", "beta", "experimental", name="detector_maturity"),
        nullable=False,
        default="experimental",
    )
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    description = db.Column(db.Text, nullable=True)
    last_run_at = db.Column(db.DateTime, nullable=True)
    last_status = db.Column(db.String(32), nullable=True)


class Gap(db.Model):
    """One missing-thing record: SPEC.md's unifying (topic, language,
    project, gap_type, evidence, action, status) shape. Detector jobs may
    freely DELETE/INSERT here; they must never touch gap_override (SPEC.md
    guardrail 5) -- that table doesn't exist yet (M3)."""

    __tablename__ = "gap"

    # BIGINT on MySQL/MariaDB (matches SPEC.md section 7's DDL exactly); on
    # SQLite (tests), only a literal INTEGER PRIMARY KEY gets autoincrement
    # rowid behaviour -- BigInteger there silently breaks id generation.
    id = db.Column(db.Integer().with_variant(mysql.BIGINT(), "mysql"), primary_key=True)
    topic_qid = db.Column(db.String(16), nullable=False)
    language_code = db.Column(db.String(20), nullable=False)
    project_code = db.Column(db.String(32), nullable=False)
    gap_type = db.Column(db.String(64), nullable=False)
    detector_key = db.Column(db.String(64), nullable=False)
    scope_version_id = db.Column(db.Integer, nullable=False)
    evidence_json = db.Column(db.Text, nullable=True)
    action_url = db.Column(db.Text, nullable=True)
    impact_score = db.Column(db.Numeric(10, 4), nullable=True)
    computed_at = db.Column(db.DateTime, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("topic_qid", "language_code", "project_code", "gap_type"),
        db.Index("ix_gap_lang_project_type", "language_code", "project_code", "gap_type"),
        db.Index("ix_gap_impact_score", "impact_score"),
    )
