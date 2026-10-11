"""Small, read-only Wikidata lookups made during a request:

- entity_exists(): does this entity (item or lexeme) exist? Validates a
  human-entered QID/Lexeme id before linking a local concept/term to it
  (SPEC.md section 10's promotion path).
- entity_terms(): one item's labels and descriptions in a contributor's
  chosen reference languages, for the edit page.

Neither is the SPARQL/replica-query request-path SPEC.md section 4
forbids -- each is one fast wbgetentities call for a single entity, the
same class of live call the OAuth login flow already makes mid-request.
"""
import requests


def entity_exists(api_url: str, entity_id: str, user_agent: str, timeout: int = 5) -> bool:
    resp = requests.get(
        api_url,
        params={"action": "wbgetentities", "ids": entity_id, "props": "", "format": "json", "formatversion": "2"},
        headers={"User-Agent": user_agent},
        timeout=timeout,
    )
    if resp.status_code != 200:
        return False
    entity = resp.json().get("entities", {}).get(entity_id)
    return bool(entity) and "missing" not in entity


def entity_terms(api_url: str, entity_id: str, languages, user_agent: str, timeout: float = 3):
    """An item's labels and descriptions in `languages`, as
    {code: {"label": str | None, "description": str | None}}, or None if
    Wikidata could not be asked.

    The one live read the edit page makes, for the reference languages a
    contributor chose on their account page: which ones is up to them, so
    no detector could have stored them in advance. It is one entity and at
    most five languages, on a logged-in page, with a short timeout -- and
    a caller that gets None falls back to the English the detector did
    store, so a slow Wikidata costs the page its extra languages, never the
    form.
    """
    languages = list(languages)
    if not languages:
        return {}
    try:
        resp = requests.get(
            api_url,
            params={
                "action": "wbgetentities",
                "ids": entity_id,
                "props": "labels|descriptions",
                # Exactly these languages, and no `languagefallback`: a
                # fallback language's text shown under another language's
                # name would mislead. (MediaWiki booleans are true when
                # present at all, so it must be left out, not set to 0.)
                "languages": "|".join(languages),
                "format": "json",
                "formatversion": "2",
            },
            headers={"User-Agent": user_agent},
            timeout=timeout,
        )
        if resp.status_code != 200:
            return None
        entity = resp.json().get("entities", {}).get(entity_id)
    except (requests.RequestException, ValueError):
        return None
    if not entity or "missing" in entity:
        return None
    labels = entity.get("labels") or {}
    descriptions = entity.get("descriptions") or {}
    return {
        code: {
            "label": (labels.get(code) or {}).get("value"),
            "description": (descriptions.get(code) or {}).get("value"),
        }
        for code in languages
    }
