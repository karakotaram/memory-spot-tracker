"""Fetch 1-week total returns for equities via yfinance."""

import logging
from typing import Optional

import yfinance as yf

logger = logging.getLogger(__name__)


def fetch_week_return(ticker: str) -> Optional[dict]:
    """Fetch 1-week total return (5 trading days) using adjusted close."""
    try:
        hist = yf.Ticker(ticker).history(period="1mo", interval="1d", auto_adjust=True)
    except Exception as e:
        logger.warning(f"Failed to fetch {ticker}: {e}")
        return None

    if hist is None or hist.empty or len(hist) < 6:
        logger.warning(f"Insufficient history for {ticker}: {0 if hist is None else len(hist)} points")
        return None

    # With auto_adjust=True, 'Close' is already total-return adjusted (splits+dividends).
    latest_close = float(hist["Close"].iloc[-1])
    week_ago_close = float(hist["Close"].iloc[-6])
    return_pct = (latest_close / week_ago_close - 1) * 100
    as_of = hist.index[-1].strftime("%Y-%m-%d")

    return {
        "ticker": ticker,
        "price": latest_close,
        "return_1w": return_pct,
        "as_of": as_of,
    }


def fetch_week_returns(tickers: list[str]) -> list[dict]:
    """Fetch 1-week returns for a list of tickers. Skips failures."""
    results = []
    for t in tickers:
        r = fetch_week_return(t)
        if r:
            results.append(r)
    return results
