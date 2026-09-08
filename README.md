# Stock Intelligence Platform

A local stock analysis platform combining **market data, technical analysis, fundamentals, news, machine learning, backtesting, and risk analysis** into one system.

The project focuses on building a transparent platform where predictions and analysis can be tested, explained, and traced back to the underlying data.

## 🚀 Features

* 📊 **Market Analysis** — Interactive charts, 40+ technical indicators, watchlists, market regimes, and sector analysis
* 📰 **Fundamentals & News** — SEC filings, financial trends, multi-source news, contextual sentiment, and impact analysis
* 🔎 **Stock Scanner** — Screens ~150 liquid US stocks using technical and fundamental filters
* 🤖 **ML Predictions** — XGBoost, Random Forest, Gradient Boosting, LSTM, and accuracy-weighted ensemble models
* 📈 **Backtesting** — Walk-forward validation, equity curves, drawdown, win rates, and benchmark comparisons
* 🎯 **Risk Analysis** — Kelly-based sizing, ATR-based risk levels, prediction intervals, and out-of-distribution warnings
* 💼 **Portfolio & Alerts** — Portfolio tracking, exit-risk monitoring, background monitoring, and anti-spam alerts
* 📉 **Options Research** — Implied volatility, IV rank, put/call skew, and volatility surfaces
* 🧪 **Reliability Testing** — Tests for look-ahead bias, model accuracy, backtesting, data quality, and system reliability

## 🛠️ Tech Stack

**Python • FastAPI • Pandas • NumPy • scikit-learn • XGBoost • PyTorch • SQLite • JavaScript • SEC EDGAR • pytest**

## 🔮 Future Improvements

* Improve **model evaluation and calibration** on unseen market data
* Develop **market-regime-aware models**
* Add **macroeconomic, options, and cross-market features**
* Build a **historical point-in-time news dataset** for ML integration
* Expand monitoring for **model drift and performance changes**
* Improve **visualizations and experiment tracking**
* Expand the scanner beyond the current **~150-stock universe**
* Continue testing for **data leakage, look-ahead bias, and model reliability**

## 🎯 Project Goal

The goal is to build a research platform that can explain **what the data shows, how models reach their conclusions, how uncertain those conclusions are, and whether they actually perform on data they have never seen before.**
