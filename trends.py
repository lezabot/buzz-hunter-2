"""Rate-limited Google Trends signal provider for PAPER-ONLY Buzz Hunter.

Returns only fresh, usable trend scores. A Google failure never becomes a zero
score or a fabricated signal. Google Trends is sampled/normalized, not live social data.
"""
import logging
import time

log = logging.getLogger('buzzhunter')

TERMS = {
    'BTC-USD': 'Bitcoin', 'ETH-USD': 'Ethereum',
    'SOL-USD': 'Solana crypto', 'DOGE-USD': 'Dogecoin',
    'PEPE-USD': 'Pepe coin crypto',
}


class TrendsFeed:
    def __init__(self, config):
        self.config = config.get('trends', {})
        self.enabled = bool(self.config.get('enabled', True))
        # Limit requests; shorter config refreshes are deliberately clamped.
        self.refresh_seconds = max(7200, int(self.config.get('refresh_seconds', 7200)))
        self.backoff_seconds = max(21600, int(self.config.get('backoff_seconds', 21600)))
        self.cache = {}
        self.cache_expires = 0
        self.next_refresh = 0
        self.warned = False

    def scores(self, symbols):
        if not self.enabled:
            return {}
        now = time.time()
        if now < self.next_refresh:
            return dict(self.cache) if now < self.cache_expires else {}
        # One batch of up to five distinct mapped terms per refresh. The caller
        # currently supplies only watchlist symbols; do not claim full coverage.
        chosen = []
        seen_terms = set()
        for symbol in symbols:
            term = self.config.get('terms', {}).get(symbol, TERMS.get(symbol))
            if term and term not in seen_terms:
                chosen.append((symbol, term))
                seen_terms.add(term)
            if len(chosen) == 5:
                break
        if not chosen:
            self.next_refresh = now + self.refresh_seconds
            return {}
        self.next_refresh = now + self.refresh_seconds
        try:
            from pytrends.request import TrendReq
            client = TrendReq(hl='en-US', tz=360, retries=0, timeout=(5, 20))
            terms = [term for _, term in chosen]
            client.build_payload(terms, timeframe='now 7-d', geo='US')
            frame = client.interest_over_time()
            result = {}
            if frame is not None and not frame.empty:
                for symbol, term in chosen:
                    if term not in frame:
                        continue
                    values = [float(v) for v in frame[term].tolist()]
                    if len(values) < 12:
                        continue
                    recent = sum(values[-6:]) / 6
                    previous = sum(values[-12:-6]) / 6
                    if previous < 5:
                        continue
                    growth = (recent - previous) / previous
                    result[symbol] = max(0.0, min(100.0, 50.0 + growth * 100.0))
            self.cache = result
            self.cache_expires = time.time() + self.refresh_seconds
            self.warned = False
            log.info('Google Trends refreshed: %d usable signals of %d requested', len(result), len(chosen))
        except Exception as exc:
            # No stale signals after a failed refresh; prevent hammering Google.
            self.cache = {}
            self.cache_expires = 0
            self.next_refresh = time.time() + self.backoff_seconds
            if not self.warned:
                log.warning('Google Trends unavailable; pausing requests for %ds: %s', self.backoff_seconds, exc)
                self.warned = True
        return dict(self.cache)
