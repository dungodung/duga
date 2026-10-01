from datetime import datetime, timezone

from app.extensions import db
from app.blueprints.main.routes import PICKER_COLLAPSE_MIN
from app.models import Detector, Gap, GapOverride, Topic


def test_home_lists_seeded_content_languages(client, seed_languages):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Français".encode() in resp.data
    assert "Српски".encode() in resp.data
    # English is an interface language, not a seeded content language.
    assert b'href="/en/"' not in resp.data


def test_lang_home_renders_for_known_language(client, seed_languages):
    resp = client.get("/fr/")
    assert resp.status_code == 200
    assert "Duga en Français".encode() in resp.data


def test_lang_home_404s_for_unknown_language(client, seed_languages):
    resp = client.get("/xx/")
    assert resp.status_code == 404


def test_lang_home_404s_for_language_not_seeded(client, db, seed_languages):
    from app.models import Language

    db.session.add(Language(code="de", autonym="Deutsch", seeded=False))
    db.session.commit()
    resp = client.get("/de/")
    assert resp.status_code == 404


def test_lang_home_defaults_interface_language_to_content_language(client, seed_languages):
    resp = client.get("/sr/")
    assert resp.status_code == 200
    assert b'lang="sr"' in resp.data


def test_uselang_query_param_overrides_content_language_default(client, seed_languages):
    resp = client.get("/sr/?uselang=fr")
    assert resp.status_code == 200
    assert b'lang="fr"' in resp.data


def test_uselang_choice_persists_via_cookie(client, seed_languages):
    client.get("/?uselang=fr")
    resp = client.get("/")
    assert b'lang="fr"' in resp.data


def test_lang_home_shows_placeholder_before_any_detector_run(client, seed_languages):
    resp = client.get("/sr/?uselang=en")
    assert resp.status_code == 200
    assert b"live yet" in resp.data


def test_lang_home_shows_gap_count_and_link_after_a_run(client, db, seed_languages):
    now = datetime.now(timezone.utc)
    db.session.add(
        Detector(
            detector_key="wp_no_article",
            project_code="wikipedia",
            gap_type="no_article",
            maturity="stable",
            last_run_at=now,
            last_status="ok",
        )
    )
    db.session.add(
        Gap(
            topic_qid="Q1",
            language_code="sr",
            project_code="wikipedia",
            gap_type="no_article",
            detector_key="wp_no_article",
            scope_version_id=1,
            evidence_json='{"label": "Test Topic"}',
            action_url="https://www.wikidata.org/wiki/Q1#sitelinks-wikipedia",
            computed_at=now,
        )
    )
    db.session.commit()

    resp = client.get("/sr/?uselang=en")
    assert resp.status_code == 200
    assert b"1 gaps" in resp.data
    assert b'href="/sr/gaps"' in resp.data


def test_lang_home_shows_stale_notice_when_detector_failed(client, db, seed_languages):
    db.session.add(
        Detector(
            detector_key="wp_no_article",
            project_code="wikipedia",
            gap_type="no_article",
            maturity="stable",
            last_run_at=datetime.now(timezone.utc),
            last_status="error",
        )
    )
    db.session.commit()
    resp = client.get("/sr/?uselang=en")
    assert b"may be stale" in resp.data


def test_gaps_page_lists_topic_with_label_and_action(client, db, seed_languages):
    now = datetime.now(timezone.utc)
    db.session.add(
        Gap(
            topic_qid="Q1",
            language_code="sr",
            project_code="wikipedia",
            gap_type="no_article",
            detector_key="wp_no_article",
            scope_version_id=1,
            evidence_json='{"label": "Marsha P. Johnson"}',
            action_url="https://www.wikidata.org/wiki/Q1#sitelinks-wikipedia",
            computed_at=now,
        )
    )
    db.session.commit()

    resp = client.get("/sr/gaps")
    assert resp.status_code == 200
    assert b"Marsha P. Johnson" in resp.data
    assert b"sitelinks-wikipedia" in resp.data


def test_gaps_page_falls_back_to_qid_without_a_label(client, db, seed_languages):
    now = datetime.now(timezone.utc)
    db.session.add(
        Gap(
            topic_qid="Q999",
            language_code="sr",
            project_code="wikipedia",
            gap_type="no_article",
            detector_key="wp_no_article",
            scope_version_id=1,
            evidence_json='{"label": null}',
            action_url="https://www.wikidata.org/wiki/Q999#sitelinks-wikipedia",
            computed_at=now,
        )
    )
    db.session.commit()

    resp = client.get("/sr/gaps")
    assert b"Q999" in resp.data


def test_gaps_page_hides_gaps_for_a_suppressed_topic(client, db, seed_languages):
    now = datetime.now(timezone.utc)
    db.session.add(
        Topic(
            qid="Q1",
            entity_class="human",
            is_human=True,
            is_living=True,
            first_seen=now,
            last_seen=now,
            suppressed=True,
            suppressed_reason="operator decision",
            suppressed_by="dungodung",
            suppressed_at=now,
        )
    )
    db.session.add(
        Gap(
            topic_qid="Q1",
            language_code="sr",
            project_code="wikipedia",
            gap_type="no_article",
            detector_key="wp_no_article",
            scope_version_id=1,
            evidence_json='{"label": "Suppressed Person"}',
            action_url="https://www.wikidata.org/wiki/Q1#sitelinks-wikipedia",
            computed_at=now,
        )
    )
    db.session.commit()

    resp = client.get("/sr/gaps")
    assert b"Suppressed Person" not in resp.data


def test_gaps_page_hides_gaps_from_a_disabled_detector(client, db, seed_languages):
    now = datetime.now(timezone.utc)
    db.session.add(
        Detector(
            detector_key="wiktionary_no_entry",
            project_code="wiktionary",
            gap_type="no_entry",
            maturity="experimental",
            enabled=False,
        )
    )
    db.session.add(
        Gap(
            topic_qid="Q1",
            language_code="sr",
            project_code="wiktionary",
            gap_type="no_entry",
            detector_key="wiktionary_no_entry",
            scope_version_id=1,
            evidence_json='{"label": "Disabled Detector Topic"}',
            action_url="https://www.wikidata.org/wiki/Q1#sitelinks-wiktionary",
            computed_at=now,
        )
    )
    db.session.commit()

    resp = client.get("/sr/gaps")
    assert b"Disabled Detector Topic" not in resp.data


def test_gaps_page_shows_gaps_with_no_matching_detector_row(client, db, seed_languages):
    """A gap seeded without a matching detector row (as most tests here
    do) must still show -- the disabled-detector filter fails open."""
    now = datetime.now(timezone.utc)
    db.session.add(
        Gap(
            topic_qid="Q1",
            language_code="sr",
            project_code="wiktionary",
            gap_type="no_entry",
            detector_key="wiktionary_no_entry",
            scope_version_id=1,
            evidence_json='{"label": "No Detector Row Topic"}',
            action_url="https://www.wikidata.org/wiki/Q1#sitelinks-wiktionary",
            computed_at=now,
        )
    )
    db.session.commit()

    resp = client.get("/sr/gaps")
    assert b"No Detector Row Topic" in resp.data


def test_lang_home_gap_count_excludes_suppressed_topics(client, db, seed_languages):
    now = datetime.now(timezone.utc)
    db.session.add(
        Topic(
            qid="Q1", entity_class="human", is_human=True, is_living=True,
            first_seen=now, last_seen=now, suppressed=True,
        )
    )
    db.session.add(
        Gap(
            topic_qid="Q1", language_code="sr", project_code="wikipedia", gap_type="no_article",
            detector_key="wp_no_article", scope_version_id=1, evidence_json="{}",
            action_url="https://www.wikidata.org/wiki/Q1#sitelinks-wikipedia", computed_at=now,
        )
    )
    db.session.commit()

    resp = client.get("/sr/?uselang=en")
    assert b"gaps found so far" not in resp.data


def test_gaps_page_hides_a_gap_with_any_override_status(client, db, seed_languages):
    now = datetime.now(timezone.utc)
    db.session.add(
        Gap(
            topic_qid="Q1",
            language_code="sr",
            project_code="wikipedia",
            gap_type="no_article",
            detector_key="wp_no_article",
            scope_version_id=1,
            evidence_json='{"label": "Overridden Person"}',
            action_url="https://www.wikidata.org/wiki/Q1#sitelinks-wikipedia",
            computed_at=now,
        )
    )
    db.session.add(
        GapOverride(
            topic_qid="Q1",
            language_code="sr",
            project_code="wikipedia",
            gap_type="no_article",
            status="not_applicable",
            reason="test",
            set_by="dungodung",
            set_at=now,
        )
    )
    db.session.commit()

    resp = client.get("/sr/gaps")
    assert b"Overridden Person" not in resp.data


def test_gaps_page_override_is_specific_to_its_own_gap_type(client, db, seed_languages):
    """An override on (Q1, sr, wikipedia, no_article) must not hide an
    unrelated gap for the same topic under a different gap_type."""
    now = datetime.now(timezone.utc)
    db.session.add(
        Gap(
            topic_qid="Q1",
            language_code="sr",
            project_code="wikidata",
            gap_type="no_label",
            detector_key="wd_no_label",
            scope_version_id=1,
            evidence_json='{"label": "Still Visible"}',
            action_url="https://www.wikidata.org/wiki/Q1#labels",
            computed_at=now,
        )
    )
    db.session.add(
        GapOverride(
            topic_qid="Q1",
            language_code="sr",
            project_code="wikipedia",
            gap_type="no_article",
            status="done",
            set_by="dungodung",
            set_at=now,
        )
    )
    db.session.commit()

    resp = client.get("/sr/gaps")
    assert b"Still Visible" in resp.data


def test_gaps_page_empty_state(client, seed_languages):
    resp = client.get("/fr/gaps?uselang=en")
    assert resp.status_code == 200
    assert b"No gaps match" in resp.data


def test_gaps_page_404s_for_unseeded_language(client, seed_languages):
    resp = client.get("/xx/gaps")
    assert resp.status_code == 404


def test_gaps_page_paginates(client, db, seed_languages):
    now = datetime.now(timezone.utc)
    for i in range(60):
        db.session.add(
            Gap(
                topic_qid=f"Q{i}",
                language_code="sr",
                project_code="wikipedia",
                gap_type="no_article",
                detector_key="wp_no_article",
                scope_version_id=1,
                evidence_json=f'{{"label": "Topic {i}"}}',
                action_url=f"https://www.wikidata.org/wiki/Q{i}#sitelinks-wikipedia",
                computed_at=now,
            )
        )
    db.session.commit()

    page1 = client.get("/sr/gaps?uselang=en")
    assert page1.status_code == 200
    assert b"Next page" in page1.data

    page2 = client.get("/sr/gaps?page=2&uselang=en")
    assert page2.status_code == 200
    assert b"Previous page" in page2.data


def test_gaps_page_orders_by_impact_score_then_falls_back_to_recency(client, db, seed_languages):
    now = datetime.now(timezone.utc)
    db.session.add_all(
        [
            Gap(
                topic_qid="Q1", language_code="sr", project_code="wikipedia", gap_type="no_article",
                detector_key="wp_no_article", scope_version_id=1, evidence_json='{"label": "Low impact"}',
                action_url="https://example.org/1", computed_at=now, impact_score=5,
            ),
            Gap(
                topic_qid="Q2", language_code="sr", project_code="wikipedia", gap_type="no_article",
                detector_key="wp_no_article", scope_version_id=1, evidence_json='{"label": "High impact"}',
                action_url="https://example.org/2", computed_at=now, impact_score=90,
            ),
            Gap(
                topic_qid="Q3", language_code="sr", project_code="wikipedia", gap_type="no_article",
                detector_key="wp_no_article", scope_version_id=1, evidence_json='{"label": "Unscored"}',
                action_url="https://example.org/3", computed_at=now, impact_score=None,
            ),
        ]
    )
    db.session.commit()

    resp = client.get("/sr/gaps?uselang=en")
    body = resp.data.decode()
    # Highest impact_score first, then lower, then the unscored gap last
    # (NULLs-last, not sorted arbitrarily) -- SPEC.md S6: this only ever
    # reorders topics within this one already language-filtered list.
    assert body.index("High impact") < body.index("Low impact") < body.index("Unscored")


def _gap(qid, label, *, project="wikipedia", gap_type="no_article", detector_key="wp_no_article", lang="sr"):
    return Gap(
        topic_qid=qid, language_code=lang, project_code=project, gap_type=gap_type,
        detector_key=detector_key, scope_version_id=1, evidence_json=f'{{"label": "{label}"}}',
        action_url=f"https://www.wikidata.org/wiki/{qid}", computed_at=datetime.now(timezone.utc),
    )


def test_gaps_page_filters_by_detector_maturity(client, db, seed_languages):
    """SPEC.md section 12: the gap list is filterable by project/type/
    maturity. Maturity lives on the detector, not on the gap row."""
    db.session.add_all(
        [
            Detector(detector_key="wp_no_article", project_code="wikipedia", gap_type="no_article", maturity="stable"),
            Detector(detector_key="commons_no_image", project_code="commons", gap_type="no_image", maturity="experimental"),
            _gap("Q1", "Stable Topic"),
            _gap("Q2", "Experimental Topic", project="commons", gap_type="no_image", detector_key="commons_no_image"),
        ]
    )
    db.session.commit()

    stable = client.get("/sr/gaps?maturity=stable")
    assert b"Stable Topic" in stable.data
    assert b"Experimental Topic" not in stable.data

    experimental = client.get("/sr/gaps?maturity=experimental")
    assert b"Experimental Topic" in experimental.data
    assert b"Stable Topic" not in experimental.data


def test_gaps_maturity_filter_includes_a_gap_with_no_detector_row(client, db, seed_languages):
    """A gap whose detector has no row is *displayed* as experimental, so
    filtering for experimental has to return it -- otherwise the filter
    would hide a row by the very label it shows."""
    db.session.add(_gap("Q1", "No Detector Row Topic"))
    db.session.commit()

    assert b"No Detector Row Topic" in client.get("/sr/gaps?maturity=experimental").data
    assert b"No Detector Row Topic" not in client.get("/sr/gaps?maturity=stable").data


def test_gaps_unknown_maturity_filter_matches_nothing(client, db, seed_languages):
    db.session.add_all(
        [
            Detector(detector_key="wp_no_article", project_code="wikipedia", gap_type="no_article", maturity="stable"),
            _gap("Q1", "Stable Topic"),
        ]
    )
    db.session.commit()

    resp = client.get("/sr/gaps?maturity=nonsense&uselang=en")
    assert resp.status_code == 200
    assert b"Stable Topic" not in resp.data
    assert b"No gaps match" in resp.data


def test_gaps_filter_form_offers_present_projects_and_keeps_the_selection(client, db, seed_languages):
    db.session.add_all([_gap("Q1", "Article Topic"), _gap("Q2", "Label Topic", project="wikidata", gap_type="no_label")])
    db.session.commit()

    resp = client.get("/sr/gaps?project=wikidata&uselang=en")
    assert b'<option value="wikidata" selected>' in resp.data
    assert b'<option value="wikipedia">' in resp.data
    # Nothing in this language has a Wiktionary gap, so it isn't offered.
    assert b'value="wiktionary"' not in resp.data
    # ...but every option stays on screen while a filter is applied, so a
    # visitor who filters into an empty list can always get back out.
    assert b'<option value="stable">' in resp.data


def test_gaps_filter_form_is_still_shown_when_a_filter_matches_nothing(client, db, seed_languages):
    db.session.add(_gap("Q1", "Article Topic"))
    db.session.commit()

    resp = client.get("/sr/gaps?project=wikidata&uselang=en")
    assert b"No gaps match" in resp.data
    assert b'<option value="wikipedia">' in resp.data


def test_gaps_filters_survive_pagination(client, db, seed_languages):
    db.session.add_all(_gap(f"Q{i}", f"Topic {i}") for i in range(60))
    db.session.commit()

    page1 = client.get("/sr/gaps?maturity=experimental&project=wikipedia&uselang=en")
    assert b"Next page" in page1.data
    assert b"maturity=experimental" in page1.data
    assert b"project=wikipedia" in page1.data

    page2 = client.get("/sr/gaps?page=2&maturity=experimental&project=wikipedia&uselang=en")
    assert b"Previous page" in page2.data
    assert b"maturity=experimental" in page2.data


def test_gaps_page_warns_that_a_failed_detector_is_stale(client, db, seed_languages):
    """SPEC.md section 11: a failed detector shows as stale in the UI
    rather than silently serving old data as current -- and the gap list
    is where that old data actually gets served."""
    db.session.add_all(
        [
            Detector(
                detector_key="wp_no_article", project_code="wikipedia", gap_type="no_article",
                maturity="stable", enabled=True,
                last_run_at=datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc), last_status="error",
            ),
            _gap("Q1", "Possibly Stale Topic"),
        ]
    )
    db.session.commit()

    resp = client.get("/sr/gaps?uselang=en")
    assert b"may be out of date" in resp.data
    assert b"2026-03-01 12:00 UTC" in resp.data
    # The warning names the affected detector, so it's clear which rows
    # it applies to.
    stale_notice = resp.data.split(b'class="notice notice-stale"')[1].split(b"</p>")[0]
    assert b"Wikipedia" in stale_notice
    assert b"no article yet" in stale_notice


def test_gaps_page_does_not_warn_about_a_healthy_or_never_run_detector(client, db, seed_languages):
    db.session.add_all(
        [
            Detector(
                detector_key="wp_no_article", project_code="wikipedia", gap_type="no_article",
                maturity="stable", enabled=True,
                last_run_at=datetime.now(timezone.utc), last_status="ok",
            ),
            # Never run: it can't have served anything stale yet.
            Detector(
                detector_key="wd_no_label", project_code="wikidata", gap_type="no_label",
                maturity="stable", enabled=True,
            ),
            _gap("Q1", "Fresh Topic"),
        ]
    )
    db.session.commit()

    resp = client.get("/sr/gaps?uselang=en")
    assert b"Fresh Topic" in resp.data
    assert b"may be out of date" not in resp.data


def test_gaps_page_does_not_warn_about_a_failed_but_disabled_detector(client, db, seed_languages):
    """A disabled detector's gaps are already hidden entirely, so there's
    nothing stale on screen to warn about."""
    db.session.add_all(
        [
            Detector(
                detector_key="commons_no_image", project_code="commons", gap_type="no_image",
                maturity="experimental", enabled=False,
                last_run_at=datetime.now(timezone.utc), last_status="error",
            ),
            _gap("Q1", "Fresh Topic"),
        ]
    )
    db.session.commit()

    resp = client.get("/sr/gaps?uselang=en")
    assert b"Fresh Topic" in resp.data
    assert b"may be out of date" not in resp.data


def _topic_row(qid, is_human=False):
    now = datetime.now(timezone.utc)
    return Topic(qid=qid, entity_class="human" if is_human else "concept", is_human=is_human,
                 is_living=False, first_seen=now, last_seen=now)


def test_gaps_page_says_where_you_are_in_a_long_list(client, db, seed_languages):
    """50 rows out of tens of thousands, with only prev/next, gave no way
    to tell how many results there were or whether a filter did anything."""
    db.session.add_all(_gap(f"Q{i}", f"Topic {i}") for i in range(60))
    db.session.commit()

    page1 = client.get("/sr/gaps?uselang=en")
    assert b"Showing 1\xe2\x80\x9350 of 60." in page1.data.replace(b"\xe2\x80\x93", b"\xe2\x80\x93")
    assert b"Page 1 of 2" in page1.data

    page2 = client.get("/sr/gaps?page=2&uselang=en")
    assert b"of 60." in page2.data
    assert b"Page 2 of 2" in page2.data


def test_gaps_page_count_reflects_the_active_filter(client, db, seed_languages):
    db.session.add_all([_gap("Q1", "Article Topic"), _gap("Q2", "Label Topic", project="wikidata", gap_type="no_label")])
    db.session.commit()

    assert b"of 2." in client.get("/sr/gaps?uselang=en").data
    assert b"of 1." in client.get("/sr/gaps?project=wikidata&uselang=en").data


def test_gaps_page_marks_the_label_with_the_language_it_is_actually_in(client, db, seed_languages):
    """A label requested in sr can come back in English, and wd_no_label's
    label is English by construction -- so the detectors record which, and
    the page must not assert the content language over an English string."""
    now = datetime.now(timezone.utc)
    db.session.add_all(
        [
            Gap(topic_qid="Q1", language_code="sr", project_code="wikidata", gap_type="no_label",
                detector_key="wd_no_label", scope_version_id=1,
                evidence_json='{"label": "Marsha P. Johnson", "label_lang": "en"}',
                action_url="https://example.org/1", computed_at=now),
            Gap(topic_qid="Q2", language_code="sr", project_code="wikipedia", gap_type="no_article",
                detector_key="wp_no_article", scope_version_id=1,
                evidence_json='{"label": "\u0440\u043e\u0434\u043d\u043e \u043a\u0432\u0438\u0440", "label_lang": "sr"}',
                action_url="https://example.org/2", computed_at=now),
        ]
    )
    db.session.commit()

    body = client.get("/sr/gaps?uselang=en").data.decode()
    assert '<div class="gap-label" lang="en"><a href="/topic/Q1">Marsha P. Johnson</a>' in body
    assert '<div class="gap-label" lang="sr"><a href="/topic/Q2">родно квир</a>' in body


def test_gaps_page_omits_the_lang_attribute_when_the_label_language_is_unknown(client, db, seed_languages):
    """Rows written before detectors recorded label_lang: guess nothing."""
    db.session.add(_gap("Q1", "Unknown Provenance"))
    db.session.commit()

    body = client.get("/sr/gaps?uselang=en").data.decode()
    assert '<div class="gap-label"><a href="/topic/Q1">Unknown Provenance</a>' in body


def test_gaps_page_invites_a_local_word_only_where_it_makes_sense(client, db, seed_languages):
    """A missing label on a concept is an invitation to supply the local
    word. On a person it is not a coherent request, and on a missing
    article it is the wrong fix."""
    db.session.add_all(
        [
            _topic_row("Q1", is_human=False),
            _topic_row("Q2", is_human=True),
            _gap("Q1", "genderqueer", project="wikidata", gap_type="no_label", detector_key="wd_no_label"),
            _gap("Q2", "A Person", project="wikidata", gap_type="no_label", detector_key="wd_no_label"),
            _gap("Q1", "genderqueer"),  # no_article on the same concept
        ]
    )
    db.session.commit()

    body = client.get("/sr/gaps?uselang=en").data.decode()
    assert "/sr/vocabulary?concept=genderqueer" in body
    assert "concept=A+Person" not in body
    # Exactly one invitation: the label gap, not the article gap.
    assert body.count("Add a word for this") == 1


def test_lang_home_breaks_the_count_down_by_project_and_type(client, db, seed_languages):
    """The GROUP BY was already being run and thrown into a sum."""
    db.session.add_all(
        [
            # The overview only shows anything once a detector has run.
            Detector(detector_key="wp_no_article", project_code="wikipedia", gap_type="no_article",
                     maturity="stable", last_run_at=datetime.now(timezone.utc), last_status="ok"),
            _gap("Q1", "A"), _gap("Q2", "B"),
            _gap("Q3", "C", project="wikidata", gap_type="no_label", detector_key="wd_no_label"),
        ]
    )
    db.session.commit()

    body = client.get("/sr/?uselang=en").data.decode()
    assert "What&#39;s missing" in body
    # Each row links into the gap list, pre-filtered to itself.
    assert "/sr/gaps?project=wikipedia&amp;type=no_article" in body
    assert "/sr/gaps?project=wikidata&amp;type=no_label" in body
    # Ordered by count, biggest first.
    assert body.index("project=wikipedia") < body.index("project=wikidata")


def test_about_page_renders(client):
    resp = client.get("/about")
    assert resp.status_code == 200
    assert b"AGPL-3.0" in resp.data


def test_unknown_route_renders_translated_404(client):
    # A single path segment without a trailing slash first 308s to try it as
    # a /<lang>/ candidate (Flask's normal strict_slashes behaviour) before
    # 404ing -- follow that redirect rather than special-casing the route.
    resp = client.get("/this-page-does-not-exist", follow_redirects=True)
    assert resp.status_code == 404
    assert b"Page not found" in resp.data


def test_unknown_multi_segment_route_404s_directly(client):
    resp = client.get("/no/such/page")
    assert resp.status_code == 404
    assert b"Page not found" in resp.data


# -- per-topic page ----------------------------------------------------------


def test_topic_page_gathers_every_language(client, db, seed_languages):
    db.session.add_all(
        [
            _topic_row("Q1"),
            _gap("Q1", "genderqueer", lang="sr"),
            _gap("Q1", "genderqueer", lang="fr"),
            _gap("Q1", "genderqueer", lang="sr", project="wikidata", gap_type="no_label", detector_key="wd_no_label"),
        ]
    )
    db.session.commit()

    resp = client.get("/topic/Q1?uselang=en")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "3 things missing, across 2 language(s)." in body
    assert "Српски" in body and "Français" in body
    assert "/sr/gaps" in body and "/fr/gaps" in body


def test_topic_page_is_never_indexed(client, db, seed_languages):
    """Everything Duga knows about one topic in one place is exactly the
    concentration guardrail 12 says to show less of -- doubly so for a
    living person."""
    db.session.add_all([_topic_row("Q1"), _gap("Q1", "Someone")])
    db.session.commit()

    assert b'<meta name="robots" content="noindex, nofollow">' in client.get("/topic/Q1").data


def test_topic_page_404s_for_a_suppressed_topic(client, db, seed_languages):
    now = datetime.now(timezone.utc)
    db.session.add_all(
        [
            Topic(qid="Q1", entity_class="concept", is_human=False, is_living=False,
                  first_seen=now, last_seen=now, suppressed=True),
            _gap("Q1", "Hidden"),
        ]
    )
    db.session.commit()

    assert client.get("/topic/Q1").status_code == 404


def test_topic_page_404s_for_an_unknown_topic(client, seed_languages):
    assert client.get("/topic/Q999").status_code == 404


def test_topic_page_hides_overridden_and_disabled_gaps(client, db, seed_languages):
    """Same visibility rules as the gap list -- it reuses the one query."""
    db.session.add_all(
        [
            _topic_row("Q1"),
            Detector(detector_key="commons_no_image", project_code="commons", gap_type="no_image",
                     maturity="experimental", enabled=False),
            _gap("Q1", "Visible"),
            _gap("Q1", "Hidden", project="commons", gap_type="no_image", detector_key="commons_no_image"),
        ]
    )
    db.session.commit()

    body = client.get("/topic/Q1?uselang=en").data.decode()
    assert "1 things missing" in body
    assert "no image yet" not in body


# -- language picker at scale -------------------------------------------------


def _seed_many_languages(db):
    from app.models import Language

    for code, autonym in [("de", "Deutsch"), ("es", "Español"), ("ru", "Русский")]:
        db.session.add(Language(code=code, autonym=autonym, seeded=True))
    db.session.commit()


def test_home_lists_languages_alphabetically_by_autonym(client, db, seed_languages):
    _seed_many_languages(db)
    body = client.get("/").data.decode()
    assert body.index("Deutsch") < body.index("Español") < body.index("Français")


def test_home_never_shows_gap_counts(client, db, seed_languages):
    """SPEC.md S6: no view may rank languages against each other, including
    implicitly by sorting or counting them."""
    _seed_many_languages(db)
    db.session.add_all(_gap(f"Q{i}", f"T{i}") for i in range(5))
    db.session.commit()

    main = _main(client.get("/?uselang=en")).replace("All 5 languages", "")
    assert "5" not in main


def _main(response):
    """Just the page body.

    The chrome outside it lists every translated interface language twice
    over -- the header's switcher, and the hreflang alternates in <head> --
    which is a different thing from the content-language picker these tests
    are about. Slicing <main> excludes both, and the footer's links too.

    Matched on the opening tag rather than the literal "<main>" so that
    adding an attribute to it (it carries id="content" for the skip link)
    doesn't silently break every caller.

    Note for anyone adding markup inside <main>: a couple of tests assert
    that no digit appears in here beyond the language count, so a stray
    data-index or similar will fail them in a confusing place.
    """
    body = response.data.decode()
    start = body.index(">", body.index("<main")) + 1
    return body[start:body.index("</main>")]


def test_home_search_filters_server_side(client, db, seed_languages):
    """Works with JavaScript off -- the live filter is enhancement only."""
    _seed_many_languages(db)
    main = _main(client.get("/?q=deu&uselang=en"))
    assert "Deutsch" in main
    assert "Français" not in main


def test_home_search_matches_the_language_code_too(client, db, seed_languages):
    _seed_many_languages(db)
    assert b"Deutsch" in client.get("/?q=de").data


def test_home_search_with_no_match_offers_a_way_back(client, db, seed_languages):
    _seed_many_languages(db)
    body = client.get("/?q=zzzz&uselang=en").data.decode()
    assert "No tracked language matches that." in body
    assert "Show every language" in body


def test_home_suggests_languages_from_accept_language(client, db, seed_languages):
    _seed_many_languages(db)
    main = _main(client.get("/?uselang=en", headers={"Accept-Language": "ru-RU,ru;q=0.9"}))
    suggested = main.split("Languages you read")[1].split("</ul>")[0]
    assert "Русский" in suggested
    assert "Français" not in suggested


def test_home_suggests_a_language_you_have_already_opened(client, db, seed_languages):
    """Visiting /de/ sets a cookie the picker reads next time."""
    _seed_many_languages(db)
    client.get("/de/")
    main = _main(client.get("/?uselang=en"))
    assert "Languages you read" in main
    assert "Deutsch" in main.split("Languages you read")[1].split("</ul>")[0]


def test_home_suggestions_never_hide_the_full_list(client, db, seed_languages):
    _seed_many_languages(db)
    main = _main(client.get("/?uselang=en", headers={"Accept-Language": "de"}))
    for autonym in ("Deutsch", "Español", "Français", "Русский", "Српски"):
        assert autonym in main.split("All 5 languages")[1]


# -- the interface-language switcher keeps the view you were on ---------------
#
# SPEC.md section 13: interface and content language are independent. A GET
# form replaces its action's query string with its own serialised fields, so
# every other parameter has to be re-submitted as a hidden input or changing
# one setting silently resets the other's view.


def test_switching_interface_language_keeps_the_gap_list_filters(client, db, seed_languages):
    body = client.get("/sr/gaps?project=wikipedia&type=no_article&page=2&uselang=en").data.decode()
    switcher = body[body.index('class="lang-switch"'):body.index("</form>", body.index('class="lang-switch"'))]
    assert 'name="project" value="wikipedia"' in switcher
    assert 'name="type" value="no_article"' in switcher
    assert 'name="page" value="2"' in switcher


def test_switching_interface_language_keeps_the_picker_search(client, db, seed_languages):
    body = client.get("/?q=sr&uselang=en").data.decode()
    switcher = body[body.index('class="lang-switch"'):body.index("</form>", body.index('class="lang-switch"'))]
    assert 'name="q" value="sr"' in switcher


def test_switching_interface_language_does_not_resubmit_the_old_one(client, db, seed_languages):
    """uselang is what the <select> itself submits. Echoing the current value
    back as a hidden input too would send two, and which one wins is a
    browser detail nobody should have to rely on."""
    body = client.get("/sr/gaps?project=wikipedia&uselang=fr").data.decode()
    switcher = body[body.index('class="lang-switch"'):body.index("</form>", body.index('class="lang-switch"'))]
    assert 'type="hidden" name="uselang"' not in switcher


def test_a_repeated_query_parameter_is_carried_through_in_full(client, db, seed_languages):
    """request.args.get() would silently keep only the first value. Werkzeug
    hands back a MultiDict, so the form has to iterate every value or
    switching language would quietly drop half a repeated filter."""
    body = client.get("/sr/gaps?project=wikipedia&project=wikidata&uselang=en").data.decode()
    switcher = body[body.index('class="lang-switch"'):body.index("</form>", body.index('class="lang-switch"'))]
    assert 'name="project" value="wikipedia"' in switcher
    assert 'name="project" value="wikidata"' in switcher


def _login_next(response):
    """The ?next= target the login link would send a visitor back to."""
    # Parse first, then let parse_qs do the percent-decoding. Unquoting the
    # whole href up front would turn the %26 inside the next= value into a
    # real &, splitting one parameter into two.
    from urllib.parse import parse_qs, urlparse

    body = response.data.decode()
    start = body.index('href="/login?', 0) + len('href="')
    href = body[start:body.index('"', start)]
    return parse_qs(urlparse(href).query)["next"][0]


def test_the_login_link_returns_you_to_the_view_you_were_filtering(client, db, seed_languages):
    """Logging in from a filtered gap list should not throw the filters
    away. _safe_next() already accepts any same-site relative path, so the
    only thing missing was the query string."""
    target = _login_next(client.get("/sr/gaps?project=wikipedia&page=2"))
    assert target == "/sr/gaps?project=wikipedia&page=2"


def test_the_login_link_has_no_stray_question_mark_without_a_query_string(client, seed_languages):
    """request.full_path appends a bare "?" even when there is no query
    string at all, so using it unguarded would send every visitor on an
    unfiltered page back to a URL with a dangling "?" on the end."""
    assert _login_next(client.get("/")) == "/"


# -- the language picker widget ----------------------------------------------


def test_the_picker_shows_a_language_name_beside_its_autonym(client, db, seed_languages):
    """The autonym stays the primary identifier; its name in the interface
    language is a secondary label, so somebody who knows a language as
    "Serbian" rather than "Српски" can recognise it."""
    main = _main(client.get("/?uselang=en"))
    assert "Српски" in main
    assert "Serbian" in main


def test_the_secondary_name_follows_the_interface_language(client, db, seed_languages):
    """SPEC.md section 13: interface and content language are independent.
    The label is the language's name in whatever chrome you are reading, not
    English with extra steps."""
    assert "serbe" in _main(client.get("/?uselang=fr"))
    assert "сербский" in _main(client.get("/?uselang=ru"))


def test_the_autonym_carries_its_own_lang_and_the_secondary_name_does_not(client, db, seed_languages):
    """docs/i18n.md: <html lang> is the *interface* language, so content-
    language text needs its own lang attribute or a screen reader announces
    Serbian with an English voice. The name beside it is in the interface
    language already, so tagging it would be the same bug inverted."""
    main = _main(client.get("/?uselang=en"))
    assert '<span class="lang-autonym" lang="sr" dir="auto">Српски</span>' in main
    assert '<span class="lang-name">Serbian</span>' in main


def test_a_name_identical_to_the_autonym_is_not_shown_twice(client, db, seed_languages):
    """A Serbian interface listing Serbian would otherwise stutter -- and
    the autonym is capitalised by hand where the name is not, so this has to
    compare case-insensitively to catch it."""
    main = _main(client.get("/?uselang=sr"))
    row = main[main.index('data-search="српски'):]
    row = row[:row.index("</li>")]
    assert "Српски" in row
    # The row renders the autonym and nothing beside it. (The lowercased
    # form still appears in data-search, which is what the search matches
    # on -- that is the attribute, not the label.)
    assert "lang-name" not in row


def test_the_picker_search_matches_the_english_name(client, db, seed_languages):
    """The whole point of adding names: "serbian" has no substring in common
    with "Српски", so the old autonym-or-code search could not find it."""
    main = _main(client.get("/?q=serbian&uselang=en"))
    assert "Српски" in main
    assert "Français" not in main


def test_the_picker_search_matches_the_name_in_the_interface_language(client, db, seed_languages):
    main = _main(client.get("/?q=serbe&uselang=fr"))
    assert "Српски" in main
    assert "Français" not in main


def test_the_picker_search_still_matches_the_english_name_in_other_chrome(client, db, seed_languages):
    """English stays in the haystack whatever the interface language, so a
    visitor reading Russian chrome who only knows "Serbian" is not stuck."""
    main = _main(client.get("/?q=serbian&uselang=ru"))
    assert "Српски" in main


def test_a_language_with_no_translated_name_shows_only_its_autonym(client, db, seed_languages):
    """A content language can be seeded before anyone names it. It must
    degrade to the autonym alone, never print a raw message key at a
    visitor."""
    from app.models import Language

    db.session.add(Language(code="zz", autonym="Zzish", seeded=True))
    db.session.commit()
    main = _main(client.get("/?uselang=en"))
    assert "Zzish" in main
    assert "duga-langname-zz" not in main


def test_the_search_haystack_does_not_repeat_itself(client, db, seed_languages):
    """With an English interface the interface name and the English name are
    the same string. Harmless in a substring search, but no reason to ship
    it twice."""
    body = client.get("/?uselang=en").data.decode()
    start = body.index('data-search="', body.index('lang-list')) + len('data-search="')
    haystack = body[start:body.index('"', start)].split()
    assert len(haystack) == len(set(haystack)), haystack


def test_a_server_side_search_match_is_never_hidden_inside_a_closed_picker(client, db, seed_languages):
    """SPEC.md section 12: every page works without JavaScript. With JS off
    the only way to reach a filtered result is this page load, so a ?q= that
    matched has to arrive with the disclosure already open -- otherwise the
    no-JS search path is broken, not merely plainer.

    Set up so that the search is the *only* thing that can open the panel:
    past the collapse threshold, so a short list doesn't open it, and with
    an Accept-Language that survives the filter, so a suggestion does exist
    and the empty-suggestions clause doesn't open it either.
    """
    from app.models import Language

    _seed_many_languages(db)
    for i in range(PICKER_COLLAPSE_MIN):
        db.session.add(Language(code=f"x{i}", autonym=f"Xx{i}", seeded=True))
    db.session.commit()

    body = client.get("/?q=deu&uselang=en", headers={"Accept-Language": "de"}).data.decode()
    assert "Deutsch" in body
    details = body[body.index("<details"):body.index(">", body.index("<details"))]
    assert "open" in details, "a ?q= match must not arrive inside a closed disclosure"


def test_the_picker_stays_open_while_the_tracked_list_is_short(client, db, seed_languages):
    """Collapsing a list that already fits on screen is one more tap for
    nothing."""
    body = client.get("/?uselang=en").data.decode()
    details = body[body.index("<details"):body.index(">", body.index("<details"))]
    assert "open" in details


def test_the_picker_collapses_once_the_tracked_list_outgrows_the_threshold(client, db, seed_languages):
    """The flat list is what stopped working at scale, so past the threshold
    the disclosure starts shut and the suggested shortcut carries the page."""
    from app.models import Language

    for i in range(PICKER_COLLAPSE_MIN):
        db.session.add(Language(code=f"x{i}", autonym=f"Xx{i}", seeded=True))
    db.session.commit()
    body = client.get("/?uselang=en", headers={"Accept-Language": "sr"}).data.decode()
    details = body[body.index("<details"):body.index(">", body.index("<details"))]
    assert "open" not in details


def test_a_collapsed_picker_still_offers_something_to_click(client, db, seed_languages):
    """The suggested shortcut sits outside the <details> precisely so that a
    collapsed widget is not a dead end -- on a phone it is often the only
    thing anyone needs."""
    from app.models import Language

    for i in range(PICKER_COLLAPSE_MIN):
        db.session.add(Language(code=f"x{i}", autonym=f"Xx{i}", seeded=True))
    db.session.commit()
    main = _main(client.get("/?uselang=en", headers={"Accept-Language": "sr"}))
    assert main.index("Српски") < main.index("<details")


def test_the_picker_opens_when_nothing_could_be_suggested(client, db, seed_languages):
    """A visitor whose Accept-Language matches nothing tracked would
    otherwise meet a collapsed box with no clickable language at all."""
    from app.models import Language

    for i in range(PICKER_COLLAPSE_MIN):
        db.session.add(Language(code=f"x{i}", autonym=f"Xx{i}", seeded=True))
    db.session.commit()
    body = client.get("/?uselang=en", headers={"Accept-Language": "ja"}).data.decode()
    details = body[body.index("<details"):body.index(">", body.index("<details"))]
    assert "open" in details


def test_the_suggested_shortcut_is_filterable_too(client, db, seed_languages):
    """Suggested rows used to carry no data attributes at all, so the live
    filter silently skipped them. One macro renders both lists now."""
    main = _main(client.get("/?uselang=en", headers={"Accept-Language": "sr"}))
    suggested = main.split("Languages you read")[1].split("</ul>")[0]
    assert "data-search=" in suggested


# -- the header ---------------------------------------------------------------


def test_the_interface_switcher_sits_in_the_header_not_the_footer(client, seed_languages):
    """It belongs with the username and logout it shares a purpose with.
    Tested by position rather than by markup so it cannot pass just because
    a stray copy exists somewhere on the page."""
    body = client.get("/?uselang=en").data.decode()
    assert body.index('id="uselang"') < body.index("<main")


def test_the_switchers_visible_label_is_part_of_its_accessible_name(client, seed_languages):
    """WCAG 2.5.3, Label in Name: the header has no room for the full
    wording, so the short visible text has to be contained in the
    unambiguous accessible name rather than be a different phrase -- or
    voice control cannot address the control by what it says."""
    body = client.get("/?uselang=en").data.decode()
    start = body.index('<select name="uselang"')
    select = body[start:body.index(">", start)]
    accessible_name = select.split('aria-label="')[1].split('"')[0]
    visible = body[body.index('class="lang-switch-text"'):]
    visible = visible[visible.index(">") + 1:visible.index("</span>")]
    assert visible, "the label must have visible text, not only an icon"
    assert visible.lower() in accessible_name.lower()


def test_the_page_offers_a_skip_link_before_the_header(client, seed_languages):
    """The header now carries a language control as well as the nav, so a
    keyboard visitor would otherwise tab through all of it on every page."""
    body = client.get("/?uselang=en").data.decode()
    assert body.index('class="skip-link"') < body.index("<header")
    assert 'href="#content"' in body
    assert '<main id="content"' in body


def test_the_footer_carries_source_and_about_links(client, seed_languages):
    """The switcher leaving emptied the footer. A Wikimedia tool needs its
    source discoverable, and /about was the only place it appeared."""
    body = client.get("/?uselang=en").data.decode()
    footer = body[body.index("<footer"):body.index("</footer>")]
    assert "github.com/dungodung/duga" in footer
    assert "Source code" in footer


def test_the_html_element_declares_a_text_direction(client, seed_languages):
    """Every one of the ten interface languages is left-to-right today, so
    this is groundwork: the CSS uses logical properties, which only mirror if
    something tells the document which way round it is."""
    assert b'dir="ltr"' in client.get("/?uselang=en").data
    assert b'dir="ltr"' in client.get("/?uselang=sr").data


def test_an_rtl_interface_language_would_flip_the_document(client, seed_languages, monkeypatch):
    """Exercised by pretending English is right-to-left, since no RTL
    interface language is translated yet. Guards the wiring, not the
    stylesheet -- a full RTL pass is a separate piece of work."""
    monkeypatch.setattr("app.i18n.RTL_LANGS", frozenset({"en"}))
    assert b'dir="rtl"' in client.get("/?uselang=en").data
