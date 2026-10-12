"""Conservative Google Trends confirmation for paper-only entries.

Rate-limit aware, fail-closed, and cache-validity bounded. No synthetic scores.
"""
import logging
import random
import time

log = logging.getLogger("buzzhunter")
TERMS = {
    "BTC-USD": "Bitcoin", "ETH-USD": "Ethereum",
    "SOL-USD": "Solana crypto", "DOGE-USD": "Dogecoin",
    "PEPE-USD": "Pepe coin crypto",
}

class TrendsFeed:
    def __init__(self, config):
        self.config = config.get("trends", {})
        self.enabled = bool(self.config.get("enabled", True))
        self.refresh_seconds = max(3600, int(self.config.get("refresh_seconds", 7200)))
        self.max_cache_age_seconds = min(
            21600, max(self.refresh_seconds, int(self.config.get("max_cache_age_seconds", 7200)))
        )
        self.request_spacing_seconds = max(5, int(self.config.get("request_spacing_seconds", 15)))
        self.backoff_seconds = max(3600, int(self.config.get("backoff_seconds", 7200)))
        self.cache = {}
        self.cache_time = {}
        self.next_refresh = 0.0
        self.warned = False

    def _valid_cache(self, now, symbols):
        return {
            symbol: self.cache[symbol]
            for symbol in symbols
            if symbol in self.cache
            and now - self.cache_time.get(symbol, 0) <= self.max_cache_age_seconds
        }

    def scores(self, symbols):
        if not self.enabled:
            return {}
        symbols = list(dict.fromkeys(symbols))
        now = time.time()
        valid = self._valid_cache(now, symbols)
        if now < self.next_refresh:
            if not valid:
                log.info("Google Trends awaiting refresh/backoff; new paper entries blocked")
            return valid

        # Schedule before attempting requests so repeated scan calls do not hammer Google.
        self.next_refresh = now + self.refresh_seconds
        try:
            from pytrends.request import TrendReq
            client = TrendReq(hl="en-US", tz=360, retries=0, timeout=(5, 20))
        except Exception as exc:
            self.next_refresh = now + self.backoff_seconds
            log.warning("Google Trends client unavailable; paper entries without valid cache blocked: %s", exc)
            return valid

        # Batch up to five terms per Google request instead of one request per coin.
        # Scores measure within-term acceleration, not cross-term popularity.
        requests = []
        for symbol in symbols:
            term = self.config.get("terms", {}).get(symbol, TERMS.get(symbol))
            if term:
                requests.append((symbol, term))
        for offset in range(0, len(requests), 5):
            batch = requests[offset:offset + 5]
            if offset:
                time.sleep(self.request_spacing_seconds + random.uniform(0, 2))
            try:
                client.build_payload([term for _, term in batch], timeframe="now 7-d", geo="US")
                frame = client.interest_over_time()
                for symbol, term in batch:
                    if frame is None or frame.empty or term not in frame:
                        self.cache.pop(symbol, None)
                        self.cache_time.pop(symbol, None)
                        continue
                    values = [float(v) for v in frame[term].tolist()]
                    if len(values) < 12:
                        self.cache.pop(symbol, None)
                        self.cache_time.pop(symbol, None)
                        continue
                    recent = sum(values[-6:]) / 6
                    previous = sum(values[-12:-6]) / 6
                    if previous < 5:
                        self.cache.pop(symbol, None)
                        self.cache_time.pop(symbol, None)
                        continue
                    growth = (recent - previous) / previous
                    self.cache[symbol] = max(0.0, min(100.0, 50.0 + growth * 100.0))
                    self.cache_time[symbol] = time.time()
                self.warned = False
            except Exception as exc:
                self.next_refresh = time.time() + self.backoff_seconds
                if not self.warned:
                    log.warning(
                        "Google Trends unavailable; backing off %ds. "
                        "Only unexpired real scores may permit paper entries: %s",
                        self.backoff_seconds, exc,
                    )
                    self.warned = True
                break
        valid = self._valid_cache(time.time(), symbols)
        log.info("Google Trends confirmation available for %d/%d requested symbols", len(valid), len(symbols))
        return valid
