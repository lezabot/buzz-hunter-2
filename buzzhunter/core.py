"""Pure scoring rules; missing Trends data cannot block market-only mode."""
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


def evaluate(market, trend_score=None):
    change = market['change_24h_pct']
    volume = market['volume_usd_24h']
    # 24h momentum is a coarse signal, not an early-move guarantee.
    momentum = max(0, min(100, 40 + change * 2))
    activity = max(0, min(100, 20 + 17 * log1p(max(0, volume) / 1e6)))
    market_score = .65 * momentum + .35 * activity
    liquidity = market['liquidity_score']
    base = .4 * market_score + .3 * liquidity
    if trend_score is None:
        score = base / .7
    else:
        score = base + .3 * trend_score
    return Signal(score, market_score, trend_score)


def entry_allowed(signal, market, config):
    s, r = config['signals'], config['risk']
    return (signal.score >= s['minimum_score'] and
            0 <= market['change_24h_pct'] <= r['max_entry_price_change_24h_pct'] and
            market['volume_usd_24h'] >= r['min_24h_quote_volume_usd'] and
            market['spread_pct'] <= r['max_spread_pct'] and market['price'] > 0)
