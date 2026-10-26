"""Buzz Hunter paper-only scanner with market-only signals."""
import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import yaml
from .core import entry_allowed, evaluate, entry_rejection_reasons
from .market import CoinbaseFeed
from .portfolio import PaperPortfolio

log = logging.getLogger('buzzhunter')

def write_status(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)

def validate(cfg):
    if cfg.get('mode') != 'paper':
        raise ValueError('Only mode: paper is supported. No live orders are implemented.')
    if int(cfg.get('poll_seconds', 0)) < 30:
        raise ValueError('poll_seconds must be >= 30')
    if not (1 <= int(cfg.get('universe_limit', 0)) <= 100):
        raise ValueError('universe_limit must be between 1 and 100')
    if not (0 <= float(cfg['signals']['minimum_score']) <= 100):
        raise ValueError('minimum_score must be 0-100')
    if any(float(cfg['risk'][k]) <= 0 for k in ('trade_usd', 'max_positions', 'max_exposure_usd', 'max_daily_loss_usd')):
        raise ValueError('Risk limits must be positive')

def scan(cfg, feed, trends, portfolio, status_path):
    now = time.time()
    log.info('SCAN STEP: requesting product universe')
    symbols = feed.products(int(cfg['universe_limit']), cfg.get('watchlist', []))
    symbols = list(dict.fromkeys(symbols + list(portfolio.state['positions'])))
    log.info('MARKET SCAN START symbols=%d held=%d', len(symbols), len(portfolio.state['positions']))
    prices, markets = {}, {}
    for symbol in symbols:
        try:
            m = feed.market(symbol)
            prices[symbol], markets[symbol] = m['price'], m
        except Exception as exc:
            log.warning('Skipping %s: %s', symbol, exc)
    missing_held = set(portfolio.state['positions']) - set(prices)
    if missing_held:
        log.error('Missing prices for held positions %s; no new trades this scan', sorted(missing_held))
    portfolio.day_check(prices, now)
    portfolio.exits(prices, now)
    candidates = []
    for symbol, m in markets.items():
        if symbol in portfolio.state['positions']:
            continue
        signal = evaluate(m, config=cfg)
        candidates.append((signal.score, symbol, signal, m))
    candidates.sort(reverse=True, key=lambda row: row[0])
    checks = max(0, min(20, int(cfg['signals'].get('volume_spike_checks_per_scan', 12))))
    for _, symbol, _, m in [row for row in candidates if 0 < row[3]['price'] < 1][:checks]:
        try:
            m['volume_spike_pct'] = feed.volume_spike_15m(symbol)
        except Exception as exc:
            log.warning('Volume history unavailable %s: %s', symbol, exc)
    candidates = [(evaluate(m, config=cfg).score, symbol, evaluate(m, config=cfg), m)
                  for _, symbol, _, m in candidates]
    candidates.sort(reverse=True, key=lambda row: row[0])
    advanced = cfg.get('advanced_signals', {})
    if advanced.get('enabled', False):
        max_checks = int(advanced.get('max_confirmation_checks_per_scan', 5))
        preliminary = [(score, symbol, signal, m) for score, symbol, signal, m in candidates if not entry_rejection_reasons(signal, m, {**cfg, 'advanced_signals': {'enabled': False}})]
        for _, symbol, _, m in preliminary[:max_checks]:
            try:
                m['confirmation'] = feed.confirmation(symbol)
            except Exception as exc:
                log.warning('Confirmation unavailable %s: %s', symbol, exc)
    for score, symbol, signal, m in candidates[:10]:
        reasons = entry_rejection_reasons(signal, m, cfg)
        log.info('CANDIDATE %s score=%.1f price=%.8f volume24h=%.0f spread=%.4f change24h=%.2f spike15m=%s eligible=%s reasons=%s',
                 symbol, score, m['price'], m['volume_usd_24h'], m['spread_pct'],
                 m['change_24h_pct'], m.get('volume_spike_pct'), not reasons, reasons)
    purchased = []
    if not missing_held and not portfolio.halted(prices):
        for score, symbol, signal, m in candidates:
            if not entry_allowed(signal, m, cfg):
                continue
            if portfolio.buy(symbol, m['price'], prices, now):
                purchased.append(symbol)
                log.info('PAPER BUY %s price=%.8f score=%.1f', symbol, m['price'], score)
    top = [{'symbol': s, 'score': round(score, 1), 'eligible': entry_allowed(sig, m, cfg),
            'market_only': True, 'rejection_reasons': entry_rejection_reasons(sig, m, cfg), 'volume_spike_15m_pct': m.get('volume_spike_pct')} for score, s, sig, m in candidates[:10]]
    status = {'timestamp_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now)),
              'mode': 'paper', 'markets_checked': len(markets), 'markets_requested': len(symbols),
              'cash_usd': round(portfolio.state['cash'], 2), 'equity_usd': round(portfolio.equity(prices), 2),
              'positions': list(portfolio.state['positions']), 'paper_buys': purchased,
              'halted_for_day': portfolio.halted(prices), 'missing_held_prices': sorted(missing_held),
              'top_signals': top}
    write_status(status_path, status)
    log.info('MARKET SCAN COMPLETE checked=%d equity=$%.2f cash=$%.2f positions=%d paper_buys=%d top=%s',
             len(markets), status['equity_usd'], status['cash_usd'], len(status['positions']), len(purchased),
             ', '.join(f"{x['symbol']}:{x['score']}" for x in top[:5]))
    return status

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='config.yaml')
    parser.add_argument('--once', action='store_true', help='Run one scan then exit, for diagnostics only')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s', force=True, stream=sys.stdout)
    log.info('BUZZ HUNTER 3.1 STARTING - PAPER MODE ONLY (GOOGLE TRENDS DISABLED)')
    try:
        log.info('STARTUP STEP 1: loading config from %s (cwd=%s)', args.config, os.getcwd())
        cfg = yaml.safe_load(Path(args.config).read_text())
        log.info('STARTUP STEP 2: validating config')
        validate(cfg)
        log.info('STARTUP STEP 3: selecting data directory')
        data_dir = Path(os.getenv('BUZZ_DATA_DIR', '/data' if Path('/data').is_dir() else 'data'))
        log.info('Data directory: %s; poll every %ss; market-only scoring',
                 data_dir.resolve(), cfg['poll_seconds'])
        if not Path(data_dir).is_dir():
            log.warning('Data directory not present; creating it.')
        log.info('STARTUP STEP 4: initializing paper portfolio')
        portfolio = PaperPortfolio(data_dir / 'paper_state.json', cfg)
        log.info('STARTUP STEP 5: initializing Coinbase feed')
        feed = CoinbaseFeed()
        status_path = data_dir / 'status.json'
        log.info('STARTUP COMPLETE; beginning paper-only scan loop')
    except Exception:
        log.exception('STARTUP FAILED')
        raise
    failures = 0
    while True:
        try:
            scan(cfg, feed, None, portfolio, status_path)
            failures = 0
        except Exception:
            failures += 1
            log.exception('SCAN FAILED (attempt %d); will retry', failures)
        if args.once:
            break
        time.sleep(max(30, int(cfg['poll_seconds'])))

if __name__ == '__main__':
    main()
