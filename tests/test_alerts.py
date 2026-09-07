import os
import tempfile
from datetime import datetime, timezone

import pandas as pd
import pytest
from tests.conftest import business_day_anchor


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


def _make_series(n, breakout=False):
    today = business_day_anchor()
    dates = pd.date_range(end=today, periods=n, freq="B")
    if breakout:
        close = [100] * (n - 5) + [101, 103, 106, 110, 115]
    else:
        close = [100 + (i % 3 - 1) for i in range(n)]
    return pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"), "open": close, "high": [c + 1 for c in close],
        "low": [c - 1 for c in close], "close": close, "adj_close": close, "volume": [1_000_000] * n,
    })


def _install_toggleable_provider():
    from backend.data.base import DataResult, MarketDataProvider
    import backend.data.market_data_service as mds_module

    class FakeProvider(MarketDataProvider):
        name = "fake"

        def __init__(self):
            self.breakout_mode = False

        def get_quote(self, ticker):
            raise NotImplementedError

        def get_historical(self, ticker, period, interval="1d"):
            return DataResult(data=_make_series(130, breakout=self.breakout_mode), source=self.name,
                               fetched_at=datetime.now(timezone.utc), timeliness="end_of_day")

        def search(self, query):
            raise NotImplementedError

    fake = FakeProvider()
    mds_module.market_data_service.providers = [fake]
    return fake


def test_no_alert_on_first_ever_check(isolated_db):
    """First time seeing a ticker, there's no 'previous state' to
    compare against — must not fire a spurious alert."""
    from backend.database.db import db_cursor
    import backend.alerts.service as alerts_service

    _install_toggleable_provider()
    with db_cursor() as cur:
        cur.execute("INSERT INTO watchlist (ticker, added_at, notes) VALUES ('TESTCO', ?, '')",
                    (datetime.now(timezone.utc).isoformat(),))

    fired = alerts_service.check_watchlist_technical_changes()
    assert fired == 0


def test_no_spam_on_repeated_unchanged_checks(isolated_db):
    from backend.database.db import db_cursor
    import backend.alerts.service as alerts_service

    _install_toggleable_provider()
    with db_cursor() as cur:
        cur.execute("INSERT INTO watchlist (ticker, added_at, notes) VALUES ('TESTCO', ?, '')",
                    (datetime.now(timezone.utc).isoformat(),))

    alerts_service.check_watchlist_technical_changes()  # baseline
    fired_2 = alerts_service.check_watchlist_technical_changes()
    fired_3 = alerts_service.check_watchlist_technical_changes()
    fired_4 = alerts_service.check_watchlist_technical_changes()
    assert fired_2 == 0 and fired_3 == 0 and fired_4 == 0


def test_fires_exactly_once_on_real_change_then_stops(isolated_db):
    """The core requirement: a real change fires exactly one alert,
    and it does not keep re-firing on every subsequent check just
    because the new state persists."""
    from backend.database.db import db_cursor
    import backend.alerts.service as alerts_service

    fake = _install_toggleable_provider()
    with db_cursor() as cur:
        cur.execute("INSERT INTO watchlist (ticker, added_at, notes) VALUES ('TESTCO', ?, '')",
                    (datetime.now(timezone.utc).isoformat(),))

    alerts_service.check_watchlist_technical_changes()  # baseline

    fake.breakout_mode = True
    fired_on_change = alerts_service.check_watchlist_technical_changes()
    assert fired_on_change == 1

    fired_after = alerts_service.check_watchlist_technical_changes()
    assert fired_after == 0

    visible_alerts = alerts_service.get_alerts()
    assert len(visible_alerts) == 1
    assert "breakout" in visible_alerts[0]["title"]


def test_state_tracking_rows_never_appear_in_user_facing_alerts(isolated_db):
    from backend.database.db import db_cursor
    import backend.alerts.service as alerts_service

    _install_toggleable_provider()
    with db_cursor() as cur:
        cur.execute("INSERT INTO watchlist (ticker, added_at, notes) VALUES ('TESTCO', ?, '')",
                    (datetime.now(timezone.utc).isoformat(),))

    for _ in range(5):
        alerts_service.check_watchlist_technical_changes()

    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) as c FROM alerts")
        total_rows = cur.fetchone()["c"]

    visible = alerts_service.get_alerts()
    assert total_rows > 0  # state rows were written
    assert len(visible) == 0  # but none are user-facing, since nothing material ever changed


def test_mark_alert_read(isolated_db):
    from backend.database.db import db_cursor
    import backend.alerts.service as alerts_service

    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO alerts (ticker, created_at, alert_type, title, reasons_json) VALUES (?, ?, ?, ?, ?)",
            ("TESTCO", datetime.now(timezone.utc).isoformat(), "bullish", "Test alert", "{}"),
        )
        alert_id = cur.lastrowid

    assert alerts_service.count_unread_alerts() == 1
    assert alerts_service.mark_alert_read(alert_id) is True
    assert alerts_service.count_unread_alerts() == 0


def test_mark_all_alerts_read_excludes_state_rows(isolated_db):
    from backend.database.db import db_cursor
    import backend.alerts.service as alerts_service

    _install_toggleable_provider()
    with db_cursor() as cur:
        cur.execute("INSERT INTO watchlist (ticker, added_at, notes) VALUES ('TESTCO', ?, '')",
                    (datetime.now(timezone.utc).isoformat(),))
    alerts_service.check_watchlist_technical_changes()  # writes a state row, not a visible alert

    updated = alerts_service.mark_all_alerts_read()
    assert updated == 0  # nothing user-facing to mark read yet


# --------------------------------------------------------- portfolio exit-risk alerts
# The tests above all cover check_watchlist_technical_changes() — this
# section covers the OTHER half of the alert system, check_portfolio_
# exit_risk(), which had no dedicated anti-spam test at all until now.

def _install_deteriorating_provider():
    """A price series that starts healthy (well above its own moving
    averages) and can be switched into a deteriorated state (broken
    below both MAs, weak RSI) via a flag — lets a single test drive
    the exit-risk assessment through a real LOW -> HIGH transition."""
    from datetime import datetime, timezone
    from backend.data.base import DataResult, MarketDataProvider
    import backend.data.market_data_service as mds_module

    today = business_day_anchor()

    def make_series(deteriorated: bool):
        n = 250
        dates = pd.date_range(end=today, periods=n, freq="B")
        if deteriorated:
            # Trends up for most of the series (builds a high 50/200-day
            # MA), then drops hard in the last few days — breaks below
            # both moving averages, exactly the HIGH-risk scenario.
            close = [100 + i * 0.15 for i in range(n - 5)] + [130, 120, 108, 98, 90]
        else:
            # Steady uptrend throughout — price stays comfortably above
            # its own moving averages the whole time.
            close = [100 + i * 0.2 for i in range(n)]
        return pd.DataFrame({
            "date": dates.strftime("%Y-%m-%d"), "open": close, "high": [c + 1 for c in close],
            "low": [c - 1 for c in close], "close": close, "adj_close": close, "volume": [1_000_000] * n,
        })

    class FakeProvider(MarketDataProvider):
        name = "fake"

        def __init__(self):
            self.deteriorated = False

        def get_quote(self, ticker):
            raise NotImplementedError

        def get_historical(self, ticker, period, interval="1d"):
            return DataResult(data=make_series(self.deteriorated), source=self.name,
                               fetched_at=datetime.now(timezone.utc), timeliness="end_of_day")

        def search(self, query):
            raise NotImplementedError

    fake = FakeProvider()
    mds_module.market_data_service.providers = [fake]
    return fake


def test_no_exit_risk_alert_on_first_ever_check(isolated_db):
    import backend.portfolio.service as portfolio_service
    import backend.alerts.service as alerts_service

    _install_deteriorating_provider()
    portfolio_service.add_holding("TESTCO", shares=10, entry_price=100.0)

    fired = alerts_service.check_portfolio_exit_risk()
    assert fired == 0


def test_no_exit_risk_spam_on_repeated_unchanged_checks(isolated_db):
    import backend.portfolio.service as portfolio_service
    import backend.alerts.service as alerts_service

    _install_deteriorating_provider()
    portfolio_service.add_holding("TESTCO", shares=10, entry_price=100.0)

    alerts_service.check_portfolio_exit_risk()  # baseline
    fired_2 = alerts_service.check_portfolio_exit_risk()
    fired_3 = alerts_service.check_portfolio_exit_risk()
    fired_4 = alerts_service.check_portfolio_exit_risk()
    assert fired_2 == 0 and fired_3 == 0 and fired_4 == 0


def test_exit_risk_alert_fires_exactly_once_on_real_deterioration(isolated_db):
    """The core anti-spam requirement, specifically for the exit-risk
    path this time: a real LOW -> HIGH transition fires exactly one
    alert, and does not keep re-firing while the position remains at
    HIGH risk on every subsequent check."""
    import backend.portfolio.service as portfolio_service
    import backend.alerts.service as alerts_service

    fake = _install_deteriorating_provider()
    portfolio_service.add_holding("TESTCO", shares=10, entry_price=100.0)

    alerts_service.check_portfolio_exit_risk()  # baseline (LOW risk)

    fake.deteriorated = True
    fired_on_change = alerts_service.check_portfolio_exit_risk()
    assert fired_on_change == 1

    fired_after = alerts_service.check_portfolio_exit_risk()
    assert fired_after == 0

    visible_alerts = alerts_service.get_alerts()
    exit_risk_alerts = [a for a in visible_alerts if a["alert_type"] == "exit_risk"]
    assert len(exit_risk_alerts) == 1
    assert "risk changed" in exit_risk_alerts[0]["title"]
    assert len(exit_risk_alerts[0]["reasons"]) > 0


def test_exit_risk_alert_only_fires_for_medium_or_high_not_low_to_low_noise(isolated_db):
    """A transition that's still LOW (e.g. score fluctuates from 0 to 1
    due to minor noise) must not be treated as alert-worthy — only
    MEDIUM/HIGH transitions are material enough to surface."""
    from backend.database.db import db_cursor
    import backend.alerts.service as alerts_service
    import backend.portfolio.service as portfolio_service

    fake = _install_deteriorating_provider()
    portfolio_service.add_holding("TESTCO", shares=10, entry_price=100.0)
    alerts_service.check_portfolio_exit_risk()

    # Confirm the recorded baseline state is genuinely LOW before asserting silence.
    from backend.alerts.service import _get_last_known_value
    assert _get_last_known_value("TESTCO", "exit_risk") == "LOW"

    fired = alerts_service.check_portfolio_exit_risk()
    assert fired == 0


def test_run_all_alert_checks_covers_both_watchlist_and_portfolio(isolated_db):
    """Integration-level check: the combined entry point the scheduler
    actually calls must run BOTH checks and report both counts."""
    from datetime import datetime, timezone
    from backend.database.db import db_cursor
    import backend.alerts.service as alerts_service
    import backend.portfolio.service as portfolio_service

    _install_deteriorating_provider()
    with db_cursor() as cur:
        cur.execute("INSERT INTO watchlist (ticker, added_at, notes) VALUES ('TESTCO', ?, '')",
                    (datetime.now(timezone.utc).isoformat(),))
    portfolio_service.add_holding("TESTCO", shares=10, entry_price=100.0)

    result = alerts_service.run_all_alert_checks()
    assert "technical_alerts_fired" in result
    assert "exit_risk_alerts_fired" in result
