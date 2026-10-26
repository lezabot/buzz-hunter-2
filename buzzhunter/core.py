"""Buzz Hunter 3.0 paper-only market signal scoring.

Entries must be strictly below $1. Existing positions may be exited at any positive price.
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

def _clamp(value):
    return max(0.0, min(100.0, float(value)))

def evaluate(market, config=None):
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
    score = _clamp(score)
    return Signal(score, score)

def entry_allowed(signal, market, config):
    return not entry_rejection_reasons(signal, market, config)

def entry_rejection_reasons(signal, market, config):
    s, r = config['signals'], config['risk']
    reasons = []
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
    advanced = config.get('advanced_signals', {})
    if advanced.get('enabled', False):
        confirmation = market.get('confirmation')
        if confirmation is None:
            reasons.append('momentum_confirmation_unavailable')
        else:
            for key, minimum in [('rvol', 'min_rvol'), ('momentum_5m_pct', 'min_momentum_5m_pct'), ('momentum_15m_pct', 'min_momentum_15m_pct'), ('vwap_gap_pct', 'min_vwap_gap_pct'), ('depth_ratio', 'min_bid_ask_depth_ratio')]:
                if confirmation[key] < float(advanced[minimum]): reasons.append(key + '_below_minimum')
            if confirmation['momentum_5m_pct'] > float(advanced['max_momentum_5m_pct']): reasons.append('momentum_5m_overextended')
            if confirmation['vwap_gap_pct'] > float(advanced['max_vwap_gap_pct']): reasons.append('vwap_overextended')
    return reasons
