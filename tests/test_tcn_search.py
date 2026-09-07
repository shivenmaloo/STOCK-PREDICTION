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


def test_generated_candidates_are_unique(isolated_db):
    from backend.forecasting.tcn_search import generate_candidate_configs
    candidates = generate_candidate_configs("TESTCO", 5, n_new=5)
    assert len(candidates) == 5
    assert len({c.to_json() for c in candidates}) == 5


def test_generated_candidates_never_repeat_across_batches(isolated_db):
    """Real point of the grid-walk approach over random sampling: the
    search space gets covered systematically, not potentially re-rolled."""
    from backend.forecasting.tcn_search import generate_candidate_configs, record_trial

    batch1 = generate_candidate_configs("TESTCO", 5, n_new=3)
    for c in batch1:
        record_trial("TESTCO", 5, c, search_score=0.5, n_search_splits=5, n_search_trades=30)

    batch2 = generate_candidate_configs("TESTCO", 5, n_new=3)
    overlap = {c.to_json() for c in batch1} & {c.to_json() for c in batch2}
    assert overlap == set()


def test_best_config_tracks_the_highest_scoring_trustworthy_trial(isolated_db):
    from backend.forecasting.tcn_search import generate_candidate_configs, record_trial, get_best_config

    candidates = generate_candidate_configs("TESTCO", 5, n_new=3)
    record_trial("TESTCO", 5, candidates[0], search_score=0.52, n_search_splits=5, n_search_trades=40)
    record_trial("TESTCO", 5, candidates[1], search_score=0.58, n_search_splits=5, n_search_trades=42)
    record_trial("TESTCO", 5, candidates[2], search_score=0.55, n_search_splits=5, n_search_trades=38)

    best = get_best_config("TESTCO", 5)
    assert best["search_score"] == 0.58
    assert best["config"] == candidates[1]


def test_untrustworthy_high_score_does_not_become_best(isolated_db):
    """The single most important safeguard in this module: a trial
    scored on too few walk-forward splits must never become the
    tracked 'best' config, no matter how good its score looks — a
    high score from a tiny sample is exactly the kind of thing that
    looks like a real edge but is actually noise."""
    from backend.forecasting.tcn_search import generate_candidate_configs, record_trial, get_best_config

    trustworthy = generate_candidate_configs("TESTCO", 5, n_new=1)[0]
    record_trial("TESTCO", 5, trustworthy, search_score=0.58, n_search_splits=5, n_search_trades=40)

    suspicious = generate_candidate_configs("TESTCO", 5, n_new=1)[0]
    record_trial("TESTCO", 5, suspicious, search_score=0.99, n_search_splits=1, n_search_trades=2)

    best = get_best_config("TESTCO", 5)
    assert best["search_score"] == 0.58
    assert best["config"] == trustworthy


def test_no_best_config_when_nothing_recorded_yet(isolated_db):
    from backend.forecasting.tcn_search import get_best_config
    assert get_best_config("NEVERTRIED", 5) is None


def test_holdout_evaluation_recorded_alongside_search_score(isolated_db):
    from backend.forecasting.tcn_search import generate_candidate_configs, record_trial, record_holdout_evaluation, get_best_config

    config = generate_candidate_configs("TESTCO", 5, n_new=1)[0]
    record_trial("TESTCO", 5, config, search_score=0.60, n_search_splits=5, n_search_trades=40)
    record_holdout_evaluation("TESTCO", 5, holdout_score=0.51)

    best = get_best_config("TESTCO", 5)
    assert best["search_score"] == 0.60
    assert best["holdout_score"] == 0.51
    assert best["holdout_evaluated_at"] is not None


def test_all_trials_are_persisted_none_silently_discarded(isolated_db):
    from backend.forecasting.tcn_search import generate_candidate_configs, record_trial, get_trial_history

    candidates = generate_candidate_configs("TESTCO", 5, n_new=4)
    for c in candidates:
        record_trial("TESTCO", 5, c, search_score=0.5, n_search_splits=5, n_search_trades=30)

    history = get_trial_history("TESTCO", 5)
    assert len(history) == 4


def test_search_holdout_split_is_chronological_and_non_overlapping():
    from backend.forecasting.tcn_search import split_search_and_holdout
    search_end, holdout_start = split_search_and_holdout(1000, holdout_fraction=0.2)
    assert search_end == holdout_start == 800


def test_different_tickers_and_horizons_are_kept_fully_separate(isolated_db):
    from backend.forecasting.tcn_search import generate_candidate_configs, record_trial, get_best_config

    config_a = generate_candidate_configs("AAA", 5, n_new=1)[0]
    record_trial("AAA", 5, config_a, search_score=0.9, n_search_splits=5, n_search_trades=40)

    config_b = generate_candidate_configs("BBB", 5, n_new=1)[0]
    record_trial("BBB", 5, config_b, search_score=0.1, n_search_splits=5, n_search_trades=40)

    assert get_best_config("AAA", 5)["search_score"] == 0.9
    assert get_best_config("BBB", 5)["search_score"] == 0.1


def test_same_ticker_different_horizons_are_kept_separate(isolated_db):
    from backend.forecasting.tcn_search import generate_candidate_configs, record_trial, get_best_config

    config_5d = generate_candidate_configs("TESTCO", 5, n_new=1)[0]
    record_trial("TESTCO", 5, config_5d, search_score=0.9, n_search_splits=5, n_search_trades=40)

    config_20d = generate_candidate_configs("TESTCO", 20, n_new=1)[0]
    record_trial("TESTCO", 20, config_20d, search_score=0.1, n_search_splits=5, n_search_trades=40)

    assert get_best_config("TESTCO", 5)["search_score"] == 0.9
    assert get_best_config("TESTCO", 20)["search_score"] == 0.1


def test_config_round_trips_through_json():
    from backend.forecasting.tcn_search import TCNSearchConfig
    config = TCNSearchConfig(num_layers=5, kernel_size=2, dropout=0.3)
    restored = TCNSearchConfig.from_json(config.to_json())
    assert restored == config


def test_run_search_iteration_evaluates_candidates_and_tracks_best(isolated_db, monkeypatch):
    """The actual background-job entry point, tested with a fake
    tcn_service so this runs without needing real PyTorch — proves the
    orchestration logic itself (evaluate candidates, persist trials,
    track best, run the one-time holdout check) independent of whether
    real model training happens to work in this environment."""
    import sys
    import backend.forecasting
    import backend.forecasting.tcn_search as search_module

    class FakeTCNService:
        def is_available(self):
            return True

        def evaluate_config_on_search_period(self, ticker, horizon_days, config):
            score = 0.7 if config.kernel_size == 2 else 0.3
            return {"score": score, "n_splits": 5, "n_trades": 40}

        def evaluate_best_config_on_holdout(self, ticker, horizon_days, config):
            return {"score": 0.5, "n_splits": 3, "n_trades": 20}

    fake_module = FakeTCNService()
    # Patch BOTH the sys.modules entry (for a fresh `from X import Y`)
    # AND the already-imported parent package's cached attribute (for
    # when some other module — e.g. the API routes — already imported
    # the real tcn_service earlier in the same test session, which
    # caches it as an attribute on the `backend.forecasting` package
    # object regardless of what sys.modules says afterward).
    monkeypatch.setitem(sys.modules, "backend.forecasting.tcn_service", fake_module)
    monkeypatch.setattr(backend.forecasting, "tcn_service", fake_module, raising=False)

    result = search_module.run_search_iteration("TESTCO", 5, n_candidates=3)
    assert result["evaluated"] == 3
    assert result["holdout_checked"] is True

    best = search_module.get_best_config("TESTCO", 5)
    assert best["search_score"] == 0.7
    assert best["holdout_score"] == 0.5


def test_run_search_iteration_reports_unavailable_without_torch(isolated_db, monkeypatch):
    import sys
    import backend.forecasting
    import backend.forecasting.tcn_search as search_module

    class UnavailableTCNService:
        def is_available(self):
            return False

    fake_module = UnavailableTCNService()
    monkeypatch.setitem(sys.modules, "backend.forecasting.tcn_service", fake_module)
    monkeypatch.setattr(backend.forecasting, "tcn_service", fake_module, raising=False)
    result = search_module.run_search_iteration("TESTCO", 5, n_candidates=3)
    assert result["evaluated"] == 0
    assert "reason" in result
