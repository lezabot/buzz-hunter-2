"""Optional, cached Google Trends confirmation; failures yield missing data, not false zero."""
import logging
import time

log = logging.getLogger('buzzhunter')

# Use unambiguous search terms; cashtags and short tickers often mean unrelated things.
TERMS = {'BTC-USD': 'Bitcoin', 'ETH-USD': 'Ethereum', 'SOL-USD': 'Solana crypto',
         'DOGE-USD': 'Dogecoin', 'PEPE-USD': 'Pepe coin crypto'}

class TrendsFeed:
    def __init__(self, config):
        self.config = config.get('trends', {})
        self.enabled = bool(self.config.get('enabled', True))
        self.refresh_seconds = max(3600, int(self.config.get('refresh_seconds', 7200)))
        self.cache = {}
        self.next_refresh = 0
        self.warned = False

    def scores(self, symbols):
        if not self.enabled:
            return {}
        now = time.time()
        if now < self.next_refresh:
            return dict(self.cache)
        self.next_refresh = now + self.refresh_seconds
        try:
            from pytrends.request import TrendReq
            client = TrendReq(hl='en-US', tz=360, retries=0, timeout=(5, 20))
            result = {}
            for symbol in symbols:
                term = self.config.get('terms', {}).get(symbol, TERMS.get(symbol))
                if not term:
                    continue
                client.build_payload([term], timeframe='now 7-d', geo='US')
                frame = client.interest_over_time()
                if frame is None or frame.empty or term not in frame:
                    continue
                values = [float(v) for v in frame[term].tolist()]
                if len(values) < 12:
                    continue
                # Relative acceleration, not cross-coin popularity; clamp noise from tiny baselines.
                recent = sum(values[-6:]) / 6
                previous = sum(values[-12:-6]) / 6
                if previous < 5:
                    continue
                growth = (recent - previous) / previous
                result[symbol] = max(0, min(100, 50 + growth * 100))
                time.sleep(2)
            self.cache = result
            self.warned = False
        except Exception as exc:
            self.cache = {}  # stale values are not treated as current
            if not self.warned:
                log.warning('Google Trends unavailable; market-only scoring: %s', exc)
                self.warned = True
        return dict(self.cache)
