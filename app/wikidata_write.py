"""The only code in Duga that writes to Wikidata (SPEC.md section 9, S1,
S8). Only set_label()/set_description() exist -- there is no generic
"set claim" function anywhere in this module or called from it, so writing
an identity statement (P91, P21, or any other claim) isn't merely
disallowed by a check, it is structurally impossible through this code
path. Guardrail 6 ("property allowlist for writes, never a denylist,
adding a property to the allowlist is a human decision") is enforced the
same way: ALLOWED_EDIT_KINDS exists as an explicit, visible allowlist even
though the API surface above it already can't reach anything else.

Callers are responsible for the kill switch (S8), preview+confirmation,
rate limiting, and wiki_edit/audit_log bookkeeping -- see
app/blueprints/write/routes.py, which is the only caller.
"""
import requests

ALLOWED_EDIT_KINDS = {"label", "description"}

# gap_type -> edit_kind for the two gap types this write path can resolve.
# Lives here (not in app/blueprints/write/routes.py) so app/blueprints/main
# can also import it, for the gap list's "edit here" link, without a
# blueprint-to-blueprint circular import.
EDITABLE_GAP_TYPES = {"no_label": "label", "no_description": "description"}


class WikidataWriteError(RuntimeError):
    """Raised on anything that should surface as a failed (not silently
    swallowed) write attempt -- callers record this in wiki_edit.error."""


def edit_summary(edit_kind: str) -> str:
    if edit_kind not in ALLOWED_EDIT_KINDS:
        raise WikidataWriteError(f"{edit_kind!r} is not an allowed edit kind")
    return f"Added missing {edit_kind} via Duga (https://duga.toolforge.org)"


def _get_csrf_token(api_url: str, access_token: str, user_agent: str, timeout: int) -> str:
    resp = requests.get(
        api_url,
        params={"action": "query", "meta": "tokens", "type": "csrf", "format": "json", "formatversion": "2"},
        headers={"Authorization": f"Bearer {access_token}", "User-Agent": user_agent},
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise WikidataWriteError(f"Could not get a CSRF token (HTTP {resp.status_code}): {resp.text[:300]}")
    data = resp.json()
    try:
        return data["query"]["tokens"]["csrftoken"]
    except KeyError as exc:
        raise WikidataWriteError(f"Unexpected token response: {data}") from exc


def _set_term(action: str, api_url: str, access_token: str, qid: str, language: str, value: str, edit_kind: str, user_agent: str, timeout: int):
    """Shared by set_label/set_description -- `action` is always one of the
    two literal action-API names below, never taken from a caller-supplied
    value, so there's no way to reach any other action through this path."""
    summary = edit_summary(edit_kind)
    csrf_token = _get_csrf_token(api_url, access_token, user_agent, timeout)

    resp = requests.post(
        api_url,
        # Deliberately no "bot" param at all: MediaWiki's action API treats
        # a boolean param as true if merely *present*, regardless of its
        # string value -- passing bot="0" would actually mark this a bot
        # edit. These are individual, human-confirmed edits; omit it.
        data={
            "action": action,
            "id": qid,
            "language": language,
            "value": value,
            "summary": summary,
            "token": csrf_token,
            "format": "json",
            "formatversion": "2",
        },
        headers={"Authorization": f"Bearer {access_token}", "User-Agent": user_agent},
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise WikidataWriteError(f"Wikidata API returned HTTP {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    if "error" in data:
        raise WikidataWriteError(data["error"].get("info") or str(data["error"]))

    revid = data.get("entity", {}).get("lastrevid")
    return revid, summary


def set_label(api_url: str, access_token: str, qid: str, language: str, value: str, user_agent: str, timeout: int = 10):
    return _set_term("wbsetlabel", api_url, access_token, qid, language, value, "label", user_agent, timeout)


def set_description(api_url: str, access_token: str, qid: str, language: str, value: str, user_agent: str, timeout: int = 10):
    return _set_term("wbsetdescription", api_url, access_token, qid, language, value, "description", user_agent, timeout)
