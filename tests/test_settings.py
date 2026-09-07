import os
import tempfile

import pytest


@pytest.fixture()
def isolated_db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    from backend.config import settings
    settings.DATABASE_PATH = tmp.name
    from backend.database.db import init_db
    init_db()
    yield tmp.name
    os.remove(tmp.name)


def test_settings_return_defaults_when_unset(isolated_db):
    import backend.settings_service as svc
    result = svc.get_all_settings()
    assert result["default_risk_profile"] == "moderate"
    assert result["browser_notifications_enabled"] == "false"


def test_settings_persist_updates(isolated_db):
    import backend.settings_service as svc
    svc.set_setting("default_risk_profile", "aggressive")
    assert svc.get_setting("default_risk_profile") == "aggressive"
    # Other settings remain at their default, unaffected.
    assert svc.get_setting("browser_notifications_enabled") == "false"


def test_settings_update_is_idempotent(isolated_db):
    import backend.settings_service as svc
    svc.set_setting("default_risk_profile", "conservative")
    svc.set_setting("default_risk_profile", "aggressive")  # overwrite, not duplicate
    assert svc.get_setting("default_risk_profile") == "aggressive"


def test_clear_cache_removes_historical_price_rows(isolated_db):
    import backend.settings_service as svc
    from backend.database.db import db_cursor

    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO historical_prices (ticker, date, open, high, low, close, adj_close, volume, source, fetched_at) "
            "VALUES ('TEST', '2026-01-01', 1, 1, 1, 1, 1, 1000, 'fake', '2026-01-01T00:00:00Z')"
        )
    stats_before = svc.get_cache_stats()
    assert stats_before["cached_price_rows"] == 1

    cleared = svc.clear_historical_cache()
    assert cleared == 1
    stats_after = svc.get_cache_stats()
    assert stats_after["cached_price_rows"] == 0


def test_settings_api_endpoints(isolated_db):
    from fastapi.testclient import TestClient
    from backend.main import app

    with TestClient(app) as client:
        r = client.get("/api/settings")
        assert r.status_code == 200
        assert r.json()["default_risk_profile"] == "moderate"

        r = client.post("/api/settings?key=default_risk_profile&value=aggressive")
        assert r.status_code == 200

        r = client.get("/api/settings")
        assert r.json()["default_risk_profile"] == "aggressive"

        r = client.post("/api/settings?key=not_a_real_setting&value=x")
        assert r.status_code == 422

        r = client.get("/api/settings/cache-stats")
        assert r.status_code == 200

        r = client.post("/api/settings/clear-cache")
        assert r.status_code == 200
