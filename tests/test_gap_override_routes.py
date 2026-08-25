import json
from datetime import datetime, timezone

from app.extensions import db
from app.models import AuditLog, Gap, GapOverride


def make_gap(gap_type="no_article", project_code="wikipedia", topic_qid="Q1", label="Some Topic", lang="sr"):
    now = datetime.now(timezone.utc)
    gap = Gap(
        topic_qid=topic_qid,
        language_code=lang,
        project_code=project_code,
        gap_type=gap_type,
        detector_key=f"wd_{gap_type}",
        scope_version_id=1,
        evidence_json=json.dumps({"label": label}),
        action_url=f"https://www.wikidata.org/wiki/{topic_qid}#labels",
        computed_at=now,
    )
    db.session.add(gap)
    db.session.commit()
    return gap


def test_override_requires_login(client, db, seed_languages):
    gap = make_gap()
    resp = client.post("/gap/override", data={"gap_id": gap.id, "status": "declined"})
    assert resp.status_code == 302
    assert "/login" in resp.location


def test_override_rejects_invalid_status(client, db, seed_languages, logged_in):
    gap = make_gap()
    resp = client.post("/gap/override", data={"gap_id": gap.id, "status": "done"})
    assert resp.status_code == 400
    assert GapOverride.query.count() == 0


def test_override_404s_for_nonexistent_gap(client, db, seed_languages, logged_in):
    resp = client.post("/gap/override", data={"gap_id": 999999, "status": "declined"})
    assert resp.status_code == 404


def test_override_declined_hides_gap_and_creates_override_row(client, db, seed_languages, logged_in):
    gap = make_gap(lang="sr")
    resp = client.post("/gap/override", data={"gap_id": gap.id, "status": "declined", "reason": "not notable enough"})
    assert resp.status_code == 302
    assert "/sr/gaps" in resp.location

    override = GapOverride.query.filter_by(topic_qid="Q1").first()
    assert override is not None
    assert override.status == "declined"
    assert override.reason == "not notable enough"
    assert override.set_by == "TestContributor"

    # Gap row itself is untouched -- only the override table changed.
    assert Gap.query.count() == 1

    # And the gap list no longer shows it.
    resp2 = client.get("/sr/gaps")
    assert b"Some Topic" not in resp2.data


def test_override_not_applicable_records_that_status(client, db, seed_languages, logged_in):
    gap = make_gap()
    client.post("/gap/override", data={"gap_id": gap.id, "status": "not_applicable"})
    override = GapOverride.query.filter_by(topic_qid="Q1").first()
    assert override.status == "not_applicable"
    assert override.reason is None


def test_override_writes_audit_log_entry(client, db, seed_languages, logged_in):
    gap = make_gap()
    client.post("/gap/override", data={"gap_id": gap.id, "status": "declined", "reason": "why not"})

    entry = AuditLog.query.filter_by(action="override_gap").first()
    assert entry is not None
    assert entry.actor == "TestContributor"
    assert entry.entity_id == str(gap.id)
    after = json.loads(entry.after_json)
    assert after["status"] == "declined"
    assert after["reason"] == "why not"


def test_override_already_overridden_gap_404s(client, db, seed_languages, logged_in):
    """Once a gap is overridden, it drops out of _visible_gaps_query -- a
    second override attempt via the same gap id can't find it any more,
    same as trying to re-fix an already-fixed gap in the write blueprint."""
    gap = make_gap()
    client.post("/gap/override", data={"gap_id": gap.id, "status": "declined"})
    resp = client.post("/gap/override", data={"gap_id": gap.id, "status": "not_applicable"})
    assert resp.status_code == 404
    assert GapOverride.query.count() == 1
