"""Paper-only advanced confirmation. Missing data fails closed."""
def confirm(feed, symbol, cfg):
    s = cfg.get('advanced_signals', {})
    if not s.get('enabled', False):
        return True, 'disabled'
    candles = feed.get('/products/' + symbol + '/candles', {'granularity': 300})
    book = feed.get('/products/' + symbol + '/book', {'level': 2})
    if not isinstance(candles, list) or len(candles) < 17:
        return False, 'insufficient candles'
    rows = sorted(candles, key=lambda x: x[0])[-17:-1]  # discard potentially incomplete current candle
    if len(rows) < 16 or any(len(x) < 6 or float(x[4]) <= 0 for x in rows):
        return False, 'invalid candles'
    close, c5, c15 = (float(rows[i][4]) for i in (-1, -2, -4))
    m5, m15 = 100*(close/c5-1), 100*(close/c15-1)
    vols = [float(r[5]) for r in rows]
    baseline = sum(vols[:-1]) / (len(vols)-1)
    if baseline <= 0 or sum(vols) <= 0:
        return False, 'invalid volume'
    rvol = vols[-1]/baseline
    vwap = sum(((float(r[1])+float(r[2])+float(r[4]))/3)*v for r,v in zip(rows,vols))/sum(vols)
    gap = 100*(close/vwap-1)
    bids, asks = book.get('bids', []), book.get('asks', [])
    bid_depth = sum(float(x[1]) for x in bids[:20])
    ask_depth = sum(float(x[1]) for x in asks[:20])
    if bid_depth <= 0 or ask_depth <= 0:
        return False, 'invalid order book'
    ratio = bid_depth/ask_depth
    checks = [(rvol >= float(s.get('min_rvol',2.5)), 'rvol'),
              (m5 >= float(s.get('min_momentum_5m_pct',.1)), '5m momentum'),
              (m5 <= float(s.get('max_momentum_5m_pct',10)), '5m overextended'),
              (m15 >= float(s.get('min_momentum_15m_pct',.3)), '15m momentum'),
              (gap >= float(s.get('min_vwap_gap_pct',0)), 'vwap low'),
              (gap <= float(s.get('max_vwap_gap_pct',5)), 'vwap high'),
              (ratio >= float(s.get('min_bid_ask_depth_ratio',1.3)), 'order book')]
    failed = [name for ok,name in checks if not ok]
    return not failed, ', '.join(failed) if failed else 'confirmed'


def volume_spike_15m(feed, symbol):
    """Completed 5m candles: last 15m volume vs immediately preceding 15m.

    A 200% increase means current volume >= 3x previous volume.
    Missing or zero baseline never earns a bonus.
    """
    candles = feed.get('/products/' + symbol + '/candles', {'granularity': 300})
    if not isinstance(candles, list) or len(candles) < 7:
        return None
    rows = sorted(candles, key=lambda r: r[0])[-7:-1]
    if len(rows) != 6 or any(len(r) < 6 for r in rows):
        return None
    volumes = [float(r[5]) for r in rows]
    if any(not __import__('math').isfinite(v) or v < 0 for v in volumes):
        return None
    baseline, recent = sum(volumes[:3]), sum(volumes[3:])
    if baseline <= 0:
        return None
    return 100 * (recent / baseline - 1)
