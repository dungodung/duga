import json
from datetime import datetime, timezone

from flask import (
    Blueprint, Response, abort, flash, g, jsonify, redirect, render_template, request, url_for,
)
from markupsafe import escape
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
# Content languages this visitor has actually opened, most recent first --
# used only to lift them to the top of the picker. Distinct from
# i18n.INTERFACE_LANG_COOKIE, which is the language the *chrome* is in.
RECENT_LANGUAGE_COOKIE = "duga_recent_langs"
RECENT_LANGUAGE_LIMIT = 5
# What a gap row's maturity displays as when its detector_key has no
# `detector` row at all -- _visible_gaps_query() deliberately fails open on
# that case, so such gaps are listed and have to be labelled something. The
# maturity filter has to agree with the label the row visibly carries, or
# filtering by what you can read on screen would silently drop rows.
UNREGISTERED_MATURITY = "experimental"
# Gap types where inviting a local word makes sense: the topic has no name
# in this language yet, which is the one thing a speaker of it can supply
# from their own head. Not offered on people (see human_qids below) -- "add
# a word for this person" is not a coherent request.
VOCABULARY_INVITING_GAP_TYPES = {"no_label", "no_description"}


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
    """Language picker. Three things constrain how this can be built:

    SPEC.md S6 forbids any view that ranks languages against each other,
    "implicitly (e.g. sorting languages by gap count)" included -- so no
    counts here, and no ordering derived from size. Alphabetical by autonym
    is the neutral choice, and stays neutral as the list grows.

    A flat list of every tracked language stops working somewhere past a
    couple of dozen, so the ones a visitor is most likely to want are
    lifted out first: their browser's own Accept-Language, plus any
    language they have already been reading. That is a convenience, never a
    filter -- the complete list is always right there underneath.

    The search box is a plain GET form that filters server-side, so it
    works with JavaScript off (SPEC.md section 12); enhance.js only makes
    it filter as you type."""
    languages = Language.query.filter_by(seeded=True).all()
    languages.sort(key=lambda language: language.autonym.lower())

    query = (request.args.get("q") or "").strip()
    if query:
        needle = query.lower()
        languages = [
            language
            for language in languages
            if needle in language.autonym.lower() or needle in language.code.lower()
        ]

    seeded_codes = {language.code for language in languages}
    suggested_codes = []
    for code in _preferred_language_codes():
        if code in seeded_codes and code not in suggested_codes:
            suggested_codes.append(code)
    by_code = {language.code: language for language in languages}
    suggested = [by_code[code] for code in suggested_codes]

    return render_template(
        "index.html",
        languages=languages,
        suggested=suggested,
        query=query,
        total_languages=Language.query.filter_by(seeded=True).count(),
    )


def _remember_language(lang):
    """Records the content language being browsed so the picker can offer
    it next time. Deferred to an after_request hook because a view has no
    response object to set a cookie on yet."""
    g.remember_language = lang


def _preferred_language_codes():
    """Best guess at which tracked languages this visitor actually reads:
    the last content language they looked at, then their browser's
    Accept-Language, in the browser's own order of preference. Never
    inferred from anything about *them* -- only from what their client
    volunteers and what they have already clicked."""
    codes = []
    recent = request.cookies.get(RECENT_LANGUAGE_COOKIE)
    if recent:
        codes.extend(code for code in recent.split(",") if code)
    codes.extend(code for code, _quality in request.accept_languages)
    # "sr-Latn"/"pt-BR" style tags also imply their base language.
    expanded = []
    for code in codes:
        expanded.append(code)
        if "-" in code:
            expanded.append(code.split("-", 1)[0])
    return expanded


@main_bp.get("/<lang>/")
def lang_home(lang):
    language = _seeded_language_or_404(lang)
    _remember_language(lang)

    detectors = Detector.query.all()
    gap_counts = (
        _visible_gaps_query(lang)
        .with_entities(Gap.project_code, Gap.gap_type, db.func.count(Gap.id))
        .group_by(Gap.project_code, Gap.gap_type)
        .all()
    )
    total_gaps = sum(count for *_rest, count in gap_counts)

    # The GROUP BY above used to be collapsed straight into that sum and
    # discarded. Passing it through turns this page into the way into the
    # gap list: every row links to itself, pre-filtered, which is also how
    # the ?project=/?type= filters get discovered at all.
    breakdown = sorted(
        (
            {"project_code": project_code, "gap_type": gap_type, "count": count}
            for project_code, gap_type, count in gap_counts
        ),
        key=lambda row: -row["count"],
    )

    return render_template(
        "lang_home.html",
        language=language,
        detectors=detectors,
        total_gaps=total_gaps,
        breakdown=breakdown,
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

    # Which of these topics are people. A local word for a *concept* is a
    # useful thing to invite; "add a word for this person" is not, so the
    # vocabulary cross-link below is offered only for non-human topics.
    human_qids = {
        qid
        for (qid,) in Topic.query.with_entities(Topic.qid)
        .filter(Topic.qid.in_(topic_qids), Topic.is_human.is_(True))
        .all()
    } if topic_qids else set()

    items = []
    for row in rows:
        evidence = json.loads(row.evidence_json) if row.evidence_json else {}
        items.append(
            {
                "id": row.id,
                "qid": row.topic_qid,
                "label": evidence.get("label") or row.topic_qid,
                # Which language that label is actually in -- detectors
                # record it because a request for `sr` can come back in
                # English, and wd_no_label's label is English by
                # construction. Absent on rows written before detectors
                # started storing it; the template then emits no `lang`
                # attribute rather than guessing.
                "label_lang": evidence.get("label_lang"),
                "is_human": row.topic_qid in human_qids,
                "project_code": row.project_code,
                "gap_type": row.gap_type,
                "maturity": detector_maturity.get(row.detector_key, UNREGISTERED_MATURITY),
                "action_url": row.action_url,
                "why_in_scope": rules_by_topic.get((row.scope_version_id, row.topic_qid), []),
                "editable": row.project_code == "wikidata" and row.gap_type in EDITABLE_GAP_TYPES,
                "vocabulary_url": (
                    url_for(
                        "vocab.list_terms",
                        lang=row.language_code,
                        concept=evidence.get("label") or row.topic_qid,
                    )
                    if row.gap_type in VOCABULARY_INVITING_GAP_TYPES and row.topic_qid not in human_qids
                    else None
                ),
            }
        )

    return render_template(
        "gaps.html",
        language=language,
        items=items,
        page=page,
        total=total,
        page_size=GAPS_PAGE_SIZE,
        showing_from=(page - 1) * GAPS_PAGE_SIZE + 1 if items else 0,
        showing_to=(page - 1) * GAPS_PAGE_SIZE + len(items),
        page_count=max(-(-total // GAPS_PAGE_SIZE), 1),
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


@main_bp.get("/topic/<qid>")
def topic_detail(qid):
    """One topic, all its gaps, across every tracked language.

    The gap list answers "what is missing in Serbian"; this answers "what
    is missing about this topic anywhere", which is the view you want
    before deciding a topic doesn't belong at all. It is also the right
    home for suppression: the gap list used to repeat the suppress link on
    every one of its fifty rows, next to two override buttons, which is a
    lot of destructive affordance for an action that applies to the topic
    as a whole rather than to the row it was clicked from.

    A suppressed topic 404s here exactly as its gaps vanish everywhere
    else (SPEC.md S4, filtered at query time in every code path)."""
    topic = Topic.query.filter_by(qid=qid, suppressed=False).first()
    if topic is None:
        abort(404)

    rows = (
        _visible_gaps_query()
        .filter(Gap.topic_qid == qid)
        .order_by(Gap.language_code, Gap.project_code, Gap.gap_type)
        .all()
    )

    detector_maturity = {d.detector_key: d.maturity for d in Detector.query.all()}
    autonyms = {row.code: row.autonym for row in Language.query.filter_by(seeded=True).all()}

    label = None
    label_lang = None
    by_language = {}
    for row in rows:
        evidence = json.loads(row.evidence_json) if row.evidence_json else {}
        if label is None and evidence.get("label"):
            label, label_lang = evidence["label"], evidence.get("label_lang")
        by_language.setdefault(row.language_code, []).append(
            {
                "project_code": row.project_code,
                "gap_type": row.gap_type,
                "maturity": detector_maturity.get(row.detector_key, UNREGISTERED_MATURITY),
                "action_url": row.action_url,
            }
        )

    languages = [
        {"code": code, "autonym": autonyms.get(code, code), "gaps": gaps}
        for code, gaps in sorted(by_language.items(), key=lambda item: autonyms.get(item[0], item[0]))
    ]

    scope_version_ids = {row.scope_version_id for row in rows}
    why_in_scope = []
    if scope_version_ids:
        rule_labels = {
            (rule.scope_version_id, rule.rule_key): rule.label
            for rule in ScopeRule.query.filter(ScopeRule.scope_version_id.in_(scope_version_ids)).all()
        }
        for tr in TopicRule.query.filter(
            TopicRule.topic_qid == qid, TopicRule.scope_version_id.in_(scope_version_ids)
        ).all():
            why_in_scope.append(rule_labels.get((tr.scope_version_id, tr.rule_key), tr.rule_key))

    return render_template(
        "topic_detail.html",
        topic=topic,
        label=label or qid,
        label_lang=label_lang,
        languages=languages,
        gap_count=len(rows),
        why_in_scope=sorted(set(why_in_scope)),
    )


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


@main_bp.get("/robots.txt")
def robots_txt():
    """What crawlers may index. Two separate reasons to disallow things:

    Safety -- /<lang>/gaps and /topic/<qid> concentrate real people's names
    under a queer-topics heading. Those topics are already public on
    Wikidata (S2 requires a sourced reference before anything is even in
    scope), but a crawlable, paginated index of them is a new artefact that
    Duga would be creating rather than reflecting. Guardrail 12: when in
    doubt about a sensitive display decision, show less. The pages stay
    fully public and linkable; they just aren't gathered up by search
    engines.

    Waste -- /login, /oauth/, /account and the write forms are
    per-visitor or transactional and index to nothing useful.

    The overview pages that explain the project stay open, so Duga is
    findable by name."""
    lines = [
        "User-agent: *",
        "Disallow: /gaps",
        "Disallow: /topic/",
        "Disallow: /login",
        "Disallow: /logout",
        "Disallow: /oauth/",
        "Disallow: /account",
        "Disallow: /gap/",
        "Disallow: /term/",
        "Allow: /$",
        "Allow: /about",
        f"Sitemap: {url_for('main.sitemap_xml', _external=True)}",
    ]
    # /<lang>/gaps sits under a language prefix, so it needs one rule per
    # tracked language rather than a single path prefix.
    for language in Language.query.filter_by(seeded=True).order_by(Language.code).all():
        lines.insert(1, f"Disallow: /{language.code}/gaps")
    return Response("\n".join(lines) + "\n", mimetype="text/plain")


@main_bp.get("/sitemap.xml")
def sitemap_xml():
    """Only the pages robots.txt actually invites in: the landing page,
    /about, and one overview per tracked language. Deliberately not the gap
    lists (see robots_txt) and not one entry per topic."""
    urls = [url_for("main.home", _external=True), url_for("main.about", _external=True)]
    for language in Language.query.filter_by(seeded=True).order_by(Language.code).all():
        urls.append(url_for("main.lang_home", lang=language.code, _external=True))
        urls.append(url_for("vocab.list_terms", lang=language.code, _external=True))

    body = ["<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
            "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">"]
    for url in urls:
        body.append(f"  <url><loc>{escape(url)}</loc></url>")
    body.append("</urlset>")
    return Response("\n".join(body) + "\n", mimetype="application/xml")


@main_bp.get("/health")
def health():
    return jsonify(status="ok"), 200
