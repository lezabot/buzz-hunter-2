"""Regression tests for Buzz Hunter 3.0 paper-only safety gates."""
import unittest
from buzzhunter.core import evaluate, entry_allowed
from buzzhunter.trends import TERMS, TrendsFeed


class TestEntrySafety(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            'mode': 'paper',
            'trends': {'enabled': True},
            'signals': {'minimum_score': 70},
            'risk': {
                'assumed_slippage_pct_per_side': .003,
                'max_entry_price_change_24h_pct': 35,
                'min_24h_quote_volume_usd': 1_000_000,
                'max_spread_pct': .015,
            },
        }
        self.market = {
            'price': .5, 'change_24h_pct': 12,
            'volume_usd_24h': 20_000_000,
            'spread_pct': .001, 'liquidity_score': 95,
        }

    def test_missing_trends_blocks_entry(self):
        self.assertFalse(entry_allowed(evaluate(self.market, None), self.market, self.cfg))

    def test_dollar_or_more_blocks_entry(self):
        market = dict(self.market, price=1.0)
        self.assertFalse(entry_allowed(evaluate(market, 100), market, self.cfg))

    def test_live_mode_blocks_entry(self):
        self.cfg['mode'] = 'live'
        self.assertFalse(entry_allowed(evaluate(self.market, 100), self.market, self.cfg))

    def test_explicit_terms_are_present(self):
        self.assertIn('SHIB-USD', TERMS)
        self.assertIn('ADA-USD', TERMS)

    def test_unknown_symbols_never_receive_synthetic_trends(self):
        feed = TrendsFeed({'trends': {'enabled': False}})
        self.assertEqual(feed.scores(['UNKNOWN-USD']), {})


if __name__ == '__main__':
    unittest.main()
