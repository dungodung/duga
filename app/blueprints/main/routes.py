import json

from flask import Blueprint, abort, jsonify, render_template, request
from sqlalchemy import and_, exists

from ...extensions import db
from ...models import Detector, Gap, GapOverride, Language, ScopeRule, Topic, TopicRule

main_bp = Blueprint("main", __name__)

GAPS_PAGE_SIZE = 50


def _seeded_language_or_404(lang):
    language = Language.query.filter_by(code=lang, seeded=True).first()
    if language is None:
        abort(404)
    return language


def _visible_gaps_query(lang):
    """The base query every gap-list-facing view must use. SPEC.md S4: a
    suppressed topic is filtered out "at query time in every code path" --
    not just by the next detector run -- and guardrail 5: a human
    gap_override decision must actually hide the gap it overrides, since
    detectors never touch that table themselves. Both are enforced here,
    once, so no view can accidentally skip either."""
    suppressed_topic = exists().where(and_(Topic.qid == Gap.topic_qid, Topic.suppressed.is_(True)))
    overridden_gap = exists().where(
        and_(
            GapOverride.topic_qid == Gap.topic_qid,
            GapOverride.language_code == Gap.language_code,
            GapOverride.project_code == Gap.project_code,
            GapOverride.gap_type == Gap.gap_type,
        )
    )
    return Gap.query.filter(Gap.language_code == lang, ~suppressed_topic, ~overridden_gap)


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

    project_filter = request.args.get("project")
    if project_filter:
        query = query.filter(Gap.project_code == project_filter)

    type_filter = request.args.get("type")
    if type_filter:
        query = query.filter(Gap.gap_type == type_filter)

    page = max(request.args.get("page", 1, type=int) or 1, 1)
    total = query.count()
    rows = (
        query.order_by(Gap.computed_at.desc(), Gap.id.desc())
        .offset((page - 1) * GAPS_PAGE_SIZE)
        .limit(GAPS_PAGE_SIZE)
        .all()
    )

    detector_maturity = {d.detector_key: d.maturity for d in Detector.query.all()}

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
                "qid": row.topic_qid,
                "label": evidence.get("label") or row.topic_qid,
                "project_code": row.project_code,
                "gap_type": row.gap_type,
                "maturity": detector_maturity.get(row.detector_key, "experimental"),
                "action_url": row.action_url,
                "why_in_scope": rules_by_topic.get((row.scope_version_id, row.topic_qid), []),
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
    )


@main_bp.get("/about")
def about():
    return render_template("about.html")


@main_bp.get("/health")
def health():
    return jsonify(status="ok"), 200
