from flask import Flask, g, render_template, request

from . import i18n
from .config import CONFIG_BY_NAME
from .extensions import db, migrate


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
        }

    @app.context_processor
    def inject_contributor():
        return {"contributor": current_contributor()}

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("404.html"), 404

    return app
