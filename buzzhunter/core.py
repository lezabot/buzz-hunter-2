"""Buzz Hunter 3.0 paper-only market signal scoring.

Every new entry requires a valid Google Trends score weighted at 45%. Entries must be strictly below $1.
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

def evaluate(market, trend_score=None, config=None):
    change = float(market['change_24h_pct'])
    volume = max(0.0, float(market['volume_usd_24h']))
    momentum = _clamp(40 + 2 * change)
    activity = _clamp(20 + 17 * log1p(volume / 1e6))
    volatility_proxy = _clamp(abs(change) * 5)
    weights = (config or {}).get('signals', {})
    mw = float(weights.get('momentum_weight', 45))
    vw = float(weights.get('volume_weight', 35))
    volw = float(weights.get('volatility_weight', 20))
    total = mw + vw + volw
    if min(mw, vw, volw) < 0 or total <= 0:
        raise ValueError('Invalid signal weights')
    score = (mw * momentum + vw * activity + volw * volatility_proxy) / total
    spike = market.get('volume_spike_pct')
    if spike is not None and spike >= float(weights.get('volume_spike_threshold_pct', 200)):
        score += float(weights.get('volume_spike_bonus_points', 15))
    market_score = _clamp(score)
    trends_weight = float((config or {}).get('trends', {}).get('weight_pct', 45)) / 100.0
    if trends_weight != 0.45:
        raise ValueError('Google Trends weight must remain 45%')
    valid_trend = trend_score is not None and 0 <= float(trend_score) <= 100
    trend_value = float(trend_score) if valid_trend else None
    combined = (1 - trends_weight) * market_score + trends_weight * (trend_value if valid_trend else 0)
    return Signal(_clamp(combined), market_score, trend_value)

def entry_allowed(signal, market, config):
    s, r = config['signals'], config['risk']
    price = float(market['price'])
    return not entry_rejection_reasons(signal, market, config)

def entry_rejection_reasons(signal, market, config):
    s, r = config['signals'], config['risk']
    reasons = []
    # Fail closed: no paper entry without a validated Google Trends score.
    if signal.trend_score is None or not (0 <= signal.trend_score <= 100):
        reasons.append('missing_valid_google_trends')
    price = float(market['price'])
    if signal.score < float(s['minimum_score']): reasons.append('score_below_minimum')
    if not (0 < price and price * (1 + float(r['assumed_slippage_pct_per_side'])) < 1):
        reasons.append('price_or_slippage_at_least_1_usd')
    change = float(market['change_24h_pct'])
    if not (0 <= change <= float(r['max_entry_price_change_24h_pct'])):
        reasons.append('24h_change_outside_range')
    if float(market['volume_usd_24h']) < float(r['min_24h_quote_volume_usd']):
        reasons.append('24h_volume_below_minimum')
    if float(market['spread_pct']) > float(r['max_spread_pct']):
        reasons.append('spread_too_wide')
    return reasons
