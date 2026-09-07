"""
Shared test utilities.

`business_day_anchor()` fixes a real, previously-undetected fragility
that affected fixtures across many test files: `pd.date_range(end=X,
periods=N, freq="B")` silently returns FEWER than N dates whenever X
falls on a Saturday or Sunday (freq="B" only counts business days, and
a weekend endpoint doesn't count as one — so the backward count comes
up short). Every fixture anchored to `pd.Timestamp.now().normalize()`
was vulnerable to this and would only actually fail on a weekend,
which is exactly what happened the first time this suite was run on
one. Snapping the anchor to the most recent business day first makes
every one of those fixtures robust regardless of what day it's run.
"""
import pandas as pd


def business_day_anchor() -> pd.Timestamp:
    now = pd.Timestamp.now().normalize()
    if now.dayofweek >= 5:  # Saturday=5, Sunday=6
        now -= pd.Timedelta(days=now.dayofweek - 4)
    return now
