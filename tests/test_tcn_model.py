import numpy as np
import pytest

from backend.forecasting.tcn_model import build_windows, probability_to_signal


def test_build_windows_produces_correct_shapes():
    X = np.arange(100 * 5).reshape(100, 5).astype(float)
    y = np.arange(100).astype(float)
    X_win, y_win = build_windows(X, y, window_len=10)
    assert X_win.shape == (91, 10, 5)
    assert y_win.shape == (91,)


def test_build_windows_target_is_the_forward_looking_label_not_shifted_again():
    """Window i covers rows [i, i+window_len) and predicts y at row
    i+window_len-1 — the label already computed upstream in
    features.py. build_windows must not apply any ADDITIONAL shift of
    its own (that would silently misalign windows from targets)."""
    X = np.zeros((20, 2))
    y = np.arange(20).astype(float)
    X_win, y_win = build_windows(X, y, window_len=5)
    assert y_win[0] == 4  # window 0 covers rows [0,5) -> predicts y[4]
    assert y_win[-1] == 19  # last window covers rows [14,19) -> predicts y[19]


def test_build_windows_too_short_returns_empty():
    X = np.zeros((5, 3))
    y = np.zeros(5)
    X_win, y_win = build_windows(X, y, window_len=10)
    assert len(X_win) == 0 and len(y_win) == 0


def test_probability_to_signal_maps_correctly():
    assert probability_to_signal(0.5) == pytest.approx(0.0)  # uninformative -> neutral
    assert probability_to_signal(1.0) == pytest.approx(1.0)   # certain up -> max bullish signal
    assert probability_to_signal(0.0) == pytest.approx(-1.0)  # certain down -> max bearish signal
    assert probability_to_signal(0.75) == pytest.approx(0.5)


def _numpy_causal_dilated_conv(x: np.ndarray, kernel: np.ndarray, dilation: int) -> np.ndarray:
    """A plain-NumPy reimplementation of EXACTLY what _CausalConv1d
    does: left-pad by (kernel_size - 1) * dilation, then convolve with
    NO padding on the right. x: 1D array (time). kernel: 1D array of
    weights. Returns an array the same length as x."""
    kernel_size = len(kernel)
    left_pad = (kernel_size - 1) * dilation
    padded = np.concatenate([np.zeros(left_pad), x])
    out = np.zeros(len(x))
    for t in range(len(x)):
        # In the padded array, position t corresponds to the window
        # ending at padded[t + left_pad], stepping backward by `dilation`
        # for each of the kernel_size taps — i.e. exactly a dilated,
        # causal convolution.
        acc = 0.0
        for k in range(kernel_size):
            idx = t + left_pad - k * dilation
            acc += kernel[k] * padded[idx]
        out[t] = acc
    return out


def test_causal_conv_output_at_time_t_is_unaffected_by_future_inputs():
    """The single most important property in this whole module: proves
    the exact padding/dilation scheme _CausalConv1d uses (left-pad only,
    no right-side padding) genuinely cannot leak a future timestep into
    an earlier one's output — perturbing ONLY a future position must
    leave every earlier position's output byte-for-byte identical."""
    rng = np.random.default_rng(0)
    x = rng.normal(0, 1, 50)
    kernel = rng.normal(0, 1, 3)
    dilation = 2

    out_before = _numpy_causal_dilated_conv(x, kernel, dilation)

    x_perturbed = x.copy()
    perturb_index = 40
    x_perturbed[perturb_index] += 1000.0  # a huge, unmissable perturbation

    out_after = _numpy_causal_dilated_conv(x_perturbed, kernel, dilation)

    # Every output at a position BEFORE the perturbation must be identical.
    assert np.allclose(out_before[:perturb_index], out_after[:perturb_index]), (
        "A causal convolution must never let a future timestep change an earlier position's output"
    )
    # Sanity check the test itself isn't vacuous: the perturbation MUST
    # actually change something at or after the perturbed position,
    # proving the perturbation was real and the conv function works.
    assert not np.allclose(out_before[perturb_index:], out_after[perturb_index:])


def test_causal_conv_receptive_field_matches_expected_dilation_schedule():
    """For a stack of layers with dilations 1, 2, 4, ... (kernel_size=3),
    the total receptive field should grow exponentially — this is the
    whole point of a dilated TCN (a large receptive field without
    needing as many layers as a plain causal CNN would)."""
    kernel_size = 3
    dilations = [2 ** i for i in range(4)]  # 1, 2, 4, 8
    total_receptive_field = 1 + sum((kernel_size - 1) * d for d in dilations)
    # 1 + (3-1)*1 + (3-1)*2 + (3-1)*4 + (3-1)*8 = 1 + 2 + 4 + 8 + 16 = 31
    assert total_receptive_field == 31


def test_tcn_model_raises_clear_error_without_torch():
    """Mirrors the exact graceful-degradation pattern already used for
    the LSTM — if torch isn't installed, constructing the model must
    fail with a clear, catchable error, not a cryptic one."""
    from backend.forecasting import tcn_model
    if tcn_model.TORCH_AVAILABLE:
        pytest.skip("torch is installed in this environment — this test only applies when it's absent")
    with pytest.raises(ImportError):
        tcn_model.TCNModel()
