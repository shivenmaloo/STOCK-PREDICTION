import pytest

from backend.options.pricing import black_scholes_call_price, solve_implied_volatility


@pytest.mark.parametrize("true_sigma", [0.15, 0.25, 0.40, 0.80, 1.5])
def test_iv_solver_recovers_exact_volatility_round_trip(true_sigma):
    """The core correctness proof: price a call at a KNOWN volatility,
    then solve backward from that price and confirm it recovers the
    exact same volatility. This is the standard way to validate an
    IV solver — if it can't round-trip its own pricing model, nothing
    built on top of it can be trusted."""
    S, K, T, r = 100.0, 105.0, 0.25, 0.04
    price = black_scholes_call_price(S, K, T, r, true_sigma)
    recovered = solve_implied_volatility(price, S, K, T, r)
    assert recovered is not None
    assert abs(recovered - true_sigma) < 1e-4


def test_deep_itm_option_recovers_correctly():
    S, K, T, r = 100.0, 50.0, 0.25, 0.04
    price = black_scholes_call_price(S, K, T, r, 0.3)
    recovered = solve_implied_volatility(price, S, K, T, r)
    assert abs(recovered - 0.3) < 1e-3


def test_price_below_intrinsic_value_returns_none_not_fabricated_iv():
    """An arbitrage-violating price (below intrinsic value) has no
    real volatility that could produce it — must return None honestly,
    never a made-up number."""
    S, K, T, r = 100.0, 50.0, 0.25, 0.04
    intrinsic = max(0, S - K)
    below_intrinsic_price = intrinsic - 1.0
    assert solve_implied_volatility(below_intrinsic_price, S, K, T, r) is None


def test_zero_or_negative_price_returns_none():
    S, K, T, r = 100.0, 105.0, 0.25, 0.04
    assert solve_implied_volatility(0.0, S, K, T, r) is None
    assert solve_implied_volatility(-5.0, S, K, T, r) is None


def test_zero_time_to_expiry_price_equals_intrinsic_value():
    price = black_scholes_call_price(100, 90, 0, 0.04, 0.3)
    assert price == 10.0  # max(0, 100-90), regardless of volatility


def test_zero_volatility_price_equals_intrinsic_value():
    price = black_scholes_call_price(100, 90, 0.25, 0.04, 0.0)
    assert price == 10.0


def test_price_above_what_max_iv_could_produce_returns_none():
    """A price so extreme that not even IV_MAX (5.0) could explain it
    is not bracketed by the solver's search range — must return None,
    not silently clamp to IV_MAX and imply a false precision."""
    S, K, T, r = 100.0, 105.0, 0.25, 0.04
    absurdly_high_price = S + 1000  # far beyond anything a real option could be worth
    assert solve_implied_volatility(absurdly_high_price, S, K, T, r) is None


def test_call_price_increases_monotonically_with_volatility():
    """A basic sanity property of the Black-Scholes model itself —
    higher volatility must never produce a lower call price."""
    S, K, T, r = 100.0, 100.0, 0.5, 0.04
    prices = [black_scholes_call_price(S, K, T, r, sigma) for sigma in [0.1, 0.2, 0.3, 0.4, 0.5]]
    assert prices == sorted(prices)
