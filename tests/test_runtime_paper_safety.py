"""Regression tests for the Railway runtime paper broker (buzzhunter.portfolio)."""
import tempfile
import time
import unittest
from pathlib import Path

from buzzhunter.portfolio import PaperPortfolio


def config():
    return {
        "mode": "paper",
        "starting_cash": 1000,
        "signals": {"cooldown_hours": 6},
        "risk": {
            "trade_usd": 125,
            "max_positions": 3,
            "max_exposure_usd": 450,
            "max_daily_loss_usd": 50,
            "assumed_fee_pct_per_side": 0.006,
            "assumed_slippage_pct_per_side": 0.003,
            "stop_loss_pct": 0.035,
            "take_profit_pct": 0.06,
            "trailing_stop_pct": 0.035,
        },
    }


class PaperBrokerSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "paper_state.json"
        self.broker = PaperPortfolio(self.path, config())
        self.now = time.time()

    def test_execution_price_must_remain_strictly_below_one_dollar(self):
        for price in (0, -0.1, 1.0, 0.999):
            with self.subTest(price=price):
                self.assertFalse(self.broker.buy("BOUNDARY-USD", price, {}, self.now))
        self.assertTrue(self.broker.buy("VALID-USD", 0.50, {}, self.now))
        self.assertLess(self.broker.state["positions"]["VALID-USD"]["entry_price"], 1)

    def test_sales_not_restricted_by_entry_price_cap(self):
        self.assertTrue(self.broker.buy("VALID-USD", 0.50, {}, self.now))
        self.assertTrue(self.broker.sell("VALID-USD", 1.50, self.now + 60, "take_profit"))
        self.assertNotIn("VALID-USD", self.broker.state["positions"])

    def test_six_hour_cooldown_survives_restart(self):
        self.assertTrue(self.broker.buy("ALEO-USD", 0.05, {}, self.now))
        self.assertTrue(self.broker.sell("ALEO-USD", 0.05, self.now + 60, "stop_loss"))
        restarted = PaperPortfolio(self.path, config())
        self.assertFalse(restarted.buy("ALEO-USD", 0.05, {}, self.now + 60 + 6 * 3600 - 1))
        self.assertTrue(restarted.buy("OTHER-USD", 0.05, {}, self.now + 61))
        self.assertTrue(restarted.buy("ALEO-USD", 0.05, {}, self.now + 60 + 6 * 3600))

    def test_missing_cooldown_setting_does_not_weaken_minimum(self):
        cfg = config()
        cfg["signals"] = {}
        broker = PaperPortfolio(self.path, cfg)
        self.assertGreaterEqual(broker.cooldown_seconds, 6 * 3600)


if __name__ == "__main__":
    unittest.main()
