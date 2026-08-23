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

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)

    @app.before_request
    def set_interface_lang():
        g.interface_lang = i18n.resolve_interface_lang()

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
