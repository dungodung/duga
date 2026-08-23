def test_home_lists_all_available_languages(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Fran\xc3\xa7ais" in resp.data
    assert "Српски".encode() in resp.data
    assert b"English" in resp.data


def test_lang_home_renders_for_known_language(client):
    resp = client.get("/fr/")
    assert resp.status_code == 200
    assert "Duga en Français".encode() in resp.data


def test_lang_home_404s_for_unknown_language(client):
    resp = client.get("/xx/")
    assert resp.status_code == 404


def test_lang_home_defaults_interface_language_to_content_language(client):
    resp = client.get("/sr/")
    assert resp.status_code == 200
    assert b'lang="sr"' in resp.data


def test_uselang_query_param_overrides_content_language_default(client):
    resp = client.get("/sr/?uselang=fr")
    assert resp.status_code == 200
    assert b'lang="fr"' in resp.data


def test_uselang_choice_persists_via_cookie(client):
    client.get("/?uselang=fr")
    resp = client.get("/")
    assert b'lang="fr"' in resp.data


def test_about_page_renders(client):
    resp = client.get("/about")
    assert resp.status_code == 200
    assert b"GPL-3.0-or-later" in resp.data


def test_unknown_route_renders_translated_404(client):
    # A single path segment without a trailing slash first 308s to try it as
    # a /<lang>/ candidate (Flask's normal strict_slashes behaviour) before
    # 404ing -- follow that redirect rather than special-casing the route.
    resp = client.get("/this-page-does-not-exist", follow_redirects=True)
    assert resp.status_code == 404
    assert b"Page not found" in resp.data


def test_unknown_multi_segment_route_404s_directly(client):
    resp = client.get("/no/such/page")
    assert resp.status_code == 404
    assert b"Page not found" in resp.data
