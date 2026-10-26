"""Coinbase public market feed with paced requests and bounded 429 retries."""
import logging
import random
import time
import requests
BASE = 'https://api.exchange.coinbase.com'
log = logging.getLogger('buzzhunter')
class CoinbaseRateLimitError(RuntimeError):
    pass
class CoinbaseFeed:
    def __init__(self, min_interval_seconds=0.55, max_retries=4):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'BuzzHunterPaper/3.0', 'Accept': 'application/json'})
        self.min_interval = min_interval_seconds
        self.max_retries = max_retries
        self._next_request = 0.0
    def get(self, path, params=None):
        for attempt in range(self.max_retries+1):
            wait = self._next_request-time.monotonic()
            if wait > 0: time.sleep(wait)
            self._next_request = time.monotonic()+self.min_interval
            try:
                response = self.session.get(BASE+path, params=params, timeout=12)
            except (requests.Timeout, requests.ConnectionError):
                if attempt == self.max_retries: raise
                time.sleep(min(12,1.5*2**attempt)+random.uniform(0,.3))
                continue
            if response.status_code in (429,503):
                if attempt == self.max_retries: raise CoinbaseRateLimitError('Coinbase throttling: '+path)
                try: delay=float(response.headers.get('Retry-After',''))
                except (ValueError,TypeError): delay=1.5*2**attempt
                time.sleep(min(30,max(1,delay))+random.uniform(0,.3))
                continue
            response.raise_for_status()
            return response.json()
        raise CoinbaseRateLimitError('Coinbase request failed')
    def products(self, limit, watchlist):
        rows=self.get('/products')
        allowed={r['id']:r for r in rows if r.get('quote_currency')=='USD' and r.get('status')=='online' and not r.get('trading_disabled',False)}
        selected=[s for s in watchlist if s in allowed]
        selected += [s for s in sorted(allowed) if s not in selected]
        return selected[:limit]
    def market(self,symbol):
        ticker=self.get('/products/'+symbol+'/ticker')
        stats=self.get('/products/'+symbol+'/stats')
        price=float(ticker['price'])
        bid,ask=float(ticker.get('bid') or 0),float(ticker.get('ask') or 0)
        if price<=0 or bid<=0 or ask<=0 or ask<bid: raise ValueError('Invalid bid/ask')
        opening=float(stats['open'])
        volume=float(stats['volume'])*price
        return {'price':price,'change_24h_pct':(price/opening-1)*100 if opening>0 else 0,
                'volume_usd_24h':volume,'spread_pct':(ask-bid)/((ask+bid)/2),
                'liquidity_score':min(100,max(0,100-1000*(ask-bid)/price))}

    def volume_spike_15m(self, symbol):
        # Compare two complete adjacent 15-minute windows of one-minute volume.
        now = int(time.time() // 60) * 60
        fmt = lambda t: time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(t))
        rows = self.get('/products/' + symbol + '/candles',
                        params={'granularity': 60, 'start': fmt(now - 31*60), 'end': fmt(now)})
        by_minute = {int(row[0]): float(row[5]) for row in rows if len(row) >= 6}
        recent = [by_minute.get(now - 60*i) for i in range(1, 16)]
        previous = [by_minute.get(now - 60*i) for i in range(16, 31)]
        if any(v is None for v in recent + previous):
            return None
        baseline = sum(previous)
        return (sum(recent) / baseline - 1) * 100 if baseline > 0 else None

    def confirmation(self, symbol):
        # Coinbase may omit minutes with no trades. Do not manufacture candles.
        now = int(time.time() // 60) * 60
        fmt = lambda t: time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(t))
        rows = self.get('/products/' + symbol + '/candles',
                        params={'granularity': 60, 'start': fmt(now-33*60), 'end': fmt(now)})
        by_time = {int(r[0]): r for r in rows if len(r) >= 6 and int(r[0]) < now}
        expected = [now - 60*i for i in range(30, 0, -1)]
        missing = [t for t in expected if t not in by_time]
        if missing:
            log.info('CONFIRMATION SKIPPED %s: missing %d of 30 complete minute candles', symbol, len(missing))
            return None
        candles = [by_time[t] for t in expected]
        closes = [float(r[4]) for r in candles]
        volumes = [float(r[5]) for r in candles]
        recent = sum(volumes[-5:])
        baseline = sum(volumes[:-5]) / 5
        total_volume = sum(volumes)
        if baseline <= 0 or total_volume <= 0 or closes[-6] <= 0 or closes[-16] <= 0:
            log.info('CONFIRMATION SKIPPED %s: insufficient volume or invalid candle prices', symbol)
            return None
        vwap = sum(float(r[4])*float(r[5]) for r in candles) / total_volume
        book = self.get('/products/'+symbol+'/book', params={'level':2})
        bid_depth = sum(float(x[1]) for x in book.get('bids',[])[:10])
        ask_depth = sum(float(x[1]) for x in book.get('asks',[])[:10])
        if ask_depth <= 0 or vwap <= 0:
            log.info('CONFIRMATION SKIPPED %s: insufficient order-book depth or VWAP', symbol)
            return None
        result = {'rvol': recent/baseline,
                  'momentum_5m_pct': 100*(closes[-1]/closes[-6]-1),
                  'momentum_15m_pct': 100*(closes[-1]/closes[-16]-1),
                  'vwap_gap_pct': 100*(closes[-1]/vwap-1),
                  'depth_ratio': bid_depth/ask_depth}
        log.info('CONFIRMATION READY %s rvol=%.2f momentum5m=%.2f momentum15m=%.2f depth=%.2f',
                 symbol, result['rvol'], result['momentum_5m_pct'],
                 result['momentum_15m_pct'], result['depth_ratio'])
        return result
