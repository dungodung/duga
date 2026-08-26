"""Shared compute logic for "missing property claim" detectors --
commons_no_image (P18) and commons_no_category (P373). Structurally like
jobs/sitelink_gap.py's sitelink-presence check, but for a Wikidata claim
rather than a sitelink: an item either has at least one statement for the
property or it doesn't.
"""
from jobs.detector_common import chunks
from jobs.wikimedia_api import MAX_ENTITY_IDS_PER_REQUEST, get_claims_batch


def make_compute_fn(property_id: str):
    """Returns a compute_fn(app, language_code, qids) suitable for
    jobs.detector_common.run_presence_detector, flagging topics with no
    `property_id` claim at all. Note this fact doesn't actually vary by
    language -- an item either has a P18/P373 statement or it doesn't,
    regardless of which language community is looking -- but gaps are
    always scoped per-language in this app (each language's gap list is
    its own actionable page), so the same missing-claim gap is written
    once per tracked language, same as every other presence detector."""

    def compute_gaps_for_language(app, language_code, qids):
        missing = {}
        for chunk in chunks(qids, MAX_ENTITY_IDS_PER_REQUEST):
            entities = get_claims_batch(
                app.config["DUGA_WIKIDATA_API"], chunk, [property_id], language_code, app.config["DUGA_USER_AGENT"]
            )
            for qid, info in entities.items():
                if not info["claims"][property_id]:
                    missing[qid] = {"label": info["label"]}
        return missing

    return compute_gaps_for_language
