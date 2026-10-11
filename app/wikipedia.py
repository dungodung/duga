"""Where a language's Wikipedia lives. Shared by the detectors (which
match sitelinks by db name) and the web app (which links to the wiki to
start an article), so the two can't disagree.

Wikipedia's subdomains are Wikimedia language codes with a few
historical quirks on top (SPEC.md section 13) -- extend the overrides as
new seeded languages hit one.
"""
from urllib.parse import urlencode

WIKIPEDIA_SUBDOMAIN_OVERRIDES = {
    "nb": "no",
}


def wikipedia_subdomain(language_code: str) -> str:
    return WIKIPEDIA_SUBDOMAIN_OVERRIDES.get(language_code, language_code)


def wikipedia_dbname(language_code: str) -> str:
    """The site key Wikidata files sitelinks under: "srwiki", "nowiki"."""
    return wikipedia_subdomain(language_code).replace("-", "_") + "wiki"


def create_article_url(language_code: str, title: str) -> str:
    """Opens the editor on `title` in that language's Wikipedia -- a blank
    page when no article has that title yet. If one does (an unlinked
    article, or a different subject with the same name), the wiki shows it
    rather than overwriting anything."""
    query = urlencode({"title": title, "action": "edit"})
    return f"https://{wikipedia_subdomain(language_code)}.wikipedia.org/w/index.php?{query}"
