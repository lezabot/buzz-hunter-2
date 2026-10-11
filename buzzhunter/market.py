"""Public Coinbase Exchange market data; no credentials or orders."""
import requests

BASE = 'https://api.exchange.coinbase.com'

class CoinbaseFeed:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'BuzzHunterPaper/2.0', 'Accept': 'application/json'})

    def get(self, path, params=None):
        r = self.session.get(BASE + path, params=params, timeout=12)
        r.raise_for_status()
        return r.json()

    def products(self, limit, watchlist):
        rows = self.get('/products')
        allowed = {r['id']: r for r in rows if r.get('quote_currency') == 'USD' and
                   r.get('status') == 'online' and not r.get('trading_disabled', False)}
        selected = [s for s in watchlist if s in allowed]
        # Use liquid watchlist first, then alphabetically sorted eligible products.
        selected += [s for s in sorted(allowed) if s not in selected]
        return selected[:limit]

    def market(self, symbol):
        ticker = self.get('/products/' + symbol + '/ticker')
        stats = self.get('/products/' + symbol + '/stats')
        price = float(ticker['price'])
        bid, ask = float(ticker.get('bid') or 0), float(ticker.get('ask') or 0)
        if price <= 0 or bid <= 0 or ask <= 0 or ask < bid:
            raise ValueError('Missing or invalid live bid/ask')
        opening = float(stats['open'])
        volume = float(stats['volume']) * price
        return {'price': price, 'change_24h_pct': (price / opening - 1) * 100 if opening > 0 else 0,
                'volume_usd_24h': volume, 'spread_pct': (ask - bid) / ((ask + bid) / 2),
                'liquidity_score': min(100, max(0, 100 - 1000 * (ask - bid) / price))}
