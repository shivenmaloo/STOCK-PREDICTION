from backend.forecasting.risk_map import (
    RiskMapConfig, process_signal, apply_dead_zone, apply_volatility_scaling, apply_exposure_cap,
)


def test_signal_transform_matches_the_standard_formula():
    result = process_signal(0.8, forecast_volatility=0.02, config=RiskMapConfig())
    assert result["raw_signal"] == 0.6  # 2*0.8 - 1


def test_dead_zone_kills_a_weak_signal():
    result = process_signal(0.52, forecast_volatility=0.02, config=RiskMapConfig(dead_zone_threshold=0.1))
    assert result["after_dead_zone"] == 0.0


def test_dead_zone_passes_through_a_strong_signal():
    result = process_signal(0.8, forecast_volatility=0.02, config=RiskMapConfig(dead_zone_threshold=0.1))
    assert result["after_dead_zone"] == result["raw_signal"]


def test_calmer_stock_gets_sized_up_relative_to_a_volatile_one():
    calm = process_signal(0.8, forecast_volatility=0.005, config=RiskMapConfig(target_volatility=0.02, min_volatility=0.005))
    volatile = process_signal(0.8, forecast_volatility=0.10, config=RiskMapConfig(target_volatility=0.02, max_volatility=0.10))
    assert abs(calm["after_vol_scaling"]) > abs(volatile["after_vol_scaling"])


def test_missing_volatility_skips_scaling_without_crashing():
    result = process_signal(0.8, forecast_volatility=None, config=RiskMapConfig())
    assert result["after_vol_scaling"] == result["after_dead_zone"]


def test_vol_scaling_can_be_disabled_via_config():
    with_scaling = process_signal(0.8, forecast_volatility=0.10, config=RiskMapConfig(vol_scaling_enabled=True))
    without_scaling = process_signal(0.8, forecast_volatility=0.10, config=RiskMapConfig(vol_scaling_enabled=False))
    assert with_scaling["after_vol_scaling"] != without_scaling["after_vol_scaling"]
    assert without_scaling["after_vol_scaling"] == without_scaling["after_dead_zone"]


def test_exposure_cap_clips_an_extreme_position():
    result = process_signal(0.99, forecast_volatility=0.001, config=RiskMapConfig(min_volatility=0.001, max_position_pct=0.20))
    assert abs(result["final_position"]) <= 0.20 + 1e-9


def test_exposure_cap_respects_negative_direction_too():
    result = process_signal(0.01, forecast_volatility=0.001, config=RiskMapConfig(min_volatility=0.001, max_position_pct=0.20))
    assert result["final_position"] == -0.20


def test_zero_volatility_does_not_produce_infinity_or_nan():
    result = process_signal(0.9, forecast_volatility=0.0, config=RiskMapConfig(min_volatility=0.005))
    assert abs(result["after_vol_scaling"]) < 1000
    assert result["after_vol_scaling"] == result["after_vol_scaling"]  # NaN != NaN, so this fails only if it's NaN


def test_stage_subsetting_reproduces_raw_signal_only_variant():
    """This is what makes the 5-way backtest comparison possible —
    passing only {'transform'} must produce exactly what 'the raw
    model signal, no risk management at all' should look like."""
    result = process_signal(0.8, forecast_volatility=0.02, config=RiskMapConfig(), stages={"transform"})
    assert result["final_position"] == result["raw_signal"]


def test_stage_subsetting_reproduces_dead_zone_only_variant():
    result = process_signal(0.8, forecast_volatility=0.02, config=RiskMapConfig(), stages={"transform", "dead_zone"})
    assert result["final_position"] == result["after_dead_zone"]


def test_apply_dead_zone_boundary_is_exclusive_of_threshold_itself():
    assert apply_dead_zone(0.1, threshold=0.1) == 0.1  # exactly at threshold: not zeroed (strictly less-than check)
    assert apply_dead_zone(0.099, threshold=0.1) == 0.0


def test_apply_exposure_cap_is_a_pure_symmetric_clip():
    config = RiskMapConfig(max_position_pct=0.15)
    assert apply_exposure_cap(0.5, config) == 0.15
    assert apply_exposure_cap(-0.5, config) == -0.15
    assert apply_exposure_cap(0.05, config) == 0.05  # within bounds, unchanged
