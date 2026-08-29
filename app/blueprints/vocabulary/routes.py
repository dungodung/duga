import re
from datetime import datetime, timezone

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func

from ... import i18n
from ...audit import log as audit_log
from ...attribution import public_name
from ...extensions import db
from ...models import Concept, Language, Term, TermAssertion, TermEvidence
from ...vocab_grading import recompute_evidence_grade
from ...wikidata_lookup import entity_exists
from ..auth.routes import current_contributor, login_required

vocab_bp = Blueprint("vocab", __name__)

VALID_REGISTERS = {"neutral", "clinical", "outdated", "slur", "reclaimed", "regional", "unknown"}
VALID_EVIDENCE_KINDS = {"publication", "style_guide", "dictionary", "law", "organisation", "other"}

# SPEC.md section 10's promotion path only ever *links* a local concept/term
# to something that already exists on Wikidata -- it never creates a new
# item or lexeme there (that's out of scope entirely: section 9's write
# allowlist is labels/descriptions/aliases now, lexemes/forms/senses
# "post-v0.1", and item creation is never listed at all).
QID_PATTERN = re.compile(r"^Q[1-9]\d*$")
LEXEME_PATTERN = re.compile(r"^L[1-9]\d*$")


def _t(key, *args):
    """Translates a flash message server-side -- flash() has no access to
    the Jinja context processor's _() at the point routes.py calls it."""
    return i18n.translate(key, g.get("interface_lang", i18n.FALLBACK_LANG), *args)


def _seeded_language_or_404(lang):
    language = Language.query.filter_by(code=lang, seeded=True).first()
    if language is None:
        abort(404)
    return language


def _visible_terms_query(lang=None):
    """SPEC.md S4: "A suppressed topic or term is filtered at query time in
    every code path" -- every vocabulary view goes through this."""
    query = Term.query.join(Concept, Concept.id == Term.concept_id).filter(
        Term.suppressed.is_(False), Concept.suppressed.is_(False)
    )
    if lang is not None:
        query = query.filter(Term.language_code == lang)
    return query


def _get_visible_term_or_404(term_id, lang=None):
    term = _visible_terms_query(lang).filter(Term.id == term_id).first()
    if term is None:
        abort(404)
    return term


@vocab_bp.get("/<lang>/vocabulary")
def list_terms(lang):
    language = _seeded_language_or_404(lang)
    terms = _visible_terms_query(lang).order_by(Term.written_form).all()
    concept_labels = [
        row[0]
        for row in db.session.query(Concept.local_label)
        .filter(Concept.suppressed.is_(False), Concept.local_label.isnot(None))
        .distinct()
        .all()
    ]
    return render_template(
        "vocabulary_list.html",
        language=language,
        terms=terms,
        concept_labels=concept_labels,
        registers=sorted(VALID_REGISTERS),
        # Prefill for the gap list's "add a word for this" link: a
        # missing-label gap is exactly the moment someone knows the local
        # word, and retyping the concept is the friction that loses them.
        # Display-only -- add_term still reads the submitted form field.
        prefill_concept=(request.args.get("concept") or "").strip(),
    )


@vocab_bp.post("/<lang>/vocabulary/add")
@login_required
def add_term(lang):
    language = _seeded_language_or_404(lang)
    contributor = current_contributor()

    concept_label = (request.form.get("concept_label") or "").strip()
    written_form = (request.form.get("written_form") or "").strip()
    register = request.form.get("register") or "unknown"
    usage_note = (request.form.get("usage_note") or "").strip() or None

    if not concept_label or not written_form:
        flash(_t("duga-vocab-add-error-required"))
        return redirect(url_for("vocab.list_terms", lang=lang))
    if register not in VALID_REGISTERS:
        register = "unknown"

    now = datetime.now(timezone.utc)
    concept = (
        Concept.query.filter(
            func.lower(Concept.local_label) == concept_label.lower(), Concept.suppressed.is_(False)
        )
        .first()
    )
    if concept is None:
        concept = Concept(local_label=concept_label, created_by=contributor.wiki_username, created_at=now)
        db.session.add(concept)
        db.session.flush()  # assigns concept.id

    existing = Term.query.filter_by(
        concept_id=concept.id, language_code=lang, written_form=written_form
    ).first()
    if existing is not None:
        flash(_t("duga-vocab-add-error-duplicate"))
        return redirect(url_for("vocab.term_detail", lang=lang, term_id=existing.id))

    term = Term(
        concept_id=concept.id,
        language_code=lang,
        written_form=written_form,
        register=register,
        usage_note=usage_note,
        lifecycle="local",
        evidence_grade="single_report",
        created_by=contributor.wiki_username,
        created_at=now,
        updated_at=now,
    )
    db.session.add(term)
    db.session.flush()  # assigns term.id

    audit_log(
        actor=contributor.wiki_username,
        action="create_term",
        entity_type="term",
        entity_id=term.id,
        before=None,
        after={"concept_id": concept.id, "language_code": lang, "written_form": written_form},
    )
    db.session.commit()
    flash(_t("duga-vocab-add-success"))
    return redirect(url_for("vocab.term_detail", lang=lang, term_id=term.id))


@vocab_bp.get("/<lang>/vocabulary/<int:term_id>")
def term_detail(lang, term_id):
    _seeded_language_or_404(lang)
    term = _get_visible_term_or_404(term_id, lang)
    contributor = current_contributor()

    my_assertion = None
    if contributor is not None:
        my_assertion = TermAssertion.query.filter_by(
            term_id=term.id, contributor=contributor.wiki_username
        ).first()

    agree_count = sum(1 for a in term.assertions if a.agrees)

    return render_template(
        "term_detail.html",
        language_code=lang,
        term=term,
        created_by_public=public_name(term.created_by),
        evidence=[
            {"row": e, "added_by_public": public_name(e.added_by)} for e in term.evidence
        ],
        agree_count=agree_count,
        my_assertion=my_assertion,
        evidence_kinds=sorted(VALID_EVIDENCE_KINDS),
        registers=sorted(VALID_REGISTERS),
    )


@vocab_bp.post("/term/<int:term_id>/evidence")
@login_required
def add_evidence(term_id):
    term = _get_visible_term_or_404(term_id)
    contributor = current_contributor()

    kind = request.form.get("kind")
    citation = (request.form.get("citation") or "").strip()
    url_value = (request.form.get("url") or "").strip() or None
    org_name = (request.form.get("org_name") or "").strip() or None
    year_raw = (request.form.get("year") or "").strip()
    year = int(year_raw) if year_raw.isdigit() else None

    if kind not in VALID_EVIDENCE_KINDS or not citation:
        flash(_t("duga-vocab-evidence-error-required"))
        return redirect(url_for("vocab.term_detail", lang=term.language_code, term_id=term.id))

    evidence = TermEvidence(
        term_id=term.id,
        kind=kind,
        citation=citation,
        url=url_value,
        org_name=org_name,
        year=year,
        added_by=contributor.wiki_username,
        added_at=datetime.now(timezone.utc),
    )
    db.session.add(evidence)
    db.session.flush()

    before_grade = term.evidence_grade
    new_grade = recompute_evidence_grade(term)
    term.updated_at = datetime.now(timezone.utc)

    audit_log(
        actor=contributor.wiki_username,
        action="add_term_evidence",
        entity_type="term",
        entity_id=term.id,
        before={"evidence_grade": before_grade},
        after={"evidence_grade": new_grade, "evidence_kind": kind},
    )
    db.session.commit()
    flash(_t("duga-vocab-evidence-success"))
    return redirect(url_for("vocab.term_detail", lang=term.language_code, term_id=term.id))


@vocab_bp.post("/term/<int:term_id>/assert")
@login_required
def assert_term(term_id):
    term = _get_visible_term_or_404(term_id)
    contributor = current_contributor()

    agrees = request.form.get("agrees") == "agree"
    register_asserted = request.form.get("register_asserted") or None
    if register_asserted not in VALID_REGISTERS:
        register_asserted = None
    note = (request.form.get("note") or "").strip() or None

    assertion = TermAssertion.query.filter_by(term_id=term.id, contributor=contributor.wiki_username).first()
    before = None
    if assertion is None:
        assertion = TermAssertion(term_id=term.id, contributor=contributor.wiki_username)
        db.session.add(assertion)
    else:
        before = {"agrees": assertion.agrees, "register_asserted": assertion.register_asserted}
    assertion.agrees = agrees
    assertion.register_asserted = register_asserted
    assertion.note = note
    assertion.created_at = datetime.now(timezone.utc)

    before_grade = term.evidence_grade
    new_grade = recompute_evidence_grade(term)
    term.updated_at = datetime.now(timezone.utc)

    audit_log(
        actor=contributor.wiki_username,
        action="assert_term",
        entity_type="term",
        entity_id=term.id,
        before=before or {"evidence_grade": before_grade},
        after={"agrees": agrees, "register_asserted": register_asserted, "evidence_grade": new_grade},
    )
    db.session.commit()
    flash(_t("duga-vocab-assert-success"))
    return redirect(url_for("vocab.term_detail", lang=term.language_code, term_id=term.id))


def _get_visible_concept_or_404(concept_id):
    concept = Concept.query.filter_by(id=concept_id, suppressed=False).first()
    if concept is None:
        abort(404)
    return concept


@vocab_bp.get("/concept/<int:concept_id>")
def concept_detail(concept_id):
    concept = _get_visible_concept_or_404(concept_id)
    terms = (
        Term.query.filter_by(concept_id=concept.id, suppressed=False)
        .order_by(Term.language_code, Term.written_form)
        .all()
    )
    autonyms = {row.code: row.autonym for row in Language.query.all()}
    return render_template(
        "concept_detail.html",
        concept=concept,
        terms=terms,
        autonyms=autonyms,
    )


# -- Promotion path (M7, SPEC.md section 10): local -> proposed -> upstream.
# Never creates anything on Wikidata -- only ever links to something that
# already exists there, verified live via wikidata_lookup.entity_exists()
# before the link is accepted.


@vocab_bp.post("/concept/<int:concept_id>/propose")
@login_required
def propose_concept(concept_id):
    concept = _get_visible_concept_or_404(concept_id)
    contributor = current_contributor()

    if concept.lifecycle != "local":
        flash(_t("duga-promote-error-not-local"))
        return redirect(url_for("vocab.concept_detail", concept_id=concept.id))

    concept.lifecycle = "proposed"
    audit_log(
        actor=contributor.wiki_username,
        action="propose_concept",
        entity_type="concept",
        entity_id=concept.id,
        before={"lifecycle": "local"},
        after={"lifecycle": "proposed"},
    )
    db.session.commit()
    flash(_t("duga-promote-proposed-success"))
    return redirect(url_for("vocab.concept_detail", concept_id=concept.id))


@vocab_bp.post("/concept/<int:concept_id>/link-upstream")
@login_required
def link_concept_upstream(concept_id):
    concept = _get_visible_concept_or_404(concept_id)
    contributor = current_contributor()

    if concept.lifecycle != "proposed":
        flash(_t("duga-promote-error-not-proposed"))
        return redirect(url_for("vocab.concept_detail", concept_id=concept.id))

    qid = (request.form.get("qid") or "").strip()
    if not QID_PATTERN.match(qid):
        flash(_t("duga-promote-error-bad-qid"))
        return redirect(url_for("vocab.concept_detail", concept_id=concept.id))
    if Concept.query.filter_by(qid=qid).first() is not None:
        flash(_t("duga-promote-error-qid-taken"))
        return redirect(url_for("vocab.concept_detail", concept_id=concept.id))
    if not entity_exists(current_app.config["DUGA_WIKIDATA_API"], qid, current_app.config["DUGA_USER_AGENT"]):
        flash(_t("duga-promote-error-not-found"))
        return redirect(url_for("vocab.concept_detail", concept_id=concept.id))

    before = {"lifecycle": "proposed", "qid": concept.qid}
    concept.qid = qid
    concept.lifecycle = "upstream"
    audit_log(
        actor=contributor.wiki_username,
        action="link_concept_upstream",
        entity_type="concept",
        entity_id=concept.id,
        before=before,
        after={"lifecycle": "upstream", "qid": qid},
    )
    db.session.commit()
    flash(_t("duga-promote-upstream-success"))
    return redirect(url_for("vocab.concept_detail", concept_id=concept.id))


@vocab_bp.post("/term/<int:term_id>/propose")
@login_required
def propose_term(term_id):
    term = _get_visible_term_or_404(term_id)
    contributor = current_contributor()

    if term.lifecycle != "local":
        flash(_t("duga-promote-error-not-local"))
        return redirect(url_for("vocab.term_detail", lang=term.language_code, term_id=term.id))

    term.lifecycle = "proposed"
    term.updated_at = datetime.now(timezone.utc)
    audit_log(
        actor=contributor.wiki_username,
        action="propose_term",
        entity_type="term",
        entity_id=term.id,
        before={"lifecycle": "local"},
        after={"lifecycle": "proposed"},
    )
    db.session.commit()
    flash(_t("duga-promote-proposed-success"))
    return redirect(url_for("vocab.term_detail", lang=term.language_code, term_id=term.id))


@vocab_bp.post("/term/<int:term_id>/link-upstream")
@login_required
def link_term_upstream(term_id):
    term = _get_visible_term_or_404(term_id)
    contributor = current_contributor()

    if term.lifecycle != "proposed":
        flash(_t("duga-promote-error-not-proposed"))
        return redirect(url_for("vocab.term_detail", lang=term.language_code, term_id=term.id))

    lexeme_id = (request.form.get("lexeme_id") or "").strip()
    sense_id = (request.form.get("sense_id") or "").strip() or None
    if not LEXEME_PATTERN.match(lexeme_id):
        flash(_t("duga-promote-error-bad-lexeme"))
        return redirect(url_for("vocab.term_detail", lang=term.language_code, term_id=term.id))
    if sense_id and not sense_id.startswith(f"{lexeme_id}-S"):
        flash(_t("duga-promote-error-bad-sense"))
        return redirect(url_for("vocab.term_detail", lang=term.language_code, term_id=term.id))
    if not entity_exists(current_app.config["DUGA_WIKIDATA_API"], lexeme_id, current_app.config["DUGA_USER_AGENT"]):
        flash(_t("duga-promote-error-not-found"))
        return redirect(url_for("vocab.term_detail", lang=term.language_code, term_id=term.id))

    before = {"lifecycle": "proposed", "lexeme_id": term.lexeme_id, "sense_id": term.sense_id}
    term.lexeme_id = lexeme_id
    term.sense_id = sense_id
    term.upstream_ref = sense_id or lexeme_id
    term.lifecycle = "upstream"
    term.updated_at = datetime.now(timezone.utc)
    audit_log(
        actor=contributor.wiki_username,
        action="link_term_upstream",
        entity_type="term",
        entity_id=term.id,
        before=before,
        after={"lifecycle": "upstream", "lexeme_id": lexeme_id, "sense_id": sense_id},
    )
    db.session.commit()
    flash(_t("duga-promote-upstream-success"))
    return redirect(url_for("vocab.term_detail", lang=term.language_code, term_id=term.id))


# -- Self-service suppression (SPEC.md S4). See the long note on
# app/blueprints/main/routes.py:suppress_topic() for why this is
# self-service, two-step, and one-way; concepts and terms follow the same
# shape. The one difference is where the reason goes: `topic` has
# suppressed_reason/_by/_at columns, but SPEC.md section 7 gives concept and
# term only a bare `suppressed` boolean, so the reason and actor are
# recorded in audit_log instead -- the same split scripts/
# suppress_vocabulary.py already makes.


def _suppress_vocabulary_row(row, kind, subject, action_url, redirect_endpoint, **redirect_args):
    """Shared GET-confirm / POST-act body for concept and term suppression."""
    if request.method == "GET":
        return render_template(
            "suppress_confirm.html", kind=kind, subject=subject, qid=None,
            action_url=action_url, lang=redirect_args.get("lang"),
        )

    reason = (request.form.get("reason") or "").strip()
    if not reason:
        flash(_t("duga-suppress-reason-required"))
        return redirect(action_url)

    contributor = current_contributor()
    row.suppressed = True
    audit_log(
        actor=contributor.wiki_username,
        action=f"suppress_{kind}",
        entity_type=kind,
        entity_id=row.id,
        before={"suppressed": False},
        after={"suppressed": True, "reason": reason},
    )
    db.session.commit()

    flash(_t("duga-suppress-success", subject))
    return redirect(url_for(redirect_endpoint, **redirect_args))


@vocab_bp.route("/term/<int:term_id>/suppress", methods=["GET", "POST"])
@login_required
def suppress_term(term_id):
    term = _get_visible_term_or_404(term_id)
    return _suppress_vocabulary_row(
        term, "term", term.written_form,
        url_for("vocab.suppress_term", term_id=term.id),
        "vocab.list_terms", lang=term.language_code,
    )


@vocab_bp.route("/concept/<int:concept_id>/suppress", methods=["GET", "POST"])
@login_required
def suppress_concept(concept_id):
    """Suppressing a concept also hides every term under it --
    _visible_terms_query() joins Concept and filters on both booleans -- so
    this is the broader of the two hammers. The confirmation page says so."""
    concept = _get_visible_concept_or_404(concept_id)
    return _suppress_vocabulary_row(
        concept, "concept", concept.local_label or _t("duga-vocab-concept-untitled"),
        url_for("vocab.suppress_concept", concept_id=concept.id),
        "main.home",
    )
