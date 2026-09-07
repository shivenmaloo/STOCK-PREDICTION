import os
import tempfile

import numpy as np
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


def test_no_rank_without_enough_history(isolated_db):
    from backend.options.iv_history import get_iv_rank
    result = get_iv_rank("TESTCO", 0.30)
    assert result["available"] is False
    assert result["n_readings"] == 0


def test_rank_correctly_identifies_historically_elevated_iv(isolated_db):
    from backend.options.iv_history import log_iv_reading, get_iv_rank
    for r in np.linspace(0.15, 0.45, 25):
        log_iv_reading("TESTCO", float(r), 0.02)

    result = get_iv_rank("TESTCO", 0.44)
    assert result["available"] is True
    assert result["percentile"] > 80
    assert result["interpretation"] == "historically elevated"


def test_rank_correctly_identifies_historically_low_iv(isolated_db):
    from backend.options.iv_history import log_iv_reading, get_iv_rank
    for r in np.linspace(0.15, 0.45, 25):
        log_iv_reading("TESTCO", float(r), 0.02)

    result = get_iv_rank("TESTCO", 0.16)
    assert result["percentile"] < 20
    assert result["interpretation"] == "historically low"


def test_rank_in_typical_range_for_a_mid_range_reading(isolated_db):
    from backend.options.iv_history import log_iv_reading, get_iv_rank
    for r in np.linspace(0.15, 0.45, 25):
        log_iv_reading("TESTCO", float(r), 0.02)

    result = get_iv_rank("TESTCO", 0.30)
    assert result["interpretation"] == "in its typical range"


def test_logging_none_iv_is_silently_skipped(isolated_db):
    from backend.options.iv_history import log_iv_reading, get_iv_rank
    log_iv_reading("TESTCO", None, None)
    result = get_iv_rank("TESTCO", 0.30)
    assert result["n_readings"] == 0


def test_different_tickers_have_independent_history(isolated_db):
    from backend.options.iv_history import log_iv_reading, get_iv_rank
    for r in np.linspace(0.10, 0.20, 25):
        log_iv_reading("LOWVOL", float(r), 0.01)
    for r in np.linspace(0.50, 0.80, 25):
        log_iv_reading("HIGHVOL", float(r), 0.05)

    low_result = get_iv_rank("LOWVOL", 0.15)
    high_result = get_iv_rank("HIGHVOL", 0.65)
    assert low_result["max_observed"] < high_result["min_observed"]


def test_get_rank_without_current_iv_reports_unavailable(isolated_db):
    from backend.options.iv_history import get_iv_rank
    result = get_iv_rank("TESTCO", None)
    assert result["available"] is False
