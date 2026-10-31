import os
import pytest

from app.core.config import settings
from app.core.database import close_mongo_connection, connect_to_mongo

# Explicitly configure dedicated test database for pytest execution
TEST_DB_NAME = getattr(settings, "TEST_DATABASE_NAME", "smartenroll_test")
os.environ["DATABASE_NAME"] = TEST_DB_NAME
settings.DATABASE_NAME = TEST_DB_NAME

# Reset client to ensure connection binds to dedicated test database
close_mongo_connection()
connect_to_mongo()


@pytest.fixture(scope="session", autouse=True)
def enforce_test_database_isolation():
    """
    Critical safety fixture: guarantees test execution and cleanup are strictly
    confined to smartenroll_test and cannot touch the development database.
    """
    assert settings.DATABASE_NAME == "smartenroll_test", (
        f"CRITICAL SAFETY VIOLATION: Test suite attempted to run against '{settings.DATABASE_NAME}', expected 'smartenroll_test'."
    )
    assert settings.DATABASE_NAME != "smartenroll", (
        "CRITICAL: Refusing to run tests against the development database 'smartenroll'!"
    )
    yield
    close_mongo_connection()


@pytest.fixture(autouse=True)
def manage_rate_limiting_for_tests(monkeypatch, request):
    """
    Automatically bypasses rate limiting for non-rate-limit tests to avoid false throttling,
    while resetting and enabling rate limiting for tests that explicitly target rate limits.
    """
    from app.core.rate_limit import limiter
    limiter.reset()
    if "rate_limit" not in request.keywords and "test_rate_limit" not in request.node.name:
        monkeypatch.setattr("app.core.config.settings.RATE_LIMIT_ENABLED", False)
    else:
        monkeypatch.setattr("app.core.config.settings.RATE_LIMIT_ENABLED", True)
