import builtins
import sys


def test_xgboost_oserror_does_not_crash_app():
    """Real bug found via manual testing on macOS: XGBoost's compiled
    binary depends on the system OpenMP library (libomp), which isn't
    included by default. When it's missing, `import xgboost` fails
    with OSError ('Library not loaded: @rpath/libomp.dylib'), not
    ImportError — the original narrow `except ImportError` guard let
    this propagate and crash the whole app at startup instead of
    marking XGBoost as simply unavailable."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "xgboost":
            raise OSError(
                "dlopen(.../libxgboost.dylib): Library not loaded: @rpath/libomp.dylib"
            )
        return real_import(name, *args, **kwargs)

    builtins.__import__ = fake_import
    try:
        sys.modules.pop("backend.forecasting.models", None)
        sys.modules.pop("xgboost", None)
        import backend.forecasting.models as models_module
        assert models_module.XGBOOST_AVAILABLE is False
    finally:
        builtins.__import__ = real_import
        sys.modules.pop("backend.forecasting.models", None)
        import backend.forecasting.models  # restore normal state for subsequent tests


def test_torch_oserror_does_not_crash_app():
    """Same class of bug, same fix, applied to the optional torch import."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "torch":
            raise OSError("simulated broken native torch install")
        return real_import(name, *args, **kwargs)

    builtins.__import__ = fake_import
    try:
        sys.modules.pop("backend.forecasting.lstm_model", None)
        sys.modules.pop("torch", None)
        import backend.forecasting.lstm_model as lstm_module
        assert lstm_module.TORCH_AVAILABLE is False
    finally:
        builtins.__import__ = real_import
        sys.modules.pop("backend.forecasting.lstm_model", None)
        import backend.forecasting.lstm_model  # restore normal state
