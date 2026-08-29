from datetime import datetime, timezone

from app.extensions import db
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
    assert '<div class="gap-label" lang="en">Marsha P. Johnson</div>' in body
    assert '<div class="gap-label" lang="sr">родно квир</div>' in body


def test_gaps_page_omits_the_lang_attribute_when_the_label_language_is_unknown(client, db, seed_languages):
    """Rows written before detectors recorded label_lang: guess nothing."""
    db.session.add(_gap("Q1", "Unknown Provenance"))
    db.session.commit()

    body = client.get("/sr/gaps?uselang=en").data.decode()
    assert '<div class="gap-label">Unknown Provenance</div>' in body


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
