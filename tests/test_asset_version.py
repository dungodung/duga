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


def _fake_static(tmp_path, css="body{}", js=""):
    static = tmp_path / "static"
    (static / "css").mkdir(parents=True, exist_ok=True)
    (static / "js").mkdir(parents=True, exist_ok=True)
    (static / "css" / "style.css").write_text(css, encoding="utf-8")
    (static / "js" / "enhance.js").write_text(js, encoding="utf-8")
    return static


def test_the_token_changes_when_an_asset_changes(tmp_path):
    """The whole point. If editing style.css left the token alone, the
    versioning would be decoration."""
    static = _fake_static(tmp_path, css="body{color:red}")
    before = asset_version(str(static))
    (static / "css" / "style.css").write_text("body{color:blue}", encoding="utf-8")
    assert asset_version(str(static)) != before


def test_the_token_changes_when_only_the_script_changes(tmp_path):
    """Both files share one token, so a JS-only change has to move it too."""
    static = _fake_static(tmp_path, js="var a=1;")
    before = asset_version(str(static))
    (static / "js" / "enhance.js").write_text("var a=2;", encoding="utf-8")
    assert asset_version(str(static)) != before


def test_the_token_is_derived_from_contents_not_timestamps(tmp_path):
    """Regression. This started out hashing mtimes and was inert in
    production: Toolforge's build service normalises every file's timestamp
    to 1980-01-01 for reproducible builds, so the token came out the same
    constant on every deploy -- exactly the stale-CSS failure it exists to
    prevent. Pin both halves: identical bytes with different mtimes must
    agree, and different bytes with identical mtimes must not."""
    static = _fake_static(tmp_path, css="body{color:red}")
    css = static / "css" / "style.css"
    stamp = os.path.getmtime(css)

    unchanged = asset_version(str(static))
    os.utime(css, (stamp + 86400, stamp + 86400))
    assert asset_version(str(static)) == unchanged, "an mtime alone must not move the token"

    css.write_text("body{color:blue}", encoding="utf-8")
    os.utime(css, (stamp + 86400, stamp + 86400))
    assert asset_version(str(static)) != unchanged, "new bytes must move it even at a fixed mtime"


def test_a_missing_asset_does_not_crash_startup(tmp_path):
    """A 404 on the asset itself says 'this file is missing' far more
    clearly than a traceback at boot does."""
    assert asset_version(str(tmp_path))


def test_an_asset_appearing_later_still_changes_the_token(tmp_path):
    """The absence is folded into the hash, so a deploy that restores a
    missing file does not serve it under the old token."""
    missing = asset_version(str(tmp_path / "static"))
    _fake_static(tmp_path)
    assert asset_version(str(tmp_path / "static")) != missing


def test_every_versioned_asset_actually_exists():
    """Guards against renaming a file and leaving this list behind, which
    would silently stop busting the cache for it."""
    import app as app_package

    static = os.path.join(os.path.dirname(app_package.__file__), "static")
    for name in VERSIONED_ASSETS:
        assert os.path.exists(os.path.join(static, name)), name
