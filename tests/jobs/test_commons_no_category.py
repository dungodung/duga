from datetime import datetime, timezone

import responses

from app.extensions import db
from app.models import Detector, Gap, Language, ScopeVersion, Topic
from jobs import commons_no_category

API_URL = "https://www.wikidata.org/w/api.php"


def seed_active_scope_version():
    version = ScopeVersion(
        source_page="Wikidata:WikiProject LGBT/Duga/scope",
        revision_id=1,
        raw_json="{}",
        fetched_at=datetime.now(timezone.utc),
        active=True,
    )
    db.session.add(version)
    db.session.commit()


def seed_topic(qid, is_living=True):
    now = datetime.now(timezone.utc)
    db.session.add(
        Topic(qid=qid, entity_class="human", is_human=True, is_living=is_living, first_seen=now, last_seen=now)
    )
    db.session.commit()


def seed_languages(*codes):
    for code in codes:
        db.session.add(Language(code=code, autonym=code, seeded=True))
    db.session.commit()


def entity(has_category=False, label=None, language="sr"):
    claims = {"P373": [{"mainsnak": {}}]} if has_category else {}
    labels = {language: {"value": label, "language": language}} if label is not None else {}
    return {"claims": claims, "labels": labels}


@responses.activate
def test_run_creates_gaps_only_for_non_living_topics_missing_a_category(app):
    with app.app_context():
        seed_active_scope_version()
        seed_topic("Q1", is_living=False)
        seed_topic("Q2", is_living=True)
        seed_languages("sr")

        responses.add(
            responses.GET,
            API_URL,
            json={"entities": {"Q1": entity(has_category=False, label="Has no category")}},
            status=200,
        )
        commons_no_category.run(app)

        gaps = Gap.query.filter_by(language_code="sr").all()
        assert {g.topic_qid for g in gaps} == {"Q1"}
        assert gaps[0].project_code == "commons"
        assert gaps[0].gap_type == "no_category"
        assert gaps[0].action_url == "https://www.wikidata.org/wiki/Q1#P373"

        detector = Detector.query.filter_by(detector_key="commons_no_category").first()
        assert detector.maturity == "experimental"
        assert detector.enabled is False
