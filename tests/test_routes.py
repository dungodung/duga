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
