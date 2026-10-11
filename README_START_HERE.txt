BUZZ HUNTER 2.0 — CLEAN START — PAPER TRADING ONLY

WHAT'S INCLUDED
Complete independent Python app, config, Coinbase market feed, optional Google Trends,
portfolio/risk management, automated tests, Dockerfile and Railway start configuration.
No X, Reddit, Telegram, API secrets, or live trading credentials are needed.

IMPORTANT: A ZIP cannot be directly run by Railway. Its contents must be added to
GitHub with the exact folder structure. Do not upload the ZIP itself as a single file.

RECOMMENDED: Keep your old Railway service and old GitHub repository unchanged as backup.
Create a NEW private GitHub repository named buzz-hunter-2 and upload the contents
of this ZIP into the repository ROOT. Ensure Dockerfile, config.yaml, and the
buzzhunter/ folder appear at the root (not inside an extra Buzz_Hunter_2_0 folder).

1. In GitHub create a new PRIVATE repository buzz-hunter-2.
2. Upload all the ZIP contents, preserving the buzzhunter/ and tests/ folders.
   GitHub mobile upload may not preserve folders; a desktop browser, GitHub app,
   or a GitHub-connected tool may be easier. We can guide you one step at a time.
3. In Railway create a NEW service from that repository.
4. Under service Settings > Deploy, use the Dockerfile builder (if prompted).
   The Dockerfile already sets the startup command; leave Custom Start Command BLANK.
   Do not use a one-off `--once` flag in Railway.
5. In Railway add a persistent VOLUME mounted at /data BEFORE the first run.
   The bot will save paper_state.json and status.json there. A volume preserves
   the $1,000 account and paper trade history across restarts/redeploys.
6. Deploy. In Deploy Logs expect 'BUZZ HUNTER 2.0 STARTING - PAPER MODE ONLY',
   then 'MARKET SCAN START' and 'MARKET SCAN COMPLETE'. It remains running.
7. No credentials are needed. NEVER enter a Coinbase trading key: live orders
   are deliberately not implemented.

FIRST START: creates a FRESH simulated $1,000 balance. If /data already contains
paper_state.json, the bot resumes that balance instead of resetting it.

CONFIG: risk limits, watchlist, score threshold, and polling interval are in
config.yaml. Google Trends is OPTIONAL: failures fall back to market-only signals.
Google Trends is unofficial and may be throttled or unavailable.

LIMITATIONS: Public Coinbase Exchange API access depends on network availability;
market data can fail or be delayed. Scans are approximately every two minutes plus
processing time. This is an experimental paper-trading strategy, not a proven
profitable strategy. Stop-loss and profit targets execute at observed scan prices
with simulated fees/slippage; they do not guarantee a fill at the threshold.

LOCAL TESTS (optional):
  python -m pip install -r requirements.txt
  python -m unittest discover -s tests -v
  python -u -m buzzhunter.main --config config.yaml --once
