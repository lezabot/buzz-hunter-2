"""Paper-only scoring with conservative market-only Trends fallback."""
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite, log1p


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
    """Score weights: Trends 45%, momentum 25%, volume 20%, liquidity 10%."""
    change = float(market['change_24h_pct'])
    volume = float(market['volume_usd_24h'])
    momentum = _clamp(40 + change * 2)
    activity = _clamp(20 + 17 * log1p(max(0, volume) / 1e6))
    liquidity = _clamp(market['liquidity_score'])
    market_score = (25 * momentum + 20 * activity + 10 * liquidity) / 55
    if trend_score is None or not isfinite(float(trend_score)):
        return Signal(market_score, market_score, None)
    trend = _clamp(trend_score)
    score = .45 * trend + .25 * momentum + .20 * activity + .10 * liquidity
    return Signal(score, market_score, trend)


def entry_allowed(signal, market, config):
    s, r = config['signals'], config['risk']
    price = float(market['price'])
    slip = float(r['assumed_slippage_pct_per_side'])
    return (config.get('mode') == 'paper'
            and (signal.trend_score is not None or config.get('signals', {}).get('allow_market_only_fallback', False))
            and isfinite(signal.score)
            and signal.score >= (s.get('fallback_minimum_score', 78) if signal.trend_score is None else s['minimum_score'])
            and 0 < price < 1
            and price * (1 + slip) < 1
            and 0 <= market['change_24h_pct'] <= r['max_entry_price_change_24h_pct']
            and market['volume_usd_24h'] >= r['min_24h_quote_volume_usd']
            and market['spread_pct'] <= r['max_spread_pct'])
