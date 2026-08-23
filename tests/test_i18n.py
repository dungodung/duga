from app import i18n


def test_available_languages_includes_the_m0_hello_world_set():
    langs = i18n.available_languages()
    assert set(langs) == {"en", "sr", "fr"}


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
