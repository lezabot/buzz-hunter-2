"""Completed exchange candles recover sparse minute data without inventing bars."""
import copy
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from buzzhunter.market import CoinbaseFeed
from buzzhunter.core import evaluate, entry_rejection_reasons
from buzzhunter.portfolio import PaperPortfolio
from buzzhunter.main import validate
import yaml

NOW = 1800000120  # deliberately not a five-minute boundary
END5 = NOW // 300 * 300


def candles(end, step, count):
    return [[end - (count-i)*step, .49, .52, .50, .50+i*.0001,
             30 if i == count-1 else 10] for i in range(count)]


class StubFeed(CoinbaseFeed):
    def __init__(self, minutes=None, aggregates=None):
        super().__init__()
        self.minutes = minutes
        self.aggregates = aggregates
        self.calls = []

    def get(self, path, params=None):
        self.calls.append((path, params))
        if path.endswith('/book'):
            return {'bids': [['.50', '20']], 'asks': [['.51', '10']]}
        rows = self.minutes if params['granularity'] == 60 else self.aggregates
        return copy.deepcopy(rows or [])


@patch('buzzhunter.market.time.time', return_value=NOW)
class CandleHistoryTests(unittest.TestCase):
    def test_complete_minutes_keep_existing_math(self, clock):
        rows = candles(NOW, 60, 30)
        feed = StubFeed(rows)
        result = feed.confirmation('TEST-USD')
        self.assertEqual(result['candle_seconds'], 60)
        self.assertAlmostEqual(result['rvol'], 1.4)
        self.assertAlmostEqual(result['momentum_5m_pct'], 100*(rows[-1][4]/rows[-6][4]-1))
        self.assertFalse(any(p and p.get('granularity') == 300 for _, p in feed.calls))

    def test_sparse_minutes_use_real_complete_five_minute_bars(self, clock):
        rows = candles(END5, 300, 6)
        feed = StubFeed(candles(NOW, 60, 30)[2:], rows[::-1])
        result = feed.confirmation('TEST-USD')
        self.assertEqual(result['candle_seconds'], 300)
        self.assertAlmostEqual(result['rvol'], 3)
        self.assertAlmostEqual(result['momentum_5m_pct'], 100*(rows[-1][4]/rows[-2][4]-1))
        self.assertAlmostEqual(result['momentum_15m_pct'], 100*(rows[-1][4]/rows[-4][4]-1))
        self.assertEqual(sum(p and p.get('granularity') == 60 for _, p in feed.calls), 2)
        self.assertAlmostEqual(feed.volume_spike_15m('TEST-USD'), (50/30-1)*100)

    def test_retry_recovers_missing_minute(self, clock):
        rows = candles(NOW, 60, 30)
        feed = StubFeed(rows[:-1])
        original = feed.get
        def get(path, params=None):
            if len(feed.calls) == 1:
                feed.minutes = rows
            return original(path, params)
        feed.get = get
        self.assertEqual(feed.confirmation('TEST-USD')['candle_seconds'], 60)

    def test_missing_stale_or_incomplete_aggregates_fail_closed(self, clock):
        rows = candles(END5, 300, 6)
        cases = [rows[:-1], candles(END5-300, 300, 6), rows[1:]+[[END5,.49,.52,.50,.51,20]]]
        for aggregate in cases:
            with self.subTest(aggregate=aggregate):
                feed = StubFeed([], aggregate)
                self.assertIsNone(feed.confirmation('TEST-USD'))
                self.assertIsNone(feed.volume_spike_15m('TEST-USD'))

    def test_invalid_values_do_not_enable_confirmation(self, clock):
        for bad in [float('nan'), float('inf'), -1]:
            for field in [4, 5]:
                rows = candles(END5, 300, 6)
                rows[-1][field] = bad
                self.assertIsNone(StubFeed([], rows).confirmation('TEST-USD'))

    def test_zero_volume_never_earns_bonus(self, clock):
        rows = candles(END5, 300, 6)
        for r in rows:
            r[5] = 0
        feed = StubFeed([], rows)
        self.assertIsNone(feed.volume_spike_15m('TEST-USD'))
        self.assertIsNone(feed.confirmation('TEST-USD'))

    def test_recovered_data_can_pass_existing_entry_rules(self, clock):
        cfg = yaml.safe_load(Path('config.yaml').read_text())
        rows = candles(END5, 300, 6)
        for i, row in enumerate(rows):
            row[4] = .50 + i*.0004
        market = {'price':.502, 'change_24h_pct':25, 'volume_usd_24h':10_000_000,
                  'spread_pct':.001, 'confirmation':StubFeed([], rows).confirmation('TEST-USD')}
        self.assertEqual(entry_rejection_reasons(evaluate(market, cfg), market, cfg), [])
        market['price'] = 1
        self.assertIn('price_or_slippage_at_least_1_usd', entry_rejection_reasons(evaluate(market,cfg),market,cfg))
        market['confirmation'] = None
        self.assertIn('momentum_confirmation_unavailable', entry_rejection_reasons(evaluate(market,cfg),market,cfg))

class PaperRiskTests(unittest.TestCase):
    def test_mode_and_persistent_position_limits(self):
        cfg = yaml.safe_load(Path('config.yaml').read_text())
        validate(cfg)
        with self.assertRaises(ValueError):
            validate(dict(cfg, mode='live'))
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'state.json'
            portfolio = PaperPortfolio(path, cfg)
            for symbol in ('A-USD', 'B-USD', 'C-USD'):
                self.assertTrue(portfolio.buy(symbol, .5, {symbol:.5}, NOW))
            self.assertFalse(portfolio.buy('D-USD', .5, {'D-USD':.5}, NOW))
            restored = PaperPortfolio(path, cfg)
            self.assertEqual(restored.state, portfolio.state)
            self.assertEqual(len(restored.state['positions']), 3)

    def test_daily_loss_blocks_entry_and_exits_remain_available(self):
        cfg = yaml.safe_load(Path('config.yaml').read_text())
        with tempfile.TemporaryDirectory() as d:
            portfolio = PaperPortfolio(Path(d) / 'state.json', cfg)
            portfolio.day_check({}, NOW)
            self.assertTrue(portfolio.buy('A-USD', .5, {'A-USD':.5}, NOW))
            portfolio.day_check({'A-USD':.01}, NOW)
            self.assertTrue(portfolio.halted({'A-USD':.01}))
            self.assertFalse(portfolio.buy('B-USD', .5, {'A-USD':.01}, NOW))
            self.assertTrue(portfolio.sell('A-USD', 1.1, NOW, 'test'))
            self.assertEqual(portfolio.state['positions'], {})


if __name__ == '__main__':
    unittest.main()
