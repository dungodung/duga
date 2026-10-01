import os

from app import VERSIONED_ASSETS, asset_version


def test_the_stylesheet_and_script_carry_a_version_token(client, seed_languages):
    """url_for('static', ...) emits a bare path. Without a cache-buster a
    returning visitor gets new markup applied to the stylesheet their
    browser already had, which for a layout change is a broken page they
    have no reason to think a reload would fix."""
    body = client.get("/").data.decode()
    assert "/static/css/style.css?v=" in body
    assert "/static/js/enhance.js?v=" in body


def test_the_token_is_the_same_on_every_page(client, db, seed_languages):
    """It is computed once at startup, not per request: the files cannot
    change under a running process without a redeploy, which restarts it."""
    home = client.get("/").data.decode()
    about = client.get("/about").data.decode()
    marker = "/static/css/style.css?v="
    token = home[home.index(marker) + len(marker):].split('"')[0]
    assert token
    assert marker + token in about


def test_the_token_changes_when_an_asset_changes(tmp_path):
    """The whole point. If editing style.css left the token alone, the
    versioning would be decoration."""
    static = tmp_path / "static"
    (static / "css").mkdir(parents=True)
    (static / "js").mkdir(parents=True)
    css = static / "css" / "style.css"
    css.write_text("body{}", encoding="utf-8")
    (static / "js" / "enhance.js").write_text("", encoding="utf-8")

    before = asset_version(str(static))
    os.utime(css, (os.path.getmtime(css) + 60, os.path.getmtime(css) + 60))
    assert asset_version(str(static)) != before


def test_a_missing_asset_does_not_crash_startup(tmp_path):
    """A 404 on the asset itself says 'this file is missing' far more
    clearly than a traceback at boot does."""
    assert asset_version(str(tmp_path)) == "0"


def test_every_versioned_asset_actually_exists():
    """Guards against renaming a file and leaving this list behind, which
    would silently stop busting the cache for it."""
    import app as app_package

    static = os.path.join(os.path.dirname(app_package.__file__), "static")
    for name in VERSIONED_ASSETS:
        assert os.path.exists(os.path.join(static, name)), name
