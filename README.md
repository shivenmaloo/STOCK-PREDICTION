# Stock AI Research Terminal

A local, personal stock-research dashboard. It pulls public market data,
computes technical indicators, and explains what it sees in plain
English — it does **not** claim to predict the market with certainty,
and it never tells you to buy or sell anything.

This is the **complete five-phase build**. What works right now:

**Phase 1 — core terminal**
- Search any US-listed ticker (stocks, ETFs, indexes)
- A watchlist you can add/remove tickers from
- A dashboard with major index snapshots (SPY, QQQ, DIA, IWM, VIX) and your watchlist
- A Stock Analyzer page with an interactive candlestick chart (SMA 50/200, Bollinger Bands, volume) plus a genuinely live TradingView chart alongside it
- A full technical-indicator engine (moving averages, RSI, MACD, stochastic, ATR, ADX, OBV, and more) with a plain-English interpretation, not just raw numbers
- **Market data source selection is quality-scored, not order-based** — yfinance and Stooq (the only two free, legitimate OHLCV sources available) are both queried on every cache miss, scored on freshness/completeness/coverage, and the genuinely better result wins — visible in a "Data source comparison" panel. Reuters/Bloomberg/CNBC/Seeking Alpha/MarketWatch don't offer free structured price data, so they aren't (and can't honestly be) part of this comparison — they're used for news instead, where they do have real feeds
- Local SQLite caching so you're not re-downloading the same history every time
- Honest data-quality reporting: every response tells you the source, whether it's real-time/delayed/end-of-day, and whether a provider failed — nothing is ever faked

**Phase 2 — fundamentals, news, market context, scanner, SEC filings**
- A 0–100 fundamental score (growth, profitability, valuation, financial health), fully explained, on the Stock Analyzer page
- **SEC EDGAR integration** — real filings (10-K, 10-Q, 8-K, DEF 14A, Form 4) with direct links to the official documents, plus a financial-trend narrative generated from SEC's own XBRL data (the exact figures companies tag in their filings) comparing periods YoY — e.g. "Revenue grew 21% YoY, but operating margin declined from 27% to 24%," sourced, not estimated
- **Multi-source news** — combines yfinance's aggregation with a Google News search (a genuinely different pipeline that surfaces real, independently-attributed publishers like Reuters, Bloomberg, and individual newsrooms — not another Yahoo-owned feed); near-duplicate headlines from different outlets are merged with a note on who else covered it, and sources are tagged by tier (primary/major press/other)
- Contextual news sentiment: headlines are split on contrast words ("but", "however", "despite"...) and the clause after the contrast is weighted more heavily, so "revenue increased but guidance was reduced" correctly scores bearish instead of just keyword-matching "increased" as positive
- News category classification (earnings, guidance, M&A, lawsuits, analyst ratings, macro, and more) and a -100..100 impact score with a short/medium/long-term horizon
- A **Market** page: rules-based bull/bear regime classification (SPY/QQQ/DIA/IWM trend + VIX) and sector rankings via the SPDR sector ETFs, including a rotation signal (accelerating/decelerating/steady) per sector
- A **News** page aggregating analyzed headlines across your whole watchlist
- A **Scanner** page with plain-English quick-scan presets (Bullish Momentum, Oversold, Unusual Volume, Steady Uptrend, Pullback in an Uptrend) plus a custom filter builder, screening ~150 liquid US stocks in one batched request — every match shows exactly which criteria it satisfied

Later phases (ML predictions, alerts, portfolio tracking, backtesting)
are scaffolded in the project structure but not yet implemented — see
**Roadmap** below.

---

## 1. Requirements

- **Python 3.10+** (developed against 3.12)
- macOS, Linux, or Windows — everything runs locally, no cloud account needed
- Internet access (for pulling market data from Yahoo Finance / Stooq)

## 2. Installation

```bash
cd stock-ai
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

> Phase 1 only needs the first block of `requirements.txt` (fastapi,
> uvicorn, yfinance, pandas, numpy...). The rest of the file installs
> the ML/news/scheduling libraries later phases will use, so you only
> have to run `pip install` once.

## 3. API key setup (optional)

Phase 1 works with **zero configuration** — yfinance and Stooq need no
API key. If you want to unlock optional data sources later, copy the
example env file and fill in what you have:

```bash
cp .env.example .env
```

Every key in `.env` is optional and additive. Never commit `.env` —
it's already in `.gitignore`.

## 4. Starting the application

```bash
python app.py
```

or, equivalently:

```bash
uvicorn backend.main:app --reload --reload-dir backend --reload-dir frontend
```

Live-reload is on (edit code, see it reflected without restarting
manually) but scoped to only watch `backend/` and `frontend/` — not
the whole project folder. This app writes its own files while running
(the SQLite price cache in `data/`, trained ML models in `models/`),
and watching those too would trick the reloader into restarting the
server mid-request right when a prediction finishes and saves its
results (showing up as "Failed to fetch" after a long wait). Scoping
the watched directories fixes that while keeping live-reload for
actual code edits.

Then open **http://localhost:8000** in your browser. The database
(`data/stock_ai.db`) and its tables are created automatically on first
run.

## 5. How to add a stock

Go to **Watchlist**, type a ticker (e.g. `NVDA`) or a company name into
the box, and click **Add**. Typing a plain ticker symbol adds it
directly; typing anything else triggers a search so you can pick the
right match. Click any ticker in a table to jump straight to its
Stock Analyzer page.

## 6. How the technical analysis works

For every ticker, the backend computes ~40 indicator columns (moving
averages, RSI, MACD, stochastic, ATR, Bollinger Bands, ADX, OBV,
relative volume, drawdown, and more) directly with pandas — no black
box. It then runs a small rules-based interpretation layer that turns
the numbers into a sentence, e.g.:

> "RSI is 63, price is above the 50-day and 200-day moving averages,
> and relative volume is 1.8x average. This supports a moderately
> bullish momentum regime."

This interpretation is **descriptive, not predictive** — it summarizes
what the indicators currently show, not what will happen next.
Machine-learning forecasts with confidence scores arrive in Phase 3.

## 7. How alerts work

Not yet implemented. Phase 4 adds a background scheduler that checks
your watchlist during market hours and raises an alert only when a
signal changes materially (not on every tick).

## 8. How backtesting works

Not yet implemented. Phase 5 adds walk-forward validation, an equity
curve, and comparisons against buy-and-hold SPY/QQQ, with an explicit
`PAST PERFORMANCE DOES NOT GUARANTEE FUTURE RESULTS` label on every
result.

## 9. How to train models

Not yet implemented — arrives in Phase 3 alongside XGBoost/LSTM
prediction models and a training interface.

## 10. How to interpret confidence scores

Not applicable yet in Phase 1 (no ML models are running). When Phase 3
lands, every prediction will show a confidence percentage, a range
(not a single point estimate), and which of the underlying models
agree or disagree — the app is designed to say "NEUTRAL — LOW
CONFIDENCE" outright when models disagree, rather than forcing a
directional call.

## 11. Known data limitations (Phase 1)

- **yfinance** data is typically delayed ~15 minutes, not real-time.
  This is shown in the UI as `delayed 15m`.
- **Stooq** (the automatic fallback if yfinance fails or rate-limits)
  provides end-of-day daily bars only — no live quotes, no intraday.
- If both providers fail for a ticker, the app shows an explicit error
  instead of a blank chart or a fabricated number.
- Historical data is cached locally for 6 hours (configurable via
  `HISTORICAL_CACHE_TTL_HOURS` in `.env`) to avoid hammering the
  provider; the UI always reports whether a response came from cache
  or a live fetch.
- Fundamentals, news, and macro data are not wired up yet (Phase 2).

---

## Roadmap

**Predictions & Models (Phase 3) — genuine walk-forward validated ML predictions:**
- **No look-ahead bias, verified two ways**: the walk-forward framework was tested against synthetic data with a real planted signal (models correctly learn and validate well above chance) and against pure noise (models correctly report ~50% accuracy — no fabricated skill). Every training split's data strictly precedes its test split; the last `horizon` days of any dataset are dropped rather than given a fabricated target.
- **Model A** (Linear Regression, Random Forest, Gradient Boosting via scikit-learn) — always available.
- **Model B** (XGBoost) — available if installed.
- **Model C** (LSTM via PyTorch) — optional; gracefully reports "unavailable" rather than crashing if PyTorch isn't installed. See the PyTorch note below.
- **Model D (ensemble)** — weights come from each model's own walk-forward validated accuracy, not arbitrary numbers. If models genuinely disagree, the app reports NEUTRAL / low confidence rather than forcing a directional call — tested explicitly.
- **Risk sizing** — fractional Kelly Criterion derived from real walk-forward win-rate/win-loss statistics (refuses to suggest a size with fewer than 20 validated trades), plus ATR-based stop-loss distances scaled to the ticker's own volatility.
- **Prediction history & accuracy tracking** — every prediction is stored; once its horizon has passed, it's automatically evaluated against the real subsequent price action by a background scheduler (checks every 60 minutes, and once immediately on startup) — no manual clicking required, though a manual "Evaluate matured predictions" button is still there as a fallback.
- **Adaptive ensemble weighting** — this is what makes predictions genuinely improve with real use, honestly: every model's individual vote (not just the ensemble's final call) gets checked against reality once a prediction matures. That live, real track record is blended with the walk-forward backtest using statistical shrinkage — a single lucky/unlucky live prediction can't swing anything, but a real pattern over enough evaluated predictions does shift which models get more say in future predictions for that ticker.
- **Risk-profile personalization** (Conservative/Moderate/Aggressive) — the one form of "personalization" that's honest to build: it changes how much of a validated statistical edge you're willing to size into (Kelly fraction), never what the model actually predicts. Clicking around the app never influences the prediction itself.
- **Relaxed mode for recently-listed tickers** — a stock with less than ~1.2 years of trading history (recent IPOs/spinoffs like CoreWeave or SanDisk-post-spinoff) doesn't get refused outright; it gets a real walk-forward validated prediction using a scaled-down window, clearly labeled as relaxed mode with the exact number of trading days available, so you know to weight it as lower-confidence than a ticker with full history. Tickers with truly minimal history (under ~6 months) still get an honest refusal rather than a fabricated result.
- **Relative strength vs. the market** — every model now sees how a stock's own recent return compares to SPY's over the same window, not just its return in isolation. Computed with zero look-ahead risk (each historical date only ever uses the benchmark's price as of that same date) and degrades gracefully to the old behavior if the benchmark can't be fetched.
- **Out-of-distribution warning** — a direct response to a real limitation surfaced during development (see the Random Forest extrapolation discussion): if today's market conditions are genuinely unlike anything in the model's training history, the prediction now says so plainly rather than silently extrapolating. Verified with both a normal-conditions case (no warning) and an engineered extreme case (correctly flagged, with the specific feature and how many standard deviations out it is).
- **Recency-weighted final model** — the live deployed model now weights recent data more heavily than data from years ago (exponential decay, ~1-year half-life), while the walk-forward validation that scores each model stays completely untouched by this, since that must remain methodologically pure.
- **A real bug fix worth flagging**: while testing the out-of-distribution warning, discovered that every live prediction had been silently using a feature row stale by exactly the horizon length (e.g. a 5-day prediction was reading data from 5 trading days ago, not today) — a side effect of correctly excluding those same rows from the *training* matrix, which doesn't have a known target yet. Fixed and covered by a regression test that engineers an extreme price move and confirms the live prediction actually sees it.
- **News context (post-hoc, not a trained feature)** — every prediction now includes a live cross-check against recent news sentiment, and flags it prominently when the news genuinely disagrees with the model's own read. Deliberately kept out of training entirely: we don't have a point-in-time news archive, so feeding today's sentiment into historical training rows would be a real form of look-ahead bias (the model would appear to "know" news it couldn't have known on those past dates). This stays a live, independent second opinion — it never changes the model's own prediction, confidence, or weighting.

**Portfolio, alerts & exit-risk (Phase 4) — background monitoring that doesn't spam:**
- **Portfolio tracking** — manually enter holdings (ticker, shares, entry price); see live value, unrealized gain/loss, and allocation using the same market data pipeline as the rest of the app. If a holding's live price can't be fetched, the portfolio total shows as unavailable rather than a silently-wrong partial number.
- **Exit-risk engine** — watches your holdings for compounding red flags (moving-average breakdown, elevated volume on a down day, weak momentum, negative news, elevated volatility) and escalates LOW → MEDIUM → HIGH. The strongest thing it will ever say is "Review position" — it never recommends selling, by design.
- **Anti-spam alerts** — the background scheduler now checks the watchlist and portfolio every 15 minutes, but an alert only fires when something genuinely changed since the last check (a technical structure flip, a risk level escalating) — verified with a test that runs the same unchanged check five times in a row and confirms zero alerts fire, then confirms exactly one fires the moment a real change happens.
- Everything here builds directly on the same data/indicators/news pipeline from Phases 1-3 — no separate, parallel system to keep in sync.

**Backtesting, Settings, and a genuine audit pass (Phase 5):**
- **Backtesting engine** — simulates actually trading on the model's out-of-sample predictions over historical time, producing an equity curve, max drawdown, win rate, and a fair buy-and-hold comparison over the *exact same* period tested (an earlier bug in this comparison — measuring buy-and-hold over the full 5-year history while the strategy was only measured over the ~3.5 years actually traded — was found and fixed before ever reaching you). Every weighting and sizing decision only uses information genuinely available at that point in the simulated timeline — proven with the same kind of causality test used to validate walk-forward validation itself: two backtests identical up to a point, diverging completely afterward, produce byte-identical results up to that point.
- **Settings page** — default risk profile (persisted server-side, not tied to one browser), cache management, model/scheduler diagnostics, and browser notification permission — all backed by real endpoints, not placeholders.
- **A significant bug found during the audit pass**: the LSTM's live prediction had been silently broken since it was first built. Its architecture needs a sequence of prior days to build a proper temporal window, but the live prediction pipeline was only ever handing it a single row — meaning it had no history to work with and defaulted to a neutral prediction every single time, regardless of what the market was actually doing, with no error ever raised to reveal it. Found by tracing through exactly what a single-row input would produce, fixed by giving LSTM its own properly-windowed input while every other model keeps receiving just the single row it actually needs, and locked in with a test that would catch this exact regression if it ever crept back in.
- Also fixed in the same pass: the LSTM's saved model files weren't storing the normalization statistics needed to use them again later, so a cached prediction always skipped the LSTM entirely rather than risk a miscalibrated result. Now persisted alongside the model weights, so cached LSTM predictions actually work.

**A second, deeper round of hardening and a new AI Assistant:**
- **Backtesting interval explained and verified**: expanding-window walk-forward — trains on the first ~200 trading days, tests the next ~21 (about a month), folds that month's real outcome into training, and repeats. For a full 5-year history that's 43 sequential out-of-sample windows, confirmed to run in ~26 seconds with the real production settings (not a sped-up test override).
- **Scenario-tested, not just claimed**: verified the same ticker at two different horizons (5D and 20D) trains, caches, and predicts fully independently with zero collision. Stress-tested the database at 1,200 concurrent read/write operations across 12 threads and found zero errors — reported honestly rather than claiming to have "found and fixed" a bug that didn't actually manifest. Enabled SQLite's WAL mode anyway as a genuine best-practice hardening step for this app's exact usage pattern (a background writer plus a constantly-reading UI), since it's strictly better with no downside even without a reproduced failure.
- **AI Assistant** — a chat page for asking questions about the app or a specific result. Uses your own Anthropic API key (`ANTHROPIC_API_KEY` in `.env`, never hardcoded or stored in the database); the rest of the app works completely normally without one configured. Automatically attaches your most recently viewed prediction or backtest as context, so "why is this neutral?" gets a specific answer instead of a generic one. Explicitly instructed to never give financial advice, matching the rest of the app's behavior.

**Conformal prediction intervals** — evaluated a third-party ML notebook someone shared and adopted the one genuinely valuable technique in it: instead of the prediction range just being "the spread of what different models predicted," it's now also backed by a proper statistical method (split conformal prediction) using each model's *own* walk-forward residuals — giving an interval with an actual empirical coverage guarantee (e.g. "80% of the time, reality falls within this band"), verified with a genuinely out-of-sample train/holdout test, not just checked against the same data it was built from. Also added a naive-baseline transparency check per model ("does this actually beat just predicting no change at all?") — an honest sanity check that, in testing, correctly showed some models *don't* clear that bar, which is exactly the kind of thing this feature exists to surface rather than hide. Deliberately did NOT adopt that notebook's single static train/test split (walk-forward across ~40 windows is more rigorous), its un-normalized MACD feature (scale-dependent, we already avoid this), or its arbitrary fixed-weight composite score (our accuracy-driven ensemble weighting is more principled).

**Stock suggestions and a real UI restructure:**
- **Suggested from your tracked stocks** — a new Dashboard feature that ranks your own watchlist/portfolio by real signal strength, confidence, and recency, so you don't have to think of a ticker yourself before getting a read. Built on the exact same predictions the Predictions page produces — never a new parallel system, so a suggestion here means exactly what it would mean if you ran that ticker yourself. A background job keeps these fresh automatically (every 4 hours, deliberately not on startup, since this can mean real model training). Found and fixed a real bug while building it: a stale prediction was being silently dropped from the report entirely instead of being flagged either way — caught and fixed before shipping.
- **Dashboard rebuilt as a real grid**, not a single vertical column — Suggestions and Watchlist now sit side by side.
- **A genuinely collapsible sidebar** — one click shrinks it to a thin icon-only rail (with hover tooltips), and the choice is remembered across sessions.

### A note on XGBoost on macOS ("Library not loaded: @rpath/libomp.dylib")

XGBoost's compiled binary depends on the OpenMP runtime library
(`libomp`), which macOS doesn't include by default. If you see an
error mentioning `libomp.dylib`, install it via Homebrew:
```
brew install libomp
```
(If you don't have Homebrew, install it first from https://brew.sh)
Once installed, restart the app — no need to reinstall xgboost itself.
Without `libomp`, the app now correctly falls back to marking XGBoost
as unavailable rather than crashing on startup (a real bug caught and
fixed during development), but installing it gets you the full model.

### A note on installing PyTorch (optional, for the LSTM model)

PyTorch is a large dependency and doesn't always have a pre-built wheel
available for the newest Python versions right away. Try:
```
pip install torch
```
If that fails with "no matching distribution found," the app still
works fully — it just skips the LSTM model and uses the baseline +
XGBoost models instead, clearly noted in the Predictions page.

**Important**: if a `torch` install ever fails or is interrupted partway
(e.g. you run out of disk space mid-install, like happened during this
app's own development), it can leave a corrupted partial package behind
that causes a hard crash on import instead of a clean "not installed"
message. If PyTorch-related features start crashing unexpectedly after
a failed install attempt, run:
```
pip uninstall torch -y
```
before trying to install it again.



| Phase | Adds |
|---|---|
| 1 ✅ | Search, historical data, candlestick chart, technical indicators, watchlist, dashboard |
| 2 ✅ (this build) | Fundamentals, news + contextual sentiment, market regime, sector analysis, stock scanner |
| 3 ✅ (this build) | Walk-forward validated XGBoost/LSTM/ensemble predictions, Kelly-based risk sizing, prediction accuracy tracking |
| 4 ✅ (this build) | Background monitoring, alerts (anti-spam, fires only on material change), portfolio tracking, exit-risk detection |
| 5 ✅ (this build) | Backtesting engine, Settings page, and an audit pass that found and fixed a significant pre-existing bug (see below) |

### Notes on Phase 2's data limitations

- **Fundamentals** come from yfinance's `.info` endpoint, which is the
  least reliable data source in the whole app — expect occasional
  failures. Results are cached in SQLite for 3 days so a flaky fetch
  doesn't force you to keep retrying, and a stale cache is served
  (clearly labeled `WARNING`) rather than nothing at all if a live
  refresh fails.
- **News sentiment/category/impact scoring is a transparent, rules-based
  system** — a curated lexicon plus contrast-conjunction detection —
  not a trained model. It's tuned for common financial-news phrasing
  and documented as such; it will miss subtlety a human would catch.
- **The Scanner's universe is a curated list of ~150 liquid US stocks**
  (large/mid-cap names across every sector, plus major ETFs), not the
  full market — this keeps the scan to a single batched request so it
  stays fast and doesn't get rate-limited. Fundamental filters (market
  cap, P/E, revenue growth) only apply to tickers that already have
  cached fundamentals; the response tells you how many were skipped
  for that reason.
- **SEC data comes straight from SEC EDGAR's free public API** — no
  key required. Company lookup uses the same ticker-search endpoint
  that powers sec.gov/search-filings (a single small request), falling
  back to the full ticker directory only if that doesn't resolve.
  Results are cached for 3 days after first load. Financial trend
  analysis relies on companies tagging their filings with standard
  XBRL concepts; smaller or newly-public companies sometimes use
  nonstandard tags, in which case you'll see "no revenue data found"
  rather than a guessed number.
- **News source priority is Google News first, then direct-outlet feeds
  (Seeking Alpha, CNBC, MarketWatch), with Yahoo as a genuine last
  resort** — never silent. Every fetch attempt (successful or not)
  produces a diagnostic entry with HTTP status, response size, entry
  count, and error message, visible in a "News source diagnostics"
  panel under every news list, and logged server-side with
  `[NEWS]`-prefixed lines in the terminal you started the app from.
  General-topic feeds (CNBC, MarketWatch) are filtered so only
  headlines that actually name the ticker/company are kept — a raw
  front-page feed would otherwise return mostly-unrelated stories.
  **Reuters and Bloomberg have no free public RSS/API** (both
  discontinued theirs years ago) — their content still surfaces
  through Google News' own aggregation, just not via a direct feed.
- **The Stock Analyzer includes a genuinely live TradingView chart**
  alongside the app's own indicator-annotated chart. This is a
  client-side embed that loads directly in your browser using your own
  internet connection — it never goes through the app's backend, so
  it's unaffected by any of the data-source caveats above.

## Project structure

```
stock-ai/
├── backend/
│   ├── main.py            # FastAPI app + static file serving
│   ├── config.py          # .env-driven settings
│   ├── api/routes.py      # REST endpoints
│   ├── data/               # provider abstraction + yfinance/Stooq + caching service
│   ├── indicators/         # technical indicator math + interpretation layer
│   ├── database/db.py     # SQLite schema + connection helpers
│   ├── models/ forecasting/ news/ alerts/ backtesting/   # scaffolded for later phases
├── frontend/
│   ├── index.html
│   ├── css/style.css
│   └── js/app.js
├── data/                   # SQLite database file lives here
├── tests/                  # pytest suite
├── requirements.txt
├── .env.example
└── app.py                  # `python app.py` entrypoint
```

## Running tests

```bash
pytest tests/ -v
```

Tests cover indicator math and every API endpoint using a fake data
provider, so they run offline and don't depend on live market data.

---

## Experimental: TCN Research module

A separate, explicitly experimental research feature — a causal
Temporal Convolutional Network plus a configurable risk-management
pipeline, kept fully separate from the main prediction ensemble so it
never affects the app's core predictions.

- **Causal by construction, not just by claim** — left-padded, dilated
  convolutions with zero right-side padding. Proven with a pure-math
  test: perturbing a future timestep by 1000x leaves every earlier
  output byte-identical.
- **Risk-map pipeline** — probability → signal → dead-zone →
  volatility scaling → exposure cap, every stage independently
  toggleable (this is what makes the 5-way comparison possible).
- **An ongoing configuration search with real anti-overfitting
  safeguards** — not a "try things, keep the best" loop. A config
  scored on too few walk-forward splits can never become the tracked
  "best," proven by test (a suspicious 0.99 score from 1 split loses
  to a real 0.58 from 5 splits). A search/holdout split means a config
  is never validated on the same data used to pick it, and the search
  and holdout scores are always shown side by side so a generalization
  gap is visible, not hidden.
- **5-way backtest comparison** — buy-and-hold vs. raw model signal
  vs. +dead-zone vs. +vol-scaling vs. +vol-scaling+exposure-cap, with
  the same transaction-cost assumption as the main backtest engine.
  Reuses the app's existing 19-feature stationary set rather than raw
  OHLCV (raw price levels are non-stationary — see the reasoning in
  `backend/forecasting/features.py` and `tcn_model.py`).
- **Fully optional** — if PyTorch isn't installed, every endpoint
  reports "unavailable" cleanly; nothing else in the app is affected.
- A background job runs a small search iteration every 6 hours,
  deliberately the most conservative interval in the app, since each
  candidate means real model training.

Find it under **TCN Research** in the app's menu.

---

## Volatility Surface (real options data)

A real Black-Scholes implied volatility engine, scoped specifically to
what actually informs stock-direction prediction — not a full options
trading toolkit.

- **Real math, not a trained model** — Black-Scholes pricing plus
  Brent's method (`scipy.optimize.brentq`) to solve for the volatility
  that explains an observed market price. Proven with a round-trip
  test: price a call at a known volatility, solve backward, recover
  the exact same number.
- **Genuine data quality filtering** — drops zero bid/ask, low
  volume/open-interest, wide bid-ask spreads (>25% of mid-price), and
  arbitrage-violating quotes (priced below intrinsic value) before any
  IV solving happens, not after.
- **2D surface interpolation** — sparse (expiry, moneyness, IV) points
  smoothed onto a grid via cubic `griddata` with a linear fallback for
  edge NaNs.
- **ATM IV, put/call skew, and IV rank** — IV rank needs 52 weeks of
  history, which (like news sentiment above) can't be faked from a
  single reading — real ATM IV readings are logged starting now, and
  rank becomes meaningful once enough have accumulated.
- **Deliberately excludes** Greeks, SVI/SABR parametric fitting, and a
  dedicated time-series database — those serve pricing/hedging an
  option itself, not predicting where the underlying stock is headed.

Find it under **Volatility Surface** in the app's menu. Not every
ticker has listed options — that's reported honestly, not hidden.

---

## Financial safety note

This is a research tool, not a trading system. It never displays
guarantees ("guaranteed profit", "definitely buy") — only probabilistic,
evidence-backed language. Nothing in this application should be treated
as financial advice, and no output should be used as the sole basis for
a real trading decision. **Past performance does not guarantee future
results.**
