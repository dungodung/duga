"""Shared compute logic for "missing sitelink on sister project X"
detectors -- wiktionary_no_entry, wikiquote_no_quotes, wikisource_no_text.
All three are structurally identical to wp_no_article.py (a sitelink is
either present under this project's dbname or it isn't); this module
exists so that sameness lives in one place instead of three copies.
wp_no_article.py predates this and keeps its own inline version rather
than being refactored onto it, since it's a stable v0.1 detector and
touching it isn't needed for this work.
"""
from jobs.detector_common import chunks
from jobs.wikimedia_api import MAX_ENTITY_IDS_PER_REQUEST, get_entities_batch

# Wikimedia language-code -> dbname-prefix exceptions that apply across
# every sister-project family, not just Wikipedia (e.g. Norwegian Bokmal
# is "nb" as a language code but "no" as a project prefix everywhere).
DBNAME_PREFIX_OVERRIDES = {
    "nb": "no",
}


def sitelink_dbname(language_code: str, family: str) -> str:
    prefix = DBNAME_PREFIX_OVERRIDES.get(language_code, language_code)
    return f"{prefix}{family}"


def make_compute_fn(family: str):
    """Returns a compute_fn(app, language_code, qids) suitable for
    jobs.detector_common.run_presence_detector, checking for a sitelink
    under f"{code}{family}" (with DBNAME_PREFIX_OVERRIDES applied)."""

    def compute_gaps_for_language(app, language_code, qids):
        dbname = sitelink_dbname(language_code, family)
        missing = {}
        for chunk in chunks(qids, MAX_ENTITY_IDS_PER_REQUEST):
            entities = get_entities_batch(
                app.config["DUGA_WIKIDATA_API"], chunk, language_code, app.config["DUGA_USER_AGENT"]
            )
            for qid, info in entities.items():
                if dbname not in info["sitelinks"]:
                    missing[qid] = {"label": info["label"]}
        return missing

    return compute_gaps_for_language
