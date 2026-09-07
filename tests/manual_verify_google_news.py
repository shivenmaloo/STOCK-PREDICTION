"""
Run this on your own machine (not in any sandbox) to get the exact
NVDA/AAPL/MSFT verification report. From the stock-ai folder, with
your virtual environment active:

    python3 tests/manual_verify_google_news.py
"""
import sys
sys.path.insert(0, ".")

from backend.data.news_provider import GoogleNewsSearchProvider
from backend.news.service import NewsService

print("=" * 60)
print("GOOGLE NEWS — LIVE VERIFICATION")
print("=" * 60)

provider = GoogleNewsSearchProvider()
tickers = ["NVDA", "AAPL", "MSFT"]
google_results = {}

for ticker in tickers:
    result, diag = provider.get_news(ticker)
    google_results[ticker] = diag
    print(f"\n{ticker}:")
    print(f"  HTTP status:     {diag.http_status}")
    print(f"  Response size:   {diag.response_size_bytes} bytes")
    print(f"  RSS entries:     {diag.entries_found}")
    print(f"  Valid articles:  {diag.valid_articles}")
    print(f"  Status:          {diag.status}")
    if diag.publisher_breakdown:
        print(f"  Publishers:      {diag.publisher_breakdown}")
    if diag.error:
        print(f"  Error:           {diag.error}")

print("\n" + "=" * 60)
print("FULL PIPELINE (Google News + Yahoo fallback logic)")
print("=" * 60)

svc = NewsService()
for ticker in tickers:
    result = svc.get_analyzed_news(ticker)
    print(f"\n{ticker}: {len(result.data)} final articles, source='{result.source}', "
          f"fallback_used={getattr(result, 'fallback_used', None)}")

print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print("Google News:")
for t in tickers:
    d = google_results[t]
    print(f"  {t} → {d.valid_articles} results ({d.status})")
print(f"\nYahoo fallback: {'Used' if any(getattr(svc.get_analyzed_news(t), 'fallback_used', False) for t in tickers) else 'Not used'}")
