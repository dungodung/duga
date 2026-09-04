import pytest


@pytest.fixture(autouse=True)
def _no_retry_backoff(monkeypatch):
    """run_sparql backs off between attempts. No test asserts on how long it
    waited, so keep the suite from actually sleeping through it."""
    monkeypatch.setattr("jobs.wikimedia_api.time.sleep", lambda _s: None)
