from ..extensions import db


class Concept(db.Model):
    """A cross-language notion a Term is a word for. Stays local (qid NULL)
    until promoted upstream to a real Wikidata lexeme/item (SPEC.md section
    10) -- that's M7, not this milestone."""

    __tablename__ = "concept"

    id = db.Column(db.Integer, primary_key=True)
    qid = db.Column(db.String(16), nullable=True, unique=True)
    local_label = db.Column(db.String(255), nullable=True)
    lifecycle = db.Column(
        db.Enum("local", "proposed", "upstream", name="concept_lifecycle"),
        nullable=False,
        default="local",
    )
    created_by = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False)
    suppressed = db.Column(db.Boolean, nullable=False, default=False)

    terms = db.relationship("Term", backref="concept", order_by="Term.language_code")


class Term(db.Model):
    """One written form of a Concept in one language. register/evidence_grade
    are about the *word itself* (is it neutral, clinical, a slur, etc), not
    about the concept -- the same concept can have very differently-graded
    terms across languages, which is the whole reason SPEC.md section 1
    treats vocabulary gaps as first-class alongside content gaps."""

    __tablename__ = "term"

    id = db.Column(db.Integer, primary_key=True)
    concept_id = db.Column(db.Integer, db.ForeignKey("concept.id"), nullable=False)
    language_code = db.Column(db.String(20), nullable=False)
    written_form = db.Column(db.String(255), nullable=False)
    lexeme_id = db.Column(db.String(16), nullable=True)
    sense_id = db.Column(db.String(24), nullable=True)
    register = db.Column(
        db.Enum(
            "neutral", "clinical", "outdated", "slur", "reclaimed", "regional", "unknown",
            name="term_register",
        ),
        nullable=False,
        default="unknown",
    )
    # Computed, not user-typed (SPEC.md section 8) -- see
    # app/vocab_grading.py:recompute_evidence_grade. Stored (not computed
    # purely at read time) so list views don't need a join+count per row.
    evidence_grade = db.Column(
        db.Enum("documented", "organisational", "community", "single_report", name="term_evidence_grade"),
        nullable=False,
        default="single_report",
    )
    lifecycle = db.Column(
        db.Enum("local", "proposed", "upstream", name="term_lifecycle"),
        nullable=False,
        default="local",
    )
    upstream_ref = db.Column(db.String(24), nullable=True)
    usage_note = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False)
    updated_at = db.Column(db.DateTime, nullable=False)
    suppressed = db.Column(db.Boolean, nullable=False, default=False)

    evidence = db.relationship("TermEvidence", backref="term", order_by="TermEvidence.added_at")
    assertions = db.relationship("TermAssertion", backref="term")

    __table_args__ = (
        db.UniqueConstraint("concept_id", "language_code", "written_form"),
        db.Index("ix_term_lang_register", "language_code", "register"),
    )


class TermEvidence(db.Model):
    """One citation supporting a Term's register/existence. `kind` in
    (publication, style_guide, dictionary, law) can justify a 'documented'
    evidence_grade; `organisation` can justify 'organisational'; `other` is
    recorded but doesn't move the grade on its own (SPEC.md section 8)."""

    __tablename__ = "term_evidence"

    id = db.Column(db.Integer, primary_key=True)
    term_id = db.Column(db.Integer, db.ForeignKey("term.id"), nullable=False)
    kind = db.Column(
        db.Enum("publication", "style_guide", "dictionary", "law", "organisation", "other", name="evidence_kind"),
        nullable=False,
    )
    citation = db.Column(db.Text, nullable=False)
    url = db.Column(db.Text, nullable=True)
    org_name = db.Column(db.String(255), nullable=True)
    year = db.Column(db.SmallInteger, nullable=True)
    added_by = db.Column(db.String(255), nullable=False)
    added_at = db.Column(db.DateTime, nullable=False)


class TermAssertion(db.Model):
    """One contributor's agree/disagree on a Term, feeding the 'community'
    evidence grade (SPEC.md section 8: computed from these rows, never
    typed in directly). One row per (term, contributor) -- asserting again
    updates the existing row rather than creating a second one, since a
    person can only have one current opinion."""

    __tablename__ = "term_assertion"

    id = db.Column(db.Integer, primary_key=True)
    term_id = db.Column(db.Integer, db.ForeignKey("term.id"), nullable=False)
    contributor = db.Column(db.String(255), nullable=False)
    agrees = db.Column(db.Boolean, nullable=False)
    register_asserted = db.Column(db.String(32), nullable=True)
    note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False)

    __table_args__ = (db.UniqueConstraint("term_id", "contributor"),)
