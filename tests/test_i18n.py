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
