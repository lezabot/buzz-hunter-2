BUZZ HUNTER 3.0 — PAPER-ONLY STRATEGY FILTER UPGRADE

This package includes:
  buzzhunter/strategy3.py  NEW: 5-minute candle and order-book confirmation
  buzzhunter/market.py     REPLACE: adds Coinbase candle and order-book fetches
  buzzhunter/main.py       REPLACE: checks advanced confirmation before each buy
  config.yaml              REPLACE: adds experimental advanced_signals settings

Upload config.yaml to the repository ROOT.
Upload the three .py files into the existing buzzhunter/ folder.
Do not upload README_UPLOAD.txt to the application unless you want to.
Commit changes on main; Railway should redeploy automatically.

Safety: PAPER ONLY. Google Trends remains MANDATORY for every new buy.
Entry prices must remain strictly below $1 after modeled slippage.
Existing positions can still be sold at any price.
If Google Trends returns 429, the bot will not make new buys.
Existing fixed stops, trailing stops, exposure and daily-loss controls remain.

The new advanced_signals.enabled flag is TRUE in this package.
To test the new logic without blocking buys, set it to false.
The new signal thresholds are HYPOTHESES, not proven profitable settings.

IMPORTANT LIMITATION: The original Trends feed still only requests configured
watchlist symbols. This upgrade does NOT claim to solve Trends rate limiting,
expand the Trends universe, or identify genuine manipulation with certainty.
The order-book metric is a snapshot and can be spoofed. Paper fills are modeled,
not executable exchange fills. Review logs after redeploy.
