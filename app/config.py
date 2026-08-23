import os


def _db_uri() -> str:
    # TOOL_TOOLSDB_USER/PASSWORD are read-only system envvars Toolforge
    # auto-provisions per-tool (wikitech.wikimedia.org/wiki/Help:Toolforge/
    # Envvars) -- preferring them over DB_USER/DB_PASSWORD means the ToolsDB
    # credential is never manually copied into a second envvar by anyone
    # deploying this, and stays in sync with whatever Toolforge itself
    # manages/rotates. Local dev has neither var set, so it falls through to
    # DB_USER/DB_PASSWORD (the docker-compose mariadb) unchanged.
    user = os.environ.get("TOOL_TOOLSDB_USER") or os.environ.get("DB_USER", "duga")
    password = os.environ.get("TOOL_TOOLSDB_PASSWORD") or os.environ.get("DB_PASSWORD", "duga")
    host = os.environ.get("DB_HOST", "127.0.0.1")
    port = os.environ.get("DB_PORT", "3306")
    name = os.environ.get("DB_NAME", "duga")
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}?charset=utf8mb4"


class BaseConfig:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-insecure-key")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    SQLALCHEMY_DATABASE_URI = _db_uri()
    # pool_pre_ping alone wasn't enough in practice: jobs that spend minutes
    # making outbound Wikimedia API calls between DB touches (e.g.
    # wp_no_article, looping over ~450 wbgetentities requests before writing
    # gap rows) hit "MySQL server has gone away" against ToolsDB even with
    # it on -- a proxied backend can reset a connection in a way pre_ping's
    # lightweight check doesn't always catch. pool_recycle forces the pool
    # to discard and reopen any connection older than this, proactively,
    # rather than only reacting to a dead one.
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 120}
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Mandatory descriptive User-Agent for outbound Wikimedia API/WDQS calls
    # (see the wikimedia-api-access convention; enforced by MediaWiki/WDQS).
    DUGA_USER_AGENT = os.environ.get(
        "DUGA_USER_AGENT", "Duga/0.1 (https://duga.toolforge.org) requests"
    )

    # The on-wiki scope definition page scope_fetch reads from. See
    # docs/scope-definition.md -- SPEC.md section 6 requires this to live on
    # Wikidata under the WikiProject LGBT namespace, not in this repo.
    DUGA_SCOPE_PAGE = os.environ.get(
        "DUGA_SCOPE_PAGE", "Wikidata:WikiProject LGBT/Duga/scope"
    )
    DUGA_WIKIDATA_API = os.environ.get("DUGA_WIKIDATA_API", "https://www.wikidata.org/w/api.php")
    DUGA_WDQS_ENDPOINT = os.environ.get("DUGA_WDQS_ENDPOINT", "https://query.wikidata.org/sparql")


class DevelopmentConfig(BaseConfig):
    DEBUG = True


class TestingConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URI", "sqlite:///:memory:")


class ProductionConfig(BaseConfig):
    DEBUG = False
    SESSION_COOKIE_SECURE = True


CONFIG_BY_NAME = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
