from flask import Blueprint, abort, jsonify, render_template

from ... import i18n

main_bp = Blueprint("main", __name__)


@main_bp.get("/")
def home():
    return render_template("index.html", languages=i18n.available_languages())


@main_bp.get("/<lang>/")
def lang_home(lang):
    if lang not in i18n.available_languages():
        abort(404)
    return render_template("lang_home.html", content_lang=lang)


@main_bp.get("/about")
def about():
    return render_template("about.html")


@main_bp.get("/health")
def health():
    return jsonify(status="ok"), 200
