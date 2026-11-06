"""Coinbase public market feed with paced requests and bounded 429 retries."""
import logging
import math
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

    def _candle_window(self, symbol, end, step, count):
        """Retry an exact completed window once; never fill absent candles."""
        expected = list(range(end - count * step, end, step))
        fmt = lambda t: time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(t))
        found = {}
        for attempt in range(2):
            rows = self.get('/products/' + symbol + '/candles', params={
                'granularity': step, 'start': fmt(expected[0]), 'end': fmt(end)})
            if not isinstance(rows, list):
                return None
            for row in rows:
                try:
                    stamp = float(row[0])
                    if stamp not in expected or len(row) < 6:
                        continue
                    values = [float(v) for v in row[1:6]]
                    if (not all(math.isfinite(v) for v in values)
                            or any(v <= 0 for v in values[:4]) or values[4] < 0
                            or values[0] > min(values[2:4])
                            or values[1] < max(values[2:4])):
                        continue
                    found[int(stamp)] = [int(stamp)] + values
                except (ValueError, TypeError, IndexError, OverflowError):
                    continue
            if all(t in found for t in expected):
                return [found[t] for t in expected]
            if attempt == 0:
                log.info('CANDLE RETRY %s step=%ds missing=%d',
                         symbol, step, sum(t not in found for t in expected))
        return None

    def _history(self, symbol):
        now = int(time.time() // 60) * 60
        candles = self._candle_window(symbol, now, 60, 30)
        if candles is not None:
            return candles, 60
        # Use real exchange aggregates, not invented zero-volume minute bars.
        # The latest complete 5m bucket ends no more than 4 minutes earlier.
        end = now // 300 * 300
        candles = self._candle_window(symbol, end, 300, 6)
        if candles is not None:
            log.info('CANDLE FALLBACK %s: complete exchange 5m candles end=%d', symbol, end)
            return candles, 300
        log.info('CONFIRMATION SKIPPED %s: incomplete 1m and 5m history', symbol)
        return None, None

    def volume_spike_15m(self, symbol):
        candles, step = self._history(symbol)
        if candles is None:
            return None
        half = len(candles) // 2
        previous = sum(r[5] for r in candles[:half])
        recent = sum(r[5] for r in candles[half:])
        return (recent / previous - 1) * 100 if previous > 0 else None

    def confirmation(self, symbol):
        candles, step = self._history(symbol)
        if candles is None:
            return None
        closes = [float(r[4]) for r in candles]
        volumes = [float(r[5]) for r in candles]
        recent_count = 300 // step
        recent = sum(volumes[-recent_count:])
        baseline = sum(volumes[:-recent_count]) / 5
        total_volume = sum(volumes)
        if baseline <= 0 or total_volume <= 0 or closes[-1 - 300 // step] <= 0 or closes[-1 - 900 // step] <= 0:
            log.info('CONFIRMATION SKIPPED %s: insufficient volume or invalid candle prices', symbol)
            return None
        vwap = sum(float(r[4])*float(r[5]) for r in candles) / total_volume
        book = self.get('/products/'+symbol+'/book', params={'level':2})
        bid_depth = sum(float(x[1]) for x in book.get('bids',[])[:10])
        ask_depth = sum(float(x[1]) for x in book.get('asks',[])[:10])
        if (not all(math.isfinite(v) for v in (bid_depth, ask_depth, vwap))
                or bid_depth <= 0 or ask_depth <= 0 or vwap <= 0):
            log.info('CONFIRMATION SKIPPED %s: insufficient order-book depth or VWAP', symbol)
            return None
        result = {'candle_seconds': step, 'rvol': recent/baseline,
                  'momentum_5m_pct': 100*(closes[-1]/closes[-1 - 300 // step]-1),
                  'momentum_15m_pct': 100*(closes[-1]/closes[-1 - 900 // step]-1),
                  'vwap_gap_pct': 100*(closes[-1]/vwap-1),
                  'depth_ratio': bid_depth/ask_depth}
        log.info('CONFIRMATION READY %s rvol=%.2f momentum5m=%.2f momentum15m=%.2f depth=%.2f',
                 symbol, result['rvol'], result['momentum_5m_pct'],
                 result['momentum_15m_pct'], result['depth_ratio'])
        return result
