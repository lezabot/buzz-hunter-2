"""Buzz Hunter 3.0 paper-only market signal scoring.

Google Trends is not required or used. Entries must be strictly below $1.
Existing positions may be exited at any positive price.
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
    trend_score: float | None = None

def _clamp(value):
    return max(0.0, min(100.0, float(value)))

def evaluate(market, trend_score=None):
    change = float(market['change_24h_pct'])
    volume = max(0.0, float(market['volume_usd_24h']))
    momentum = _clamp(40 + 2 * change)
    activity = _clamp(20 + 17 * log1p(volume / 1e6))
    volatility_proxy = _clamp(abs(change) * 5)
    score = .45 * momentum + .35 * activity + .20 * volatility_proxy
    return Signal(_clamp(score), _clamp(score), None)

def entry_allowed(signal, market, config):
    s, r = config['signals'], config['risk']
    price = float(market['price'])
    return (signal.score >= float(s['minimum_score']) and
            0 < price < 1.0 and
            0 <= float(market['change_24h_pct']) <= float(r['max_entry_price_change_24h_pct']) and
            float(market['volume_usd_24h']) >= float(r['min_24h_quote_volume_usd']) and
            float(market['spread_pct']) <= float(r['max_spread_pct']))
