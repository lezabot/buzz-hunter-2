"""Safety regression checks for market-only paper trading."""
import tempfile
import unittest
from pathlib import Path
from .core import evaluate, entry_allowed
from .portfolio import PaperPortfolio
from .main import validate

CFG = {
    "mode": "paper", "starting_cash": 1000, "poll_seconds": 120, "universe_limit": 100,
    "signals": {"minimum_score": 68},
    "risk": {"trade_usd": 125, "max_positions": 3, "max_exposure_usd": 450,
             "max_daily_loss_usd": 50, "stop_loss_pct": .035, "take_profit_pct": .06,
             "trailing_stop_pct": .035, "assumed_fee_pct_per_side": .006,
             "assumed_slippage_pct_per_side": .003, "max_spread_pct": .015,
             "min_24h_quote_volume_usd": 1000000, "max_entry_price_change_24h_pct": 35}
}
M = {"price": .5, "change_24h_pct": 15, "volume_usd_24h": 100000000, "spread_pct": .001}

class PaperSafetyTests(unittest.TestCase):
    def test_market_only_without_google(self):
        signal = evaluate(M)
        self.assertIsNone(signal.trend_score)
        self.assertTrue(entry_allowed(signal, M, CFG))

    def test_price_boundary_including_slippage(self):
        near = dict(M, price=.999)
        self.assertFalse(entry_allowed(evaluate(near), near, CFG))

    def test_paper_broker_rejects_above_dollar(self):
        with tempfile.TemporaryDirectory() as d:
            p = PaperPortfolio(Path(d)/"state.json", CFG)
            self.assertFalse(p.buy("TEST-USD", .999, {"TEST-USD": .999}, 1))
            self.assertEqual(p.state["cash"], 1000)
            self.assertEqual(p.state["positions"], {})

    def test_limits_and_mode(self):
        validate(CFG)
        with tempfile.TemporaryDirectory() as d:
            p = PaperPortfolio(Path(d)/"state.json", CFG)
            for s in ("A-USD","B-USD","C-USD"):
                self.assertTrue(p.buy(s, .5, {s:.5}, 1))
            self.assertFalse(p.buy("D-USD", .5, {"D-USD":.5}, 1))
            self.assertEqual(len(p.state["positions"]), 3)
        bad = dict(CFG, mode="live")
        with self.assertRaises(ValueError):
            validate(bad)

if __name__ == "__main__":
    unittest.main()
