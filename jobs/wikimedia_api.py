"""Thin, read-only helpers for the two Wikimedia endpoints Duga's jobs use:
the Wikidata action API (to fetch the scope page's wikitext) and WDQS (to
resolve scope rules to topics). No writes happen from here -- see SPEC.md
section 9 for the (separate, M6+) write path.
"""
import requests


class WikimediaApiError(RuntimeError):
    """Raised on anything that should fail a job loudly (SPEC.md guardrail 9)."""


def fetch_page_wikitext(api_url: str, title: str, user_agent: str, timeout: int = 30):
    """Returns (revision_id, wikitext) for the current revision of `title`.
    Raises WikimediaApiError if the page doesn't exist or the API errors.
    """
    resp = requests.get(
        api_url,
        params={
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "prop": "revisions",
            "rvprop": "ids|content",
            "rvslots": "main",
            "titles": title,
        },
        headers={"User-Agent": user_agent},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()

    pages = data.get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing"):
        raise WikimediaApiError(f"Scope page {title!r} does not exist on-wiki")

    page = pages[0]
    revisions = page.get("revisions")
    if not revisions:
        raise WikimediaApiError(f"Scope page {title!r} has no revisions")

    revision = revisions[0]
    wikitext = revision["slots"]["main"]["content"]
    return revision["revid"], wikitext


def run_sparql(endpoint: str, query: str, user_agent: str, timeout: int = 55):
    """Runs a SPARQL query against WDQS and returns the list of ?item QIDs
    (plus any other requested bindings) as a list of dicts of plain values.
    A 55s timeout stays under WDQS's public 60s cutoff (SPEC.md section 4).
    """
    resp = requests.get(
        endpoint,
        params={"query": query},
        headers={
            "User-Agent": user_agent,
            "Accept": "application/sparql-results+json",
        },
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise WikimediaApiError(
            f"WDQS returned HTTP {resp.status_code} for a scope_rule query: {resp.text[:500]}"
        )
    data = resp.json()

    variables = data["head"]["vars"]
    rows = []
    for binding in data["results"]["bindings"]:
        row = {}
        for var in variables:
            cell = binding.get(var)
            row[var] = cell["value"] if cell else None
        rows.append(row)
    return rows


def qid_from_uri(uri: str) -> str:
    """'http://www.wikidata.org/entity/Q42' -> 'Q42'."""
    return uri.rsplit("/", 1)[-1]


MAX_ENTITY_IDS_PER_REQUEST = 50  # the action API's limit for non-bot accounts


def get_entities_batch(api_url: str, qids: list, language: str, user_agent: str, timeout: int = 30):
    """Fetches sitelinks + a best-effort label (with MediaWiki's language
    fallback chain, then an explicit English fallback if that chain still
    came up empty) for up to 50 QIDs in one call. Returns
    {qid: {"sitelinks": {"enwiki": {...}, ...}, "label": str | None}}.
    Callers needing more than 50 ids must chunk themselves.
    """
    if len(qids) > MAX_ENTITY_IDS_PER_REQUEST:
        raise ValueError(f"get_entities_batch takes at most {MAX_ENTITY_IDS_PER_REQUEST} ids at a time")

    languages = language if language == "en" else f"{language}|en"

    resp = requests.get(
        api_url,
        params={
            "action": "wbgetentities",
            "format": "json",
            "formatversion": "2",
            "ids": "|".join(qids),
            "props": "sitelinks|labels",
            "languages": languages,
            "languagefallback": "1",
        },
        headers={"User-Agent": user_agent},
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise WikimediaApiError(
            f"wbgetentities returned HTTP {resp.status_code} for {len(qids)} ids: {resp.text[:500]}"
        )
    data = resp.json()

    result = {}
    for qid, entity in data.get("entities", {}).items():
        if "missing" in entity:
            result[qid] = {"sitelinks": {}, "label": None}
            continue
        labels = entity.get("labels", {})
        label_entry = labels.get(language) or labels.get("en")
        result[qid] = {
            "sitelinks": entity.get("sitelinks", {}),
            "label": label_entry["value"] if label_entry else None,
        }
    return result


def get_raw_labels_and_descriptions(api_url: str, qids: list, language: str, user_agent: str, timeout: int = 30):
    """Like get_entities_batch, but deliberately WITHOUT MediaWiki's
    language fallback chain: a label/description here is present only if a
    genuine value exists exactly in `language`. wd_no_label/wd_no_description
    need this raw presence to decide whether something is actually missing
    -- a fallback-filled value would mask a real gap. English is requested
    alongside for display purposes only; because there's no fallback
    involved, the two never cross-contaminate (each key is populated only
    from that exact language's own value), so this needs just one request
    instead of a raw check plus a separate fallback lookup.
    Returns {qid: {"label_language": str|None, "label_en": str|None,
                    "description_language": str|None, "description_en": str|None}}.
    """
    if len(qids) > MAX_ENTITY_IDS_PER_REQUEST:
        raise ValueError(
            f"get_raw_labels_and_descriptions takes at most {MAX_ENTITY_IDS_PER_REQUEST} ids at a time"
        )

    languages = language if language == "en" else f"{language}|en"

    resp = requests.get(
        api_url,
        params={
            "action": "wbgetentities",
            "format": "json",
            "formatversion": "2",
            "ids": "|".join(qids),
            "props": "labels|descriptions",
            "languages": languages,
        },
        headers={"User-Agent": user_agent},
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise WikimediaApiError(
            f"wbgetentities returned HTTP {resp.status_code} for {len(qids)} ids: {resp.text[:500]}"
        )
    data = resp.json()

    result = {}
    for qid, entity in data.get("entities", {}).items():
        if "missing" in entity:
            result[qid] = {
                "label_language": None,
                "label_en": None,
                "description_language": None,
                "description_en": None,
            }
            continue
        labels = entity.get("labels", {})
        descriptions = entity.get("descriptions", {})
        result[qid] = {
            "label_language": labels.get(language, {}).get("value"),
            "label_en": labels.get("en", {}).get("value"),
            "description_language": descriptions.get(language, {}).get("value"),
            "description_en": descriptions.get("en", {}).get("value"),
        }
    return result
