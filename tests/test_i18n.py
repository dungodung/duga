import json
import os
import time
from unittest import mock

from app import i18n


def test_available_languages_is_read_from_the_directory():
    """Adding a language means adding a file -- nothing else is hardcoded
    (docs/i18n.md). The M0 three are asserted explicitly because they are
    the ones the rest of this module's tests translate against; the set is
    a superset check so adding the tenth language doesn't fail this."""
    langs = set(i18n.available_languages())
    assert {"en", "sr", "fr"} <= langs
    assert "qqq" not in langs, "qqq is translator documentation, never an interface language"


def test_translate_returns_requested_language():
    assert i18n.translate("duga-nav-home", "fr") == "Accueil"
    assert i18n.translate("duga-nav-home", "sr") == "Почетна"


def test_translate_falls_back_to_english_for_missing_key():
    # A key present in en.json but deliberately absent elsewhere would fall
    # back; here we simulate that by asking for a nonexistent language.
    assert i18n.translate("duga-nav-home", "xx") == "Home"


def test_translate_substitutes_positional_placeholders():
    text = i18n.translate("duga-lang-home-title", "en", "Français")
    assert text == "Duga in Français"


def test_translate_unknown_key_returns_the_key_itself():
    assert i18n.translate("duga-does-not-exist", "en") == "duga-does-not-exist"


# -- caching -----------------------------------------------------------------


def test_a_message_file_is_parsed_once_however_often_it_is_translated_from():
    """translate() used to re-read and re-parse a 210-key JSON file on every
    single call. A page renders dozens of strings, and the language picker
    renders two per language row, so this was pure waste at ~200us a time."""
    i18n._MESSAGE_CACHE.clear()
    parses = []
    real_load = json.load

    def counting_load(fh):
        parses.append(1)
        return real_load(fh)

    with mock.patch.object(i18n.json, "load", counting_load):
        for _ in range(25):
            i18n.translate("duga-nav-home", "en")

    assert len(parses) == 1, f"parsed en.json {len(parses)} times, expected once"


def test_editing_a_message_file_is_picked_up_without_a_restart(tmp_path, monkeypatch):
    """The cache is keyed on mtime rather than being a plain dict, so that
    `flask run --debug` still reflects an edit to a message file. A cache
    that needed a restart to clear would make translation work miserable."""
    monkeypatch.setattr(i18n, "I18N_DIR", str(tmp_path))
    i18n._MESSAGE_CACHE.clear()
    path = tmp_path / "en.json"

    path.write_text(json.dumps({"duga-test": "first"}), encoding="utf-8")
    assert i18n.translate("duga-test", "en") == "first"

    # Same path, new content, and an mtime far enough ahead to be visible
    # on a filesystem with coarse timestamp granularity.
    path.write_text(json.dumps({"duga-test": "second"}), encoding="utf-8")
    os.utime(path, (time.time() + 10, time.time() + 10))
    assert i18n.translate("duga-test", "en") == "second"


def test_available_languages_is_not_relisted_on_every_call(tmp_path, monkeypatch):
    """It is called once per request and then looped in base.html for the
    hreflang alternates, so an os.listdir per call is wasted work."""
    monkeypatch.setattr(i18n, "I18N_DIR", str(tmp_path))
    monkeypatch.setattr(i18n, "_LANGUAGES_CACHE", None)
    (tmp_path / "en.json").write_text("{}", encoding="utf-8")
    (tmp_path / "qqq.json").write_text("{}", encoding="utf-8")

    listings = []
    real_listdir = os.listdir

    def counting_listdir(path):
        listings.append(path)
        return real_listdir(path)

    with mock.patch.object(i18n.os, "listdir", counting_listdir):
        first = i18n.available_languages()
        for _ in range(10):
            i18n.available_languages()

    assert first == ["en"]
    assert len(listings) == 1, f"listed the directory {len(listings)} times, expected once"


def test_callers_cannot_corrupt_the_cached_language_list():
    """available_languages() hands back a list that templates and
    resolve_interface_lang() both iterate; if one of them sorted it in
    place, every later request would see the mutation."""
    first = i18n.available_languages()
    first.append("zz")
    assert "zz" not in i18n.available_languages()


# -- message file integrity --------------------------------------------------
#
# Every language file is checked against English rather than reviewed by
# hand: with ten of them, a missing key or a dropped $1 is much likelier
# than a mistranslation to slip through unnoticed, and it is the failure
# mode that actually breaks a page.


def _message_files():
    import json
    import os

    files = {}
    for name in sorted(os.listdir(i18n.I18N_DIR)):
        if name.endswith(".json"):
            with open(os.path.join(i18n.I18N_DIR, name), encoding="utf-8") as fh:
                data = json.load(fh)
            data.pop("@metadata", None)
            files[name[: -len(".json")]] = data
    return files


def test_every_language_has_every_english_key():
    files = _message_files()
    english = files["en"]
    for code, messages in files.items():
        missing = sorted(set(english) - set(messages))
        assert not missing, f"{code}.json is missing {missing}"


def test_no_language_has_keys_english_does_not():
    files = _message_files()
    english = files["en"]
    for code, messages in files.items():
        extra = sorted(set(messages) - set(english))
        assert not extra, f"{code}.json has keys not in en.json: {extra}"


def test_placeholders_match_english_in_every_language():
    """A dropped or renumbered $1 renders the literal "$1" to a visitor."""
    import re

    files = _message_files()
    english = files["en"]
    placeholder = re.compile(r"\$\d")
    for code, messages in files.items():
        if code == "qqq":
            continue  # documentation prose, not a translation
        for key, value in messages.items():
            assert sorted(placeholder.findall(value)) == sorted(placeholder.findall(english[key])), (
                f"{code}.json:{key} placeholders differ from English"
            )


def test_every_interface_language_has_an_autonym():
    for code in i18n.available_languages():
        assert i18n.autonym(code) != code, f"{code} has no entry in AUTONYMS"


def test_unreviewed_translations_say_so():
    """Machine-drafted files must carry the warning, so nobody mistakes
    them for reviewed copy (SPEC.md section 13's terminology policy)."""
    import json
    import os

    for code in ("de", "es", "it", "nl", "pl", "ru", "sv"):
        with open(os.path.join(i18n.I18N_DIR, f"{code}.json"), encoding="utf-8") as fh:
            metadata = json.load(fh).get("@metadata", {})
        assert "not reviewed" in metadata.get("note", "").lower(), code


# -- language names ----------------------------------------------------------


def test_a_language_name_is_given_in_the_interface_language():
    """SPEC.md section 13: interface and content language are independent.
    The name beside an autonym is in whichever chrome you are reading, so
    "German" is only right while that chrome happens to be English."""
    assert i18n.language_name("de", "en") == "German"
    assert i18n.language_name("de", "es") == "alemán"
    assert i18n.language_name("de", "ru") == "немецкий"


def test_a_missing_language_name_resolves_to_empty_not_to_the_message_key():
    """A content language can be seeded before anyone names it. The picker
    then shows its autonym alone, rather than printing "duga-langname-zz" at
    a visitor."""
    assert i18n.language_name("zz", "en") == ""


def test_every_interface_language_has_a_name_in_every_interface_language():
    """A missing name degrades quietly, which is correct but silent -- so the
    check has to live here. Adding an interface language means adding its
    duga-langname-* to all of them, and giving it names for all of them;
    docs/i18n.md's "Adding a language" lists it as a step."""
    for subject in i18n.available_languages():
        for reader in i18n.available_languages():
            assert i18n.language_name(subject, reader), (
                f"{subject} has no name in {reader}"
            )


def test_every_rtl_language_code_is_lowercase_and_plausible():
    """RTL_LANGS is matched against resolve_interface_lang()'s output, which
    is a filename stem from i18n/ -- so an uppercased or stray entry would
    simply never fire, silently."""
    for code in i18n.RTL_LANGS:
        assert code == code.lower()
        assert i18n.is_rtl(code)
    assert not i18n.is_rtl("en")
