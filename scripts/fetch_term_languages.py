"""Regenerate data/wikidata_term_languages.json: every language Wikidata
accepts a label or description in, with its autonym and its name in each
of Duga's interface languages.

The account page's reference-language picker offers exactly this list.
It is a file in the repository rather than a live API call, because the
list changes a few times a year and a page should not wait on Wikidata to
draw a <datalist> (SPEC.md section 4). Rerun it when Wikidata adds
languages, or when Duga gains an interface language:

    python3 scripts/fetch_term_languages.py
"""
import json
import os
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import i18n  # noqa: E402

API = "https://www.wikidata.org/w/api.php"
USER_AGENT = "Duga/0.1 (https://duga.toolforge.org) fetch_term_languages.py"
OUT = os.path.join(ROOT, "data", "wikidata_term_languages.json")


def fetch(uselang):
    resp = requests.get(
        API,
        params={
            "action": "query",
            "meta": "wbcontentlanguages",
            # "term" is the set labels and descriptions may be written in --
            # wider than the set of Wikipedias, narrower than all of ISO 639.
            "wbclcontext": "term",
            "wbclprop": "code|autonym|name",
            "uselang": uselang,
            "format": "json",
            "formatversion": "2",
        },
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["query"]["wbcontentlanguages"]


def main():
    languages = {}
    for uselang in i18n.available_languages():
        for code, row in fetch(uselang).items():
            entry = languages.setdefault(code, {"autonym": row.get("autonym") or code, "names": {}})
            name = row.get("name")
            # MediaWiki answers with the code itself when it has no name
            # for a language; the autonym is the better fallback then, and
            # the reader falls back to it on its own.
            if name and name != code:
                entry["names"][uselang] = name

    # Names that only repeat English add bytes and nothing else: the
    # reader falls back to English before the autonym.
    for entry in languages.values():
        english = entry["names"].get("en")
        entry["names"] = {
            lang: name for lang, name in entry["names"].items() if lang == "en" or name != english
        }

    # One language per line, sorted, so a rerun diffs to just what changed.
    lines = [
        f"  {json.dumps(code)}: {json.dumps(languages[code], ensure_ascii=False, sort_keys=True)}"
        for code in sorted(languages)
    ]
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("{\n" + ",\n".join(lines) + "\n}\n")
    print(f"wrote {len(languages)} languages to {OUT}")


if __name__ == "__main__":
    main()
