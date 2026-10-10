"""Interface-string loader.

Message files live in ``i18n/`` at the repo root: one JSON file per language
code, plus ``qqq.json`` holding message documentation for translators. This
is the "banana" i18n shape translatewiki.net expects from Wikimedia tools --
see SPEC.md section 13. It is deliberately not gettext/Babel: starting
compatible from commit one avoids a full retranslation later.
"""
import json
import os
import re

from flask import request

I18N_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "i18n")
FALLBACK_LANG = "en"
INTERFACE_LANG_COOKIE = "duga_uselang"
INTERFACE_LANG_COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # 1 year

_PLACEHOLDER_RE = re.compile(r"\$(\d+)")

# Parsed message files, keyed by language code: {code: (mtime, messages)}.
# translate() is called once per user-facing string, so a page renders
# dozens to hundreds of times -- and the language picker calls it twice per
# language row. Re-reading and re-parsing a 210-key JSON file that often is
# ~200us of pure waste each time. The mtime check means `flask run --debug`
# still picks up an edit to a message file without a restart, which is the
# only reason this isn't a plain dict.
_MESSAGE_CACHE = {}

# Same idea for the directory listing: available_languages() is called once
# per request by inject_i18n(), and then looped in base.html to emit an
# hreflang alternate per interface language. A directory's mtime changes
# when an entry is added or removed, which is exactly when this is stale.
_LANGUAGES_CACHE = None

# Autonyms for the languages Duga's own interface chrome is translated into.
# This is *not* the product's content-language list (Wikimedia languages a
# gap can be about) -- that much larger, community-relevant set lives in the
# `language` table starting at M1. Conflating the two would violate the
# interface/content independence principle in SPEC.md section 13.
#
# The two lists happen to match right now (ten each), which is a
# coincidence rather than an invariant: `ceb` was briefly a tracked content
# language with no interface translation, and any future content language
# will be too until someone translates the chrome. Nothing should be built
# that assumes the sets are equal.
AUTONYMS = {
    "en": "English",
    "sr": "Српски",
    "fr": "Français",
    "de": "Deutsch",
    "es": "Español",
    "it": "Italiano",
    "nl": "Nederlands",
    "pl": "Polski",
    "ru": "Русский",
    "sv": "Svenska",
}


# Interface languages written right to left. None of them are translated
# yet, so nothing here is exercised in production -- it exists because the
# alternative is discovering, the day somebody translates Duga into Arabic or
# Hebrew, that the whole stylesheet assumed otherwise. The CSS uses logical
# properties (padding-inline, border-inline-start) so that it mirrors from
# this one attribute rather than needing a second set of rules.
#
# Codes follow Wikimedia's conventions, not ISO's, per SPEC.md section 13.
RTL_LANGS = frozenset({"ar", "arc", "arz", "azb", "ckb", "dv", "fa", "he", "ks", "ku-arab",
                       "ps", "sd", "ug", "ur", "yi"})

# How each interface language groups the digits of a count: its separator,
# and how many digits must sit left of the first group before grouping
# starts at all. Spanish and Polish write 7714 but 37.714 / 37 714 -- that
# second number is CLDR's minimumGroupingDigits, and getting it wrong reads
# as a typo to a native speaker. Values are CLDR's, transcribed rather than
# pulled from Babel for the reason in this module's docstring. French uses
# U+202F (narrow no-break space); Polish, Russian and Swedish U+00A0 --
# either way a count never wraps across a line. A language missing here
# falls back to English's rule, and tests/test_i18n.py fails if any message
# file lacks an entry.
NUMBER_GROUPING = {
    "en": (",", 1),
    "sr": (".", 1),
    "fr": ("\u202f", 1),
    "de": (".", 1),
    "es": (".", 2),
    "it": (".", 1),
    "nl": (".", 1),
    "pl": ("\u00a0", 2),
    "ru": ("\u00a0", 1),
    "sv": ("\u00a0", 1),
}


def format_number(number, lang):
    """`number` with `lang`'s thousands separator: 37714 -> "37.714" in
    Serbian, "37,714" in English. Integers only -- every number Duga shows
    is a count."""
    separator, min_grouping = NUMBER_GROUPING.get(lang, NUMBER_GROUPING[FALLBACK_LANG])
    sign, digits = ("-", str(-number)) if number < 0 else ("", str(number))
    if len(digits) < 3 + min_grouping:
        return sign + digits
    groups = []
    while len(digits) > 3:
        groups.insert(0, digits[-3:])
        digits = digits[:-3]
    return sign + separator.join([digits] + groups)


def is_rtl(code):
    """Whether `code`'s script runs right to left, for <html dir>."""
    return code in RTL_LANGS


def available_languages():
    """Interface languages with a message file -- the source of truth for
    what's translated, not a hardcoded list that could drift from i18n/.

    Cached against the directory's mtime; see _LANGUAGES_CACHE. Returns a
    fresh list each call so a caller sorting or filtering it in place can't
    corrupt what the next request sees.
    """
    global _LANGUAGES_CACHE

    try:
        mtime = os.stat(I18N_DIR).st_mtime
    except OSError:
        mtime = None

    if _LANGUAGES_CACHE is None or _LANGUAGES_CACHE[0] != mtime:
        codes = []
        for name in sorted(os.listdir(I18N_DIR)):
            if name.endswith(".json") and name != "qqq.json":
                codes.append(name[:-len(".json")])
        _LANGUAGES_CACHE = (mtime, codes)

    return list(_LANGUAGES_CACHE[1])


def autonym(code):
    return AUTONYMS.get(code, code)


def language_name(code, lang):
    """A language's name written in `lang` -- "Serbian" in English chrome,
    "serbio" in Spanish chrome. The language picker shows it as a small
    secondary label beside the autonym, and matches it in search, so that
    somebody who knows a language as "Serbian" rather than "Српски" can
    still find it.

    Deliberately a message rather than a column on `language` or a dict in
    Python: this is user-facing text in the *interface* language (SPEC.md
    guardrail 4 -- no hardcoded user-facing English), and "German" is only
    the right answer while the interface happens to be English. It is also
    the same shape MediaWiki's CLDR extension uses.

    Returns "" rather than the message key when nobody has supplied a name,
    so a content language seeded before anyone translates it degrades to
    showing its autonym alone instead of printing "duga-langname-xx" at a
    visitor.
    """
    key = f"duga-langname-{code}"
    text = translate(key, lang)
    return "" if text == key else text


def _load(lang):
    """Parsed messages for one language, or {} if it has no file.

    The returned dict is the cached one, not a copy: translate() only ever
    reads from it, and copying 210 keys per call would hand back most of
    what the cache just saved. Treat it as read-only.
    """
    path = os.path.join(I18N_DIR, f"{lang}.json")
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        # No file for this language. Not cached: resolve_interface_lang()
        # only ever returns a code that has one, so this is the rare path
        # and a bare stat is cheaper than reasoning about invalidating a
        # cached absence once somebody adds the file.
        return {}

    cached = _MESSAGE_CACHE.get(lang)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    data.pop("@metadata", None)
    _MESSAGE_CACHE[lang] = (mtime, data)
    return data


def translate(key, lang, *args):
    messages = _load(lang)
    if key not in messages and lang != FALLBACK_LANG:
        messages = _load(FALLBACK_LANG)
    text = messages.get(key, key)
    if args:
        def _sub(match):
            index = int(match.group(1)) - 1
            if not 0 <= index < len(args):
                return match.group(0)
            arg = args[index]
            # Every integer reaching a message is a count, so it is grouped
            # for the reader's language here rather than at each call site.
            # bool is an int subclass; it is never meant as a number.
            if isinstance(arg, int) and not isinstance(arg, bool):
                return format_number(arg, lang)
            return str(arg)

        text = _PLACEHOLDER_RE.sub(_sub, text)
    return text


def resolve_interface_lang():
    """Interface language for this request: explicit choice (query param,
    then cookie) always wins; failing that, default to the content language
    being browsed for this one request -- so a first visit to /sr/ isn't
    English chrome around Serbian content -- then Accept-Language, then
    English. Interface and content language stay independent once a real
    preference is set; this is only a same-request fallback default.
    """
    langs = available_languages()

    requested = request.args.get("uselang")
    if requested in langs:
        return requested

    cookie_lang = request.cookies.get(INTERFACE_LANG_COOKIE)
    if cookie_lang in langs:
        return cookie_lang

    view_lang = (request.view_args or {}).get("lang")
    if view_lang in langs:
        return view_lang

    return request.accept_languages.best_match(langs) or FALLBACK_LANG
