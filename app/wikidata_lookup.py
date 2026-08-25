"""A single, trivial, read-only lookup: does this Wikidata entity (item or
lexeme) exist? Used only to validate a human-entered QID/Lexeme id before
linking a local concept/term to it (SPEC.md section 10's promotion path).
This is not the SPARQL/replica-query request-path SPEC.md section 4
forbids -- it's one fast wbgetentities existence check, the same class of
live call the OAuth login flow already makes mid-request.
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
