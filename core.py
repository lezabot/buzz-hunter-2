"""Buzz Hunter 3.0 paper-only signal scoring.

Google Trends contributes 45% of the score. New purchases require a valid
Trends score and a strictly below-$1 entry price. This module does not
restrict exits: existing positions may be sold at any positive price.
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
    momentum = _clamp(40 + 2 * change)
    activity = _clamp(20 + 17 * log1p(volume / 1e6))
    # Proxy based on absolute 24-hour change; not intraday realized volatility.
    volatility_proxy = _clamp(abs(change) * 5)
    market_component = .25 * momentum + .20 * activity + .10 * volatility_proxy
    trend = None if trend_score is None else _clamp(trend_score)
    score = market_component + (.45 * trend if trend is not None else 0.0)
    return Signal(_clamp(score), _clamp(market_component / .55), trend)


def entry_allowed(signal, market, config):
    """Apply the sub-$1 ceiling to new entries ONLY, never exits."""
    s, r = config['signals'], config['risk']
    price = float(market['price'])
    return (signal.trend_score is not None and
            signal.score >= float(s['minimum_score']) and
            0 < price < 1.0 and
            0 <= float(market['change_24h_pct']) <= float(r['max_entry_price_change_24h_pct']) and
            float(market['volume_usd_24h']) >= float(r['min_24h_quote_volume_usd']) and
            float(market['spread_pct']) <= float(r['max_spread_pct']))
