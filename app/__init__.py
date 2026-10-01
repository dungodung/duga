import os

from flask import Flask, g, render_template, request

from . import i18n
from .config import CONFIG_BY_NAME
from .extensions import db, migrate

# The hand-written assets, in the order they appear in base.html. Both are
# served straight from disk with no build step, so their mtimes are the only
# version information that exists.
VERSIONED_ASSETS = ("css/style.css", "js/enhance.js")


def asset_version(static_folder):
    """A cache-busting token for the stylesheet and the enhancement script.

    url_for('static', ...) emits a bare path with nothing to invalidate on,
    so without this a returning visitor gets the new markup applied to
    whichever stylesheet their browser already had cached. For a small
    tweak that is a stale detail; for a layout change it is a broken page,
    and there is no way for them to know a reload would fix it.

    Computed once at startup rather than per request -- the files cannot
    change under a running process without a redeploy, which restarts it.
    One token for both files, because they change together and a single
    query parameter is simpler to reason about than two.
    """
    newest = 0.0
    for name in VERSIONED_ASSETS:
        try:
            newest = max(newest, os.stat(os.path.join(static_folder, name)).st_mtime)
        except OSError:
            # A missing asset is not this function's problem to report: the
            # 404 on the asset itself says it far more clearly than a
            # startup crash would.
            continue
    return str(int(newest))


def create_app(config_name: str = "production") -> Flask:
    app = Flask(__name__)
    app.config.from_object(CONFIG_BY_NAME.get(config_name, CONFIG_BY_NAME["production"]))

    db.init_app(app)
    migrate.init_app(app, db, directory="migrations")

    from . import models  # noqa: F401 registers models with SQLAlchemy metadata

    from .blueprints.auth.routes import auth_bp, current_contributor
    from .blueprints.main.routes import main_bp
    from .blueprints.vocabulary.routes import vocab_bp
    from .blueprints.write.routes import write_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(vocab_bp)
    app.register_blueprint(write_bp)

    @app.before_request
    def set_interface_lang():
        g.interface_lang = i18n.resolve_interface_lang()

    @app.after_request
    def persist_recent_content_language(response):
        """Remembers which content languages this visitor has opened, so
        the language picker can lift them to the top once the tracked list
        outgrows a single readable page. Most recent first, capped, and
        entirely client-side -- nothing about the visitor is stored server
        side (SPEC.md S5's spirit: Duga does not build profiles).

        Deliberately separate from the interface-language cookie: which
        language you read *about* and which language the buttons are in are
        independent (SPEC.md section 13)."""
        lang = g.get("remember_language")
        if not lang:
            return response
        from .blueprints.main.routes import RECENT_LANGUAGE_COOKIE, RECENT_LANGUAGE_LIMIT

        seen = [lang]
        for code in (request.cookies.get(RECENT_LANGUAGE_COOKIE) or "").split(","):
            if code and code != lang and code.isalnum() and len(seen) < RECENT_LANGUAGE_LIMIT:
                seen.append(code)
        response.set_cookie(
            RECENT_LANGUAGE_COOKIE,
            ",".join(seen),
            max_age=i18n.INTERFACE_LANG_COOKIE_MAX_AGE,
            samesite="Lax",
        )
        return response

    @app.after_request
    def persist_interface_lang(response):
        requested = request.args.get("uselang")
        if requested in i18n.available_languages():
            response.set_cookie(
                i18n.INTERFACE_LANG_COOKIE,
                requested,
                max_age=i18n.INTERFACE_LANG_COOKIE_MAX_AGE,
                samesite="Lax",
            )
        return response

    @app.context_processor
    def inject_i18n():
        lang = g.get("interface_lang", i18n.FALLBACK_LANG)
        return {
            "_": lambda key, *args: i18n.translate(key, lang, *args),
            "interface_lang": lang,
            "available_languages": i18n.available_languages(),
            "autonym": i18n.autonym,
            "interface_dir": "rtl" if i18n.is_rtl(lang) else "ltr",
        }

    @app.context_processor
    def inject_contributor():
        return {"contributor": current_contributor()}

    app.config.setdefault("DUGA_ASSET_VERSION", asset_version(app.static_folder))

    @app.context_processor
    def inject_asset_version():
        return {"asset_version": app.config["DUGA_ASSET_VERSION"]}

    @app.context_processor
    def inject_current_path():
        """The path *including* its query string, for ?next= round trips.

        `request.full_path` would do, except Flask appends a bare "?" when
        there is no query string at all, so a login link off the home page
        would read next=/%3F. Templates use this anywhere they need to send
        someone back to the view they were actually looking at -- a gap list
        keeps its filters and page, the picker keeps its search.
        """
        return {
            "current_path": request.full_path if request.query_string else request.path,
        }

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("404.html"), 404

    return app
