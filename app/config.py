import os


class BaseConfig:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-insecure-key")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # Mandatory descriptive User-Agent for outbound Wikimedia API/WDQS calls.
    # Unused in M0 (no outbound requests yet); needed starting with the M1
    # scope_fetch/topic_refresh jobs.
    DUGA_USER_AGENT = os.environ.get("DUGA_USER_AGENT", "Duga/0.1 (dev) requests")


class DevelopmentConfig(BaseConfig):
    DEBUG = True


class TestingConfig(BaseConfig):
    TESTING = True


class ProductionConfig(BaseConfig):
    DEBUG = False
    SESSION_COOKIE_SECURE = True


CONFIG_BY_NAME = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
