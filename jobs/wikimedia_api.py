"""Thin, read-only helpers for the Wikimedia endpoints Duga's jobs use:
the Wikidata action API (scope page wikitext, entity data), WDQS (resolving
scope rules to topics), and the Wikimedia pageviews REST API (impact
scoring, S1+). No writes happen from here -- see SPEC.md section 9 for the
(separate, M6+) write path.
"""
import sys
import threading
import time
from datetime import date, timedelta
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class WikimediaApiError(RuntimeError):
    """Raised on anything that should fail a job loudly (SPEC.md guardrail 9)."""


class RetryableApiError(WikimediaApiError):
    """A transport-level failure worth another attempt: the connection died,
    or the body arrived incomplete. Subclasses WikimediaApiError so every
    existing handler treats it identically -- only retry loops care about the
    distinction, so that a genuinely bad request (a malformed SPARQL query,
    say) is never retried.
    """


# A detector sweeps ~2,200 requests across ten languages, so a single
# connection reset roughly thirteen minutes in used to kill the whole run --
# which is exactly what happened to wp_no_article on 2026-08-30. Retry the
# transient cases before giving up.
#
# 404 is deliberately NOT retried: get_monthly_pageviews() treats it as a
# real answer ("no data for this article") rather than a failure.
_RETRY = Retry(
    total=3,
    connect=3,
    read=3,
    status=3,
    backoff_factor=0.5,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=("GET",),
    respect_retry_after_header=True,
    raise_on_status=True,
)

# requests.Session is not documented as thread-safe, and impact_score fetches
# pageviews from a thread pool, so each thread gets its own.
_local = threading.local()


def _session() -> requests.Session:
    session = getattr(_local, "session", None)
    if session is None:
        session = requests.Session()
        adapter = HTTPAdapter(max_retries=_RETRY)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        _local.session = session
    return session


def _get(url, **kwargs):
    """Every outbound GET goes through here so that network-level failures
    become WikimediaApiError like every other failure.

    Without this, a connection reset or read timeout raised
    requests.RequestException, which is not WikimediaApiError -- so it slipped
    past jobs/detector_common.py's handler, the detector row was never marked
    'error', and the UI went on presenting the previous day's gaps as current.
    That is precisely the failure SPEC.md guardrail 9 forbids, and it is how
    wp_no_article failed silently on 2026-08-30.
    """
    try:
        return _session().get(url, **kwargs)
    except requests.RequestException as exc:
        raise RetryableApiError(f"request to {url} failed: {exc.__class__.__name__}: {exc}") from exc


def _json(resp, context: str):
    """Every response body is decoded through here so that a malformed or
    truncated body becomes WikimediaApiError like every other failure.

    This is the same lesson as _get() above, one layer up. On 2026-08-30 the
    transport layer was wrapped, but resp.json() was left bare -- and
    json.JSONDecodeError subclasses ValueError, not WikimediaApiError. So
    when WDQS returned a truncated 865KB body on 2026-09-01, the error blew
    straight past topic_refresh's per-rule handler and killed the whole run.
    A body that arrives cut in half is a transport failure wearing a
    different exception type; it is typed as one here.
    """
    try:
        return resp.json()
    except ValueError as exc:
        body = resp.text or ""
        raise RetryableApiError(
            f"could not decode the JSON response for {context}: {exc} "
            f"(received {len(body)} bytes, ending {body[-120:]!r})"
        ) from exc


def fetch_page_wikitext(api_url: str, title: str, user_agent: str, timeout: int = 30):
    """Returns (revision_id, wikitext) for the current revision of `title`.
    Raises WikimediaApiError if the page doesn't exist or the API errors.
    """
    resp = _get(
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
    data = _json(resp, f"the wikitext of {title!r}")

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


def run_sparql(endpoint: str, query: str, user_agent: str, timeout: int = 55, attempts: int = 3):
    """Runs a SPARQL query against WDQS and returns the list of ?item QIDs
    (plus any other requested bindings) as a list of dicts of plain values.
    A 55s timeout stays under WDQS's public 60s cutoff (SPEC.md section 4).

    WDQS keeps cutting the ~865KB person_orientation_sourced body off
    mid-stream: 2026-09-01 and again 2026-09-04. Both are the same event and
    it surfaces two different ways, depending on whether the chunked-transfer
    layer notices the premature end -- as a JSONDecodeError from the parse, or
    as a ChunkedEncodingError from the read. So the whole fetch retries, not
    just the parse: the first version of this guarded only the decode, and the
    2026-09-04 failure walked straight past it.

    _RETRY cannot cover either case. requests reads the body in Session.send,
    after urllib3 has already handed back a clean HTTP 200, so a body that
    dies mid-read is outside the adapter's retry scope entirely.

    A non-200 is NOT retried here -- _RETRY has already exhausted its attempts
    on 429/5xx by this point, and retrying a rejected query just repeats it.
    """
    delay = 2.0
    for attempt in range(1, attempts + 1):
        try:
            resp = _get(
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
            data = _json(resp, "a scope_rule WDQS query")
            break
        except RetryableApiError as exc:
            if attempt == attempts:
                raise
            print(
                f"run_sparql: attempt {attempt}/{attempts} did not complete "
                f"({exc}); retrying in {delay:.0f}s",
                file=sys.stderr,
            )
            time.sleep(delay)
            delay *= 2

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
    {qid: {"sitelinks": {"enwiki": {...}, ...}, "label": str | None,
    "label_lang": str | None}}.

    `label_lang` is the language the label actually came back in, which is
    not necessarily the one asked for: with languagefallback on, a request
    for `sr` can be answered from a fallback chain or from the explicit
    English fallback below. Callers store it so the UI can mark the text
    with a correct `lang` attribute instead of asserting the requested
    language over a value that may be English.

    Callers needing more than 50 ids must chunk themselves.
    """
    if len(qids) > MAX_ENTITY_IDS_PER_REQUEST:
        raise ValueError(f"get_entities_batch takes at most {MAX_ENTITY_IDS_PER_REQUEST} ids at a time")

    languages = language if language == "en" else f"{language}|en"

    resp = _get(
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
    data = _json(resp, f"wbgetentities sitelinks/labels for {len(qids)} ids in {language!r}")

    result = {}
    for qid, entity in data.get("entities", {}).items():
        if "missing" in entity:
            result[qid] = {"sitelinks": {}, "label": None, "label_lang": None}
            continue
        labels = entity.get("labels", {})
        label_entry = labels.get(language) or labels.get("en")
        result[qid] = {
            "sitelinks": entity.get("sitelinks", {}),
            "label": label_entry["value"] if label_entry else None,
            "label_lang": label_entry.get("language") if label_entry else None,
        }
    return result


def get_claims_batch(api_url: str, qids: list, properties: list, language: str, user_agent: str, timeout: int = 30):
    """Fetches claim presence for `properties` (e.g. ["P18"]) plus a
    best-effort label (same fallback behaviour as get_entities_batch) for
    up to 50 QIDs in one call -- for "is there a P18/P373/... statement at
    all" checks (commons_no_image, commons_no_category), as opposed to
    get_entities_batch's sitelink-presence check. Returns
    {qid: {"claims": {property: bool}, "label": str | None,
    "label_lang": str | None}} -- see get_entities_batch on `label_lang`.
    """
    if len(qids) > MAX_ENTITY_IDS_PER_REQUEST:
        raise ValueError(f"get_claims_batch takes at most {MAX_ENTITY_IDS_PER_REQUEST} ids at a time")

    languages = language if language == "en" else f"{language}|en"

    resp = _get(
        api_url,
        params={
            "action": "wbgetentities",
            "format": "json",
            "formatversion": "2",
            "ids": "|".join(qids),
            "props": "claims|labels",
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
    data = _json(resp, f"wbgetentities claims for {len(qids)} ids in {language!r}")

    result = {}
    for qid, entity in data.get("entities", {}).items():
        if "missing" in entity:
            result[qid] = {"claims": {prop: False for prop in properties}, "label": None, "label_lang": None}
            continue
        claims = entity.get("claims", {})
        labels = entity.get("labels", {})
        label_entry = labels.get(language) or labels.get("en")
        result[qid] = {
            "claims": {prop: bool(claims.get(prop)) for prop in properties},
            "label": label_entry["value"] if label_entry else None,
            "label_lang": label_entry.get("language") if label_entry else None,
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

    resp = _get(
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
    data = _json(resp, f"wbgetentities labels/descriptions for {len(qids)} ids in {language!r}")

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


PAGEVIEWS_API = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"


def _previous_month_range() -> tuple:
    """Returns (start, end) timestamps -- YYYYMMDD00 -- spanning the most
    recently completed calendar month, the standard window for a single
    "monthly" granularity bucket from the pageviews API."""
    today = date.today()
    first_of_this_month = today.replace(day=1)
    last_day_prev_month = first_of_this_month - timedelta(days=1)
    first_day_prev_month = last_day_prev_month.replace(day=1)
    start = first_day_prev_month.strftime("%Y%m%d") + "00"
    end = last_day_prev_month.strftime("%Y%m%d") + "00"
    return start, end


def previous_month_key() -> str:
    """The completed month get_monthly_pageviews() reports on, as
    'YYYY-MM'. Derived from the same _previous_month_range() the request
    URL is built from, so a cache keyed on this can never disagree with
    the window that was actually fetched."""
    start, _end = _previous_month_range()
    return f"{start[:4]}-{start[4:6]}"


def get_monthly_pageviews(language_code: str, article_title: str, user_agent: str, timeout: int = 15) -> int:
    """Total pageviews for `article_title` on `{language_code}.wikipedia`
    over the most recently completed calendar month (impact scoring,
    S1+). Returns 0 -- not an error -- when the endpoint has no data for
    this article (HTTP 404: too new, redirect, or genuinely never
    viewed); raises WikimediaApiError on an actual failure (5xx,
    malformed response), leaving it to the caller to decide whether that
    should fail the whole run or just this one topic."""
    start, end = _previous_month_range()
    project = f"{language_code}.wikipedia"
    encoded_title = quote(article_title.replace(" ", "_"), safe="")
    url = f"{PAGEVIEWS_API}/{project}/all-access/all-agents/{encoded_title}/monthly/{start}/{end}"

    resp = _get(url, headers={"User-Agent": user_agent}, timeout=timeout)
    if resp.status_code == 404:
        return 0
    if resp.status_code != 200:
        raise WikimediaApiError(
            f"pageviews API returned HTTP {resp.status_code} for {project}/{article_title}: {resp.text[:300]}"
        )
    data = _json(resp, f"pageviews for {project}/{article_title}")
    return sum(item.get("views", 0) for item in data.get("items", []))
