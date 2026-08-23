from ..extensions import db


class Language(db.Model):
    """A content language Duga actively tracks gaps for. Distinct from the
    interface languages in i18n/*.json (SPEC.md section 13: interface and
    content language are independent) -- this is the much larger, growing
    set of Wikimedia languages a topic's gap can be *about*. Only `seeded`
    rows are shown to visitors or touched by detectors."""

    __tablename__ = "language"

    code = db.Column(db.String(20), primary_key=True)
    autonym = db.Column(db.String(128), nullable=False)
    seeded = db.Column(db.Boolean, nullable=False, default=False)
    notes = db.Column(db.Text, nullable=True)


class Project(db.Model):
    """A Wikimedia project family a detector can target (wikipedia,
    wikidata, commons, wiktionary, ...)."""

    __tablename__ = "project"

    code = db.Column(db.String(32), primary_key=True)
    family = db.Column(db.String(32), nullable=False)
