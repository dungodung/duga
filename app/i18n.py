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

# Autonyms for the languages Duga's own interface chrome is translated into.
# This is *not* the product's content-language list (Wikimedia languages a
# gap can be about) -- that much larger, community-relevant set lives in the
# `language` table starting at M1. Conflating the two would violate the
# interface/content independence principle in SPEC.md section 13.
#
# The two lists currently overlap heavily but are not identical: `ceb` is a
# tracked *content* language with no interface translation, so a Cebuano
# gap list is browsed with chrome in some other language. That asymmetry is
# the normal state of affairs for a Wikimedia tool, not a bug to fix by
# machine-translating into a language nobody here can check.
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


def available_languages():
    """Interface languages with a message file -- the source of truth for
    what's translated, not a hardcoded list that could drift from i18n/."""
    codes = []
    for name in sorted(os.listdir(I18N_DIR)):
        if name.endswith(".json") and name != "qqq.json":
            codes.append(name[:-len(".json")])
    return codes


def autonym(code):
    return AUTONYMS.get(code, code)


def _load(lang):
    path = os.path.join(I18N_DIR, f"{lang}.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    data.pop("@metadata", None)
    return data


def translate(key, lang, *args):
    messages = _load(lang)
    if key not in messages and lang != FALLBACK_LANG:
        messages = _load(FALLBACK_LANG)
    text = messages.get(key, key)
    if args:
        def _sub(match):
            index = int(match.group(1)) - 1
            return str(args[index]) if 0 <= index < len(args) else match.group(0)

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
