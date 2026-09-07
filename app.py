"""
Single-command launcher: `python app.py`

Note on the environment variables set below (before any other import):
PyTorch's CPU thread pool can silently deadlock on macOS — no error,
no crash, just an infinite hang — when it initializes in a process
where other libraries (numpy, scikit-learn, XGBoost) have already set
up their own BLAS/OpenMP threading. This was found via real testing:
random_forest/gradient_boosting/xgboost all completed in seconds, but
the LSTM (the only PyTorch-based model) hung indefinitely every time,
right at its first training call. Forcing every library to use a
single thread removes the conflicting-thread-pool problem entirely.
This does mean none of these libraries use multi-core parallelism
internally anymore — an acceptable tradeoff, since the dataset sizes
here are small enough that single-threaded execution still finishes
in seconds (confirmed: 6-8s for the tree-based models even before this
change), and a slow-but-correct model beats an indefinitely hung one.

Note on `reload`: live-reload is ON, but scoped to only watch the
actual source code directories (backend/, frontend/) — NOT the whole
project folder. This app writes its own files while running (the
SQLite price cache in data/, trained models in models/), and watching
those too would trick the reloader into restarting the server
mid-request every time a prediction finishes and saves its results
(which showed up as "Failed to fetch" after a long wait). Scoping the
watched directories keeps live-reload working for actual code edits
without that false-positive restart problem.
"""
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")  # tolerate duplicate OpenMP runtimes (torch's bundled copy + Homebrew's libomp) instead of deadlocking on them

from pathlib import Path

import uvicorn

from backend.config import settings

PROJECT_ROOT = Path(__file__).resolve().parent

if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=True,
        reload_dirs=[str(PROJECT_ROOT / "backend"), str(PROJECT_ROOT / "frontend")],
    )
