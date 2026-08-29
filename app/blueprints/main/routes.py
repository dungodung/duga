import json
from datetime import datetime, timezone

from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for
from sqlalchemy import and_, exists, or_

from ... import i18n
from ...audit import log as audit_log
from ...extensions import db
from ...models import Detector, Gap, GapOverride, Language, ScopeRule, Topic, TopicRule
from ...wikidata_write import EDITABLE_GAP_TYPES
from ..auth.routes import current_contributor, login_required

main_bp = Blueprint("main", __name__)

GAPS_PAGE_SIZE = 50
OVERRIDE_STATUSES = {"declined", "not_applicable"}
GAP_MATURITIES = ("stable", "beta", "experimental")
# What a gap row's maturity displays as when its detector_key has no
# `detector` row at all -- _visible_gaps_query() deliberately fails open on
# that case, so such gaps are listed and have to be labelled something. The
# maturity filter has to agree with the label the row visibly carries, or
# filtering by what you can read on screen would silently drop rows.
UNREGISTERED_MATURITY = "experimental"


def _t(key, *args):
    """Translates a flash message server-side -- flash() has no access to
    the Jinja context processor's _() at the point routes.py calls it."""
    return i18n.translate(key, g.get("interface_lang", i18n.FALLBACK_LANG), *args)


def _seeded_language_or_404(lang):
    language = Language.query.filter_by(code=lang, seeded=True).first()
    if language is None:
        abort(404)
    return language


def _visible_gaps_query(lang=None):
    """The base query every gap-list-facing view must use. SPEC.md S4: a
    suppressed topic is filtered out "at query time in every code path" --
    not just by the next detector run -- and guardrail 5: a human
    gap_override decision must actually hide the gap it overrides, since
    detectors never touch that table themselves. Both are enforced here,
    once, so no view can accidentally skip either.

    `lang=None` (used by app/blueprints/write/routes.py, which looks a gap
    up by id alone) applies the suppression/override filters without a
    language filter -- omitting the language_code condition entirely,
    not filtering for a null one, which would match nothing.

    Also hides gaps from a detector explicitly marked disabled (SPEC.md
    section 11: post-v0.1 detectors ship disabled by default). This fails
    open -- a gap only disappears when a `detector` row exists AND says
    enabled=False -- so gaps seeded without a matching detector row (as
    plenty of tests do) are unaffected."""
    suppressed_topic = exists().where(and_(Topic.qid == Gap.topic_qid, Topic.suppressed.is_(True)))
    overridden_gap = exists().where(
        and_(
            GapOverride.topic_qid == Gap.topic_qid,
            GapOverride.language_code == Gap.language_code,
            GapOverride.project_code == Gap.project_code,
            GapOverride.gap_type == Gap.gap_type,
        )
    )
    disabled_detector = exists().where(
        and_(Detector.detector_key == Gap.detector_key, Detector.enabled.is_(False))
    )
    query = Gap.query.filter(~suppressed_topic, ~overridden_gap, ~disabled_detector)
    if lang is not None:
        query = query.filter(Gap.language_code == lang)
    return query


@main_bp.get("/")
def home():
    languages = Language.query.filter_by(seeded=True).order_by(Language.code).all()
    return render_template("index.html", languages=languages)


@main_bp.get("/<lang>/")
def lang_home(lang):
    language = _seeded_language_or_404(lang)

    detectors = Detector.query.all()
    gap_counts = (
        _visible_gaps_query(lang)
        .with_entities(Gap.project_code, Gap.gap_type, db.func.count(Gap.id))
        .group_by(Gap.project_code, Gap.gap_type)
        .all()
    )
    total_gaps = sum(count for *_rest, count in gap_counts)

    return render_template(
        "lang_home.html",
        language=language,
        detectors=detectors,
        total_gaps=total_gaps,
        has_any_detector_run=any(d.last_run_at for d in detectors),
    )


@main_bp.get("/<lang>/gaps")
def gaps(lang):
    language = _seeded_language_or_404(lang)

    query = _visible_gaps_query(lang)

    # Filter options come from the *unfiltered* visible list for this
    # language, so the form can never offer a choice that returns nothing
    # and -- more importantly -- filtering into an empty result still
    # leaves every option on screen to get back out with.
    project_options = sorted(row[0] for row in query.with_entities(Gap.project_code).distinct())
    type_options = sorted(row[0] for row in query.with_entities(Gap.gap_type).distinct())

    project_filter = request.args.get("project")
    if project_filter:
        query = query.filter(Gap.project_code == project_filter)

    type_filter = request.args.get("type")
    if type_filter:
        query = query.filter(Gap.gap_type == type_filter)

    # SPEC.md section 12: the gap list is "filterable by project/type/
    # maturity". Maturity lives on `detector`, not on `gap`, so this is an
    # EXISTS against the detector row rather than a column comparison. An
    # unrecognised value matches no detector and so returns nothing, the
    # same way an unrecognised project or type already does.
    maturity_filter = request.args.get("maturity")
    if maturity_filter:
        has_maturity = exists().where(
            and_(Detector.detector_key == Gap.detector_key, Detector.maturity == maturity_filter)
        )
        if maturity_filter == UNREGISTERED_MATURITY:
            unregistered = ~exists().where(Detector.detector_key == Gap.detector_key)
            query = query.filter(or_(has_maturity, unregistered))
        else:
            query = query.filter(has_maturity)

    page = max(request.args.get("page", 1, type=int) or 1, 1)
    total = query.count()
    rows = (
        # Impact scoring (SPEC.md S6: ranks topics *within* a language,
        # never languages against each other -- see jobs/impact_score.py)
        # sorts highest-reach topics first within this one already
        # language-filtered list; NULLS-last via the boolean ordering
        # trick below (portable across SQLite/MariaDB, unlike NULLS LAST
        # syntax) so unscored topics fall back to the original
        # recency-based order rather than sinking in an arbitrary way.
        query.order_by(
            Gap.impact_score.is_(None), Gap.impact_score.desc(), Gap.computed_at.desc(), Gap.id.desc()
        )
        .offset((page - 1) * GAPS_PAGE_SIZE)
        .limit(GAPS_PAGE_SIZE)
        .all()
    )

    detectors = Detector.query.all()
    detector_maturity = {d.detector_key: d.maturity for d in detectors}

    # SPEC.md section 11's detector contract: "a failed detector shows as
    # stale in the UI rather than silently serving old data as current".
    # The gap list is where that old data actually gets served, so the
    # warning belongs here and not only on the language overview. Only
    # detectors that have actually run can have served anything stale, and
    # a disabled detector's gaps are already hidden by
    # _visible_gaps_query(), so neither is worth warning about.
    stale_detectors = [
        d for d in detectors if d.enabled and d.last_run_at is not None and d.last_status != "ok"
    ]

    scope_version_ids = {row.scope_version_id for row in rows}
    topic_qids = {row.topic_qid for row in rows}
    topic_rules = []
    if scope_version_ids and topic_qids:
        topic_rules = TopicRule.query.filter(
            TopicRule.scope_version_id.in_(scope_version_ids),
            TopicRule.topic_qid.in_(topic_qids),
        ).all()
    rule_labels = {}
    if scope_version_ids:
        for rule in ScopeRule.query.filter(ScopeRule.scope_version_id.in_(scope_version_ids)).all():
            rule_labels[(rule.scope_version_id, rule.rule_key)] = rule.label
    rules_by_topic = {}
    for tr in topic_rules:
        rules_by_topic.setdefault((tr.scope_version_id, tr.topic_qid), []).append(
            rule_labels.get((tr.scope_version_id, tr.rule_key), tr.rule_key)
        )

    items = []
    for row in rows:
        evidence = json.loads(row.evidence_json) if row.evidence_json else {}
        items.append(
            {
                "id": row.id,
                "qid": row.topic_qid,
                "label": evidence.get("label") or row.topic_qid,
                "project_code": row.project_code,
                "gap_type": row.gap_type,
                "maturity": detector_maturity.get(row.detector_key, UNREGISTERED_MATURITY),
                "action_url": row.action_url,
                "why_in_scope": rules_by_topic.get((row.scope_version_id, row.topic_qid), []),
                "editable": row.project_code == "wikidata" and row.gap_type in EDITABLE_GAP_TYPES,
            }
        )

    return render_template(
        "gaps.html",
        language=language,
        items=items,
        page=page,
        total=total,
        page_size=GAPS_PAGE_SIZE,
        has_next=page * GAPS_PAGE_SIZE < total,
        project_filter=project_filter,
        type_filter=type_filter,
        maturity_filter=maturity_filter,
        project_options=project_options,
        type_options=type_options,
        maturity_options=GAP_MATURITIES,
        stale_detectors=stale_detectors,
    )


@main_bp.post("/gap/override")
@login_required
def override_gap():
    """SPEC.md section 12's `POST /gap/override` -- a contributor's own
    "this doesn't need fixing" decision, distinct from M6's write path
    (which resolves a gap by actually fixing it). Only declined/
    not_applicable are self-service; 'done' stays operator-only
    (scripts/set_gap_override.py), since M6 already marks a gap done by
    fixing and removing it directly. Guardrail 5: this only ever touches
    `gap_override`, never `gap` itself -- a detector's next run can't
    destroy this decision, and can't be destroyed by one either."""
    contributor = current_contributor()
    gap_id = request.form.get("gap_id", type=int)
    status = request.form.get("status")
    reason = (request.form.get("reason") or "").strip() or None

    if status not in OVERRIDE_STATUSES:
        abort(400)

    gap = _visible_gaps_query().filter(Gap.id == gap_id).first()
    if gap is None:
        abort(404)

    existing = GapOverride.query.filter_by(
        topic_qid=gap.topic_qid,
        language_code=gap.language_code,
        project_code=gap.project_code,
        gap_type=gap.gap_type,
    ).first()
    if existing is None:
        existing = GapOverride(
            topic_qid=gap.topic_qid,
            language_code=gap.language_code,
            project_code=gap.project_code,
            gap_type=gap.gap_type,
        )
        db.session.add(existing)
    existing.status = status
    existing.reason = reason
    existing.set_by = contributor.wiki_username
    existing.set_at = datetime.now(timezone.utc)

    audit_log(
        actor=contributor.wiki_username,
        action="override_gap",
        entity_type="gap",
        entity_id=gap.id,
        before=None,
        after={
            "status": status,
            "topic_qid": gap.topic_qid,
            "language_code": gap.language_code,
            "project_code": gap.project_code,
            "gap_type": gap.gap_type,
            "reason": reason,
        },
    )
    db.session.commit()

    flash(_t("duga-gaps-override-success"))
    return redirect(url_for("main.gaps", lang=gap.language_code))


def _redirect_lang(default_endpoint="main.home"):
    """Where to send someone after a suppression. The subject they were
    looking at is gone from every list by the time we redirect, so we go
    back to the list they came from -- carried as an explicit `lang` field
    rather than trusting Referer, and validated as a seeded language so it
    can't be turned into an open redirect."""
    lang = request.values.get("lang")
    if lang and Language.query.filter_by(code=lang, seeded=True).first() is not None:
        return lang
    return None


def _topic_label(qid):
    """Best available human-readable name for a topic: detectors already
    store one in gap.evidence_json, so a suppression confirmation page can
    say "Marsha P. Johnson" instead of just "Q18916". Falls back to the
    qid, exactly like the gap list does."""
    row = Gap.query.filter(Gap.topic_qid == qid, Gap.evidence_json.isnot(None)).first()
    if row is not None:
        try:
            label = json.loads(row.evidence_json).get("label")
        except ValueError:
            label = None
        if label:
            return label
    return qid


@main_bp.route("/topic/<qid>/suppress", methods=["GET", "POST"])
@login_required
def suppress_topic(qid):
    """Self-service topic suppression (SPEC.md S4). Suppression is the
    tool's safety valve -- "absolute and immediate... no upstream edit and
    no justification beyond a logged reason" -- and routing it through an
    operator's CLI put a human round-trip in front of the one action that
    most needs to be fast. Any logged-in contributor can do it, the same
    bar as POST /gap/override.

    Deliberately one-way: there is no self-service un-suppress, only
    scripts/suppress_topic.py --unsuppress. Making a topic reappear is a
    decision that should cost more than making it disappear.

    Two steps (GET confirm, POST act) rather than a button in the gap list,
    because this hides the topic in every language for everyone, not just
    the row it was clicked from -- that deserves to be read before it is
    done, and it matches the preview/confirm shape every write path uses."""
    topic = Topic.query.filter_by(qid=qid, suppressed=False).first()
    if topic is None:
        abort(404)

    label = _topic_label(qid)
    lang = _redirect_lang()

    if request.method == "GET":
        return render_template(
            "suppress_confirm.html", kind="topic", subject=label, qid=qid,
            action_url=url_for("main.suppress_topic", qid=qid), lang=lang,
        )

    reason = (request.form.get("reason") or "").strip()
    if not reason:
        flash(_t("duga-suppress-reason-required"))
        return redirect(url_for("main.suppress_topic", qid=qid, lang=lang))

    contributor = current_contributor()
    topic.suppressed = True
    topic.suppressed_reason = reason
    topic.suppressed_by = contributor.wiki_username
    topic.suppressed_at = datetime.now(timezone.utc)
    audit_log(
        actor=contributor.wiki_username,
        action="suppress_topic",
        entity_type="topic",
        entity_id=qid,
        before={"suppressed": False},
        after={"suppressed": True, "reason": reason},
    )
    db.session.commit()

    flash(_t("duga-suppress-success", label))
    if lang:
        return redirect(url_for("main.gaps", lang=lang))
    return redirect(url_for("main.home"))


@main_bp.get("/about")
def about():
    return render_template("about.html")


@main_bp.get("/health")
def health():
    return jsonify(status="ok"), 200
