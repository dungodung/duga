"""The one place in Duga that writes to Wikidata (SPEC.md section 9, S1,
S8). Every write here:
  1. checks the global kill switch immediately before the request (S8) --
     not cached, not checked earlier in the flow, read fresh right before
     the Wikidata API call
  2. shows an exact preview and requires a second, explicit confirmation
     before anything is written (same request path handles both: no
     "confirmed" field renders the preview, "confirmed=1" performs the write)
  3. uses an edit summary naming Duga and linking to the tool
     (app/wikidata_write.py:edit_summary)
  4. logs to wiki_edit and audit_log before and after (guardrail 11) -- a
     wiki_edit row is created with status='pending' before the API call, so
     a crash mid-write still leaves a record something was attempted
  5. is rate-limited, per-user and globally (SPEC.md section 9)

Only labels and descriptions can be written -- see
app/wikidata_write.py's module docstring for why that's structural, not
just a runtime check.
"""
import json
from datetime import datetime, timedelta, timezone

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for

from ... import i18n
from ...audit import log as audit_log
from ...extensions import db
from ...models import Gap, WikiEdit
from ...token_store import TokenUnavailable, get_valid_access_token
from ...wikidata_write import (
    EDITABLE_GAP_TYPES,
    WikidataWriteError,
    add_sense,
    edit_summary,
    set_description,
    set_label,
)
from ..auth.routes import current_contributor, login_required
from ..main.routes import _visible_gaps_query
from ..vocabulary.routes import _get_visible_term_or_404

write_bp = Blueprint("write", __name__)

WRITE_FUNCTIONS = {"label": set_label, "description": set_description}


def _t(key, *args):
    return i18n.translate(key, g.get("interface_lang", i18n.FALLBACK_LANG), *args)


def _editable_gap_or_404(gap_id):
    """Only a currently-visible wikidata no_label/no_description gap can be
    edited -- reuses the exact same suppression/override filter the gap
    list itself uses (SPEC.md S4), so a suppressed or overridden gap can't
    be edited via a stale link any more than it can be seen."""
    gap = (
        _visible_gaps_query()
        .filter(Gap.id == gap_id, Gap.project_code == "wikidata")
        .first()
    )
    if gap is None or gap.gap_type not in EDITABLE_GAP_TYPES:
        abort(404)
    return gap


def _gap_evidence_label(gap):
    evidence = json.loads(gap.evidence_json) if gap.evidence_json else {}
    return evidence.get("label") or gap.topic_qid


def _english_reference(gap):
    """The English label/description Wikidata already holds, for someone
    writing the missing one in another language. Both are recorded by
    wd_no_label/wd_no_description at detection time, so rendering this
    costs no API call -- the web side never talks to the Wikidata API to
    draw a page.

    The label is dropped when it is the same string already shown as the
    heading (which is the normal case for a missing *label*, where the
    English one is all we had to display in the first place), so the
    reference block adds information rather than repeating it.

    Returns {} for gaps detected before this was recorded; the template
    then shows nothing rather than a half-empty box. Detectors rewrite
    their rows nightly, so it fills in on its own."""
    evidence = json.loads(gap.evidence_json) if gap.evidence_json else {}
    label = evidence.get("label_en") or (
        evidence.get("label") if evidence.get("label_lang") == "en" else None
    )
    if label == _gap_evidence_label(gap):
        label = None
    description = evidence.get("description_en")
    if not label and not description:
        return {}
    return {"label": label, "description": description}


def _term_awaiting_sense_or_404(term_id):
    """Lexeme write-back (SPEC.md section 9: "Wikidata Lexemes, Forms,
    Senses (post-v0.1)") is only offered for a term that M7's promotion
    path already linked to an existing Lexeme but not yet to any specific
    Sense there -- reached via propose_term + link_term_upstream in
    app/blueprints/vocabulary/routes.py. Once term.sense_id is set (either
    entered directly at link time, or by a previous run through this
    flow), there's nothing left to add here."""
    term = _get_visible_term_or_404(term_id)
    if term.lifecycle != "upstream" or not term.lexeme_id or term.sense_id:
        abort(404)
    return term


def _rate_limited(contributor_username):
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    per_user = WikiEdit.query.filter(WikiEdit.contributor == contributor_username, WikiEdit.created_at >= since).count()
    if per_user >= current_app.config["DUGA_MAX_WRITES_PER_HOUR_PER_USER"]:
        return True
    total = WikiEdit.query.filter(WikiEdit.created_at >= since).count()
    return total >= current_app.config["DUGA_MAX_WRITES_PER_HOUR_GLOBAL"]


@write_bp.get("/gap/<int:gap_id>/edit")
@login_required
def edit_form(gap_id):
    gap = _editable_gap_or_404(gap_id)
    return render_template(
        "gap_edit.html",
        gap=gap,
        edit_kind=EDITABLE_GAP_TYPES[gap.gap_type],
        label=_gap_evidence_label(gap),
        english=_english_reference(gap),
        value="",
        confirming=False,
    )


@write_bp.post("/gap/<int:gap_id>/edit")
@login_required
def edit_submit(gap_id):
    gap = _editable_gap_or_404(gap_id)
    edit_kind = EDITABLE_GAP_TYPES[gap.gap_type]
    contributor = current_contributor()
    value = (request.form.get("value") or "").strip()
    confirmed = request.form.get("confirmed") == "1"

    if not value:
        flash(_t("duga-write-error-required"))
        return redirect(url_for("write.edit_form", gap_id=gap_id))

    if not confirmed:
        # Step 1 of 2: show the exact preview. Nothing is written yet --
        # no DB row, no Wikidata call (SPEC.md section 9, requirement 2).
        return render_template(
            "gap_edit.html",
            gap=gap,
            edit_kind=edit_kind,
            label=_gap_evidence_label(gap),
            english=_english_reference(gap),
            value=value,
            confirming=True,
        )

    # --- Step 2 of 2: the person has seen the preview and confirmed. ---

    if not current_app.config["DUGA_WRITES_ENABLED"]:  # S8, checked here, not earlier
        flash(_t("duga-write-error-disabled"))
        return redirect(url_for("main.gaps", lang=gap.language_code))

    if _rate_limited(contributor.wiki_username):
        flash(_t("duga-write-error-rate-limited"))
        return redirect(url_for("main.gaps", lang=gap.language_code))

    try:
        access_token = get_valid_access_token(contributor.id)
    except TokenUnavailable:
        flash(_t("duga-write-error-relogin"))
        return redirect(url_for("auth.login", next=url_for("write.edit_form", gap_id=gap_id)))

    wiki_edit = WikiEdit(
        contributor=contributor.wiki_username,
        target_wiki="wikidata",
        target_entity=gap.topic_qid,
        edit_kind=edit_kind,
        summary=edit_summary(edit_kind),
        status="pending",
        created_at=datetime.now(timezone.utc),
    )
    db.session.add(wiki_edit)
    db.session.flush()  # assigns wiki_edit.id
    audit_log(
        actor=contributor.wiki_username,
        action="wiki_edit_attempt",
        entity_type="wiki_edit",
        entity_id=wiki_edit.id,
        before=None,
        after={"target_entity": gap.topic_qid, "edit_kind": edit_kind, "value": value},
    )
    db.session.commit()

    write_fn = WRITE_FUNCTIONS[edit_kind]
    try:
        revid, _summary = write_fn(
            current_app.config["DUGA_WIKIDATA_API"],
            access_token,
            gap.topic_qid,
            gap.language_code,
            value,
            current_app.config["DUGA_USER_AGENT"],
        )
    except WikidataWriteError as exc:
        wiki_edit.status = "failed"
        wiki_edit.error = str(exc)
        audit_log(
            actor=contributor.wiki_username,
            action="wiki_edit_failed",
            entity_type="wiki_edit",
            entity_id=wiki_edit.id,
            before={"status": "pending"},
            after={"status": "failed", "error": str(exc)},
        )
        db.session.commit()
        flash(_t("duga-write-error-failed", str(exc)))
        return redirect(url_for("main.gaps", lang=gap.language_code))

    wiki_edit.status = "success"
    wiki_edit.revid = revid
    # The gap is resolved -- the next detector run would drop it anyway
    # (SPEC.md guardrail 8), but removing it now means the person sees it
    # actually disappear rather than wondering if the edit "really" worked.
    Gap.query.filter_by(id=gap.id).delete()
    audit_log(
        actor=contributor.wiki_username,
        action="wiki_edit_success",
        entity_type="wiki_edit",
        entity_id=wiki_edit.id,
        before={"status": "pending"},
        after={"status": "success", "revid": revid},
    )
    db.session.commit()

    flash(_t("duga-write-success"))
    return redirect(url_for("main.gaps", lang=gap.language_code))


@write_bp.get("/term/<int:term_id>/add-sense")
@login_required
def add_sense_form(term_id):
    term = _term_awaiting_sense_or_404(term_id)
    return render_template(
        "term_add_sense.html",
        term=term,
        gloss=term.usage_note or "",
        confirming=False,
    )


@write_bp.post("/term/<int:term_id>/add-sense")
@login_required
def add_sense_submit(term_id):
    term = _term_awaiting_sense_or_404(term_id)
    contributor = current_contributor()
    gloss = (request.form.get("gloss") or "").strip()
    confirmed = request.form.get("confirmed") == "1"

    if not gloss:
        flash(_t("duga-write-error-required"))
        return redirect(url_for("write.add_sense_form", term_id=term_id))

    if not confirmed:
        # Step 1 of 2: show the exact preview. Nothing is written yet.
        return render_template("term_add_sense.html", term=term, gloss=gloss, confirming=True)

    # --- Step 2 of 2: the person has seen the preview and confirmed. ---

    if not current_app.config["DUGA_WRITES_ENABLED"]:  # S8, checked here, not earlier
        flash(_t("duga-write-error-disabled"))
        return redirect(url_for("vocab.term_detail", lang=term.language_code, term_id=term.id))

    if _rate_limited(contributor.wiki_username):
        flash(_t("duga-write-error-rate-limited"))
        return redirect(url_for("vocab.term_detail", lang=term.language_code, term_id=term.id))

    try:
        access_token = get_valid_access_token(contributor.id)
    except TokenUnavailable:
        flash(_t("duga-write-error-relogin"))
        return redirect(url_for("auth.login", next=url_for("write.add_sense_form", term_id=term_id)))

    wiki_edit = WikiEdit(
        contributor=contributor.wiki_username,
        target_wiki="wikidata",
        target_entity=term.lexeme_id,
        edit_kind="sense",
        summary=edit_summary("sense"),
        status="pending",
        created_at=datetime.now(timezone.utc),
    )
    db.session.add(wiki_edit)
    db.session.flush()  # assigns wiki_edit.id
    audit_log(
        actor=contributor.wiki_username,
        action="wiki_edit_attempt",
        entity_type="wiki_edit",
        entity_id=wiki_edit.id,
        before=None,
        after={"target_entity": term.lexeme_id, "edit_kind": "sense", "gloss": gloss, "term_id": term.id},
    )
    db.session.commit()

    try:
        sense_id, revid, _summary = add_sense(
            current_app.config["DUGA_WIKIDATA_API"],
            access_token,
            term.lexeme_id,
            term.language_code,
            gloss,
            current_app.config["DUGA_USER_AGENT"],
        )
    except WikidataWriteError as exc:
        wiki_edit.status = "failed"
        wiki_edit.error = str(exc)
        audit_log(
            actor=contributor.wiki_username,
            action="wiki_edit_failed",
            entity_type="wiki_edit",
            entity_id=wiki_edit.id,
            before={"status": "pending"},
            after={"status": "failed", "error": str(exc)},
        )
        db.session.commit()
        flash(_t("duga-write-error-failed", str(exc)))
        return redirect(url_for("vocab.term_detail", lang=term.language_code, term_id=term.id))

    wiki_edit.status = "success"
    wiki_edit.revid = revid
    before = {"sense_id": term.sense_id, "upstream_ref": term.upstream_ref}
    term.sense_id = sense_id
    # Now that a real Sense exists, it's the more specific reference --
    # same preference link_term_upstream itself gives sense_id over
    # lexeme_id when computing upstream_ref.
    term.upstream_ref = sense_id
    term.updated_at = datetime.now(timezone.utc)
    audit_log(
        actor=contributor.wiki_username,
        action="wiki_edit_success",
        entity_type="wiki_edit",
        entity_id=wiki_edit.id,
        before={"status": "pending"},
        after={"status": "success", "revid": revid, "sense_id": sense_id},
    )
    audit_log(
        actor=contributor.wiki_username,
        action="link_term_sense",
        entity_type="term",
        entity_id=term.id,
        before=before,
        after={"sense_id": sense_id, "upstream_ref": sense_id},
    )
    db.session.commit()

    flash(_t("duga-write-sense-success"))
    return redirect(url_for("vocab.term_detail", lang=term.language_code, term_id=term.id))
