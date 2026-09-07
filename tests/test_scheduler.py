import builtins
import sys
import time

import pytest


@pytest.fixture()
def isolated_db():
    import os
    import tempfile
    from backend.config import settings
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    settings.DATABASE_PATH = tmp.name
    from backend.database.db import init_db
    init_db()
    yield tmp.name
    os.remove(tmp.name)


def test_scheduler_starts_and_stops_cleanly(isolated_db):
    from backend.scheduler import start_scheduler, stop_scheduler, get_scheduler_status

    started = start_scheduler(interval_minutes=60)
    assert started is True
    assert get_scheduler_status()["running"] is True

    stop_scheduler()
    assert get_scheduler_status()["running"] is False


def test_scheduler_runs_evaluation_job_immediately_on_startup(isolated_db):
    """The whole point of the scheduler is that accuracy tracking
    updates without a manual button click — it must actually execute,
    not just report 'running' while doing nothing."""
    from backend.scheduler import start_scheduler, stop_scheduler, get_scheduler_status

    start_scheduler(interval_minutes=60)
    time.sleep(4.0)  # bumped further — three jobs now registered (predictions + alerts + suggestions), more startup contention
    status = get_scheduler_status()
    assert status["run_count"] >= 1
    assert status["last_run_at"] is not None
    stop_scheduler()


def test_scheduler_degrades_gracefully_when_apscheduler_broken():
    """Same class of bug as the xgboost/torch OSError crashes — a
    broken or missing apscheduler install must not take down the whole
    app at startup, just disable the automatic-evaluation feature."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("apscheduler"):
            raise OSError("simulated broken apscheduler install")
        return real_import(name, *args, **kwargs)

    builtins.__import__ = fake_import
    try:
        sys.modules.pop("backend.scheduler", None)
        sys.modules.pop("apscheduler", None)
        import backend.scheduler as sched_module
        assert sched_module.SCHEDULER_AVAILABLE is False
        assert sched_module.start_scheduler() is False
    finally:
        builtins.__import__ = real_import
        sys.modules.pop("backend.scheduler", None)
        import backend.scheduler  # restore normal state for subsequent tests
