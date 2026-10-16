"""Unit checks for the paper portfolio price boundary."""
import tempfile
import unittest
from pathlib import Path
from buzzhunter.portfolio import PaperPortfolio

CONFIG = {
    "starting_cash": 1000,
    "risk": {
        "trade_usd": 100, "max_positions": 3, "max_exposure_usd": 450,
        "max_daily_loss_usd": 50, "assumed_fee_pct_per_side": .006,
        "assumed_slippage_pct_per_side": .003, "stop_loss_pct": .035,
        "take_profit_pct": .06, "trailing_stop_pct": .035,
    },
}

class PaperPriceBoundary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.paper = PaperPortfolio(Path(self.tmp.name) / "state.json", CONFIG)

    def test_price_boundary(self):
        for price in (1, 1.1, .999, 0):
            self.assertFalse(self.paper.buy("EXAMPLE-USD", price, {}, 1))
        self.assertEqual(self.paper.state["cash"], 1000)

    def test_valid_entry_and_unrestricted_exit(self):
        self.assertTrue(self.paper.buy("EXAMPLE-USD", .5, {}, 1))
        self.assertLess(self.paper.state["positions"]["EXAMPLE-USD"]["entry_price"], 1)
        self.assertTrue(self.paper.sell("EXAMPLE-USD", 2, 2, "test"))
        self.assertEqual(self.paper.state["trades"][-1]["side"], "SELL")
