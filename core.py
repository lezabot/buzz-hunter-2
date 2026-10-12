"""Buzz Hunter 3.0 paper-only signal scoring.

Google Trends is the largest scoring component. Missing Trends data never
receives an artificial boost, and entries require an actual Trends score.
"""
from dataclasses import dataclass
from math import log1p
from datetime import datetime, timezone


def utc_day(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d')


@dataclass
class Signal:
    score: float
    market_score: float
    trend_score: float | None


def _clamp(value):
    return max(0.0, min(100.0, float(value)))


def evaluate(market, trend_score=None):
    change = float(market['change_24h_pct'])
    volume = max(0.0, float(market['volume_usd_24h']))
    liquidity = _clamp(market['liquidity_score'])

    # Available market feed supplies 24-hour change/volume, not 5-minute candles.
    momentum = _clamp(40 + 2 * change)
    activity = _clamp(20 + 17 * log1p(volume / 1e6))
    # Proxy only: large absolute daily moves, not measured intraday volatility.
    volatility_proxy = _clamp(abs(change) * 5)

    market_score = .25 * momentum + .20 * activity + .10 * volatility_proxy
    # No score normalization when Trends is missing: missing data must not
    # masquerade as strong public interest.
    trend = None if trend_score is None else _clamp(trend_score)
    score = market_score + (.45 * trend if trend is not None else 0.0)
    return Signal(_clamp(score), _clamp(market_score / .55), trend)


def entry_allowed(signal, market, config):
    s, r = config['signals'], config['risk']
    # Google-first mode: do not buy assets without a measured Trends signal.
    return (signal.trend_score is not None and
            signal.score >= float(s['minimum_score']) and
            0 <= market['change_24h_pct'] <= r['max_entry_price_change_24h_pct'] and
            market['volume_usd_24h'] >= r['min_24h_quote_volume_usd'] and
            market['spread_pct'] <= r['max_spread_pct'] and market['price'] > 0)
