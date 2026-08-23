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
