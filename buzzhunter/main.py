"""Buzz Hunter 3.0 continuously running PAPER-ONLY Coinbase signal scanner."""
import argparse
import json
import logging
import os
import time
from pathlib import Path
import yaml
from .core import entry_allowed, evaluate
from .market import CoinbaseFeed, CoinbaseRateLimitError
from .portfolio import PaperPortfolio
from .trends import TrendsFeed
from .strategy3 import confirm
log = logging.getLogger('buzzhunter')
def write_status(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data,indent=2))
    os.replace(tmp,path)
def validate(cfg):
    if cfg.get('mode')!='paper': raise ValueError('Paper mode only; no live orders')
    if int(cfg.get('poll_seconds',0))<30: raise ValueError('poll_seconds must be >=30')
    if not 1<=int(cfg.get('universe_limit',0))<=100: raise ValueError('universe_limit must be 1-100')
    if not 0<=float(cfg['signals']['minimum_score'])<=100: raise ValueError('Invalid minimum_score')
    if any(float(cfg['risk'][k])<=0 for k in ('trade_usd','max_positions','max_exposure_usd','max_daily_loss_usd')): raise ValueError('Invalid risk limits')
def scan(cfg,feed,trends,portfolio,status_path):
    now=time.time()
    symbols=feed.products(int(cfg['universe_limit']),cfg.get('watchlist',[]))
    symbols=list(dict.fromkeys(list(portfolio.state['positions'])+symbols))
    log.info('MARKET SCAN START symbols=%d held=%d',len(symbols),len(portfolio.state['positions']))
    prices,markets={},{}
    throttled=False
    for symbol in symbols:
        try:
            m=feed.market(symbol)
            prices[symbol],markets[symbol]=m['price'],m
        except CoinbaseRateLimitError as exc:
            throttled=True
            log.warning('Coinbase throttled %s: %s',symbol,exc)
            break
        except Exception as exc:
            log.warning('Skipping %s: %s',symbol,exc)
    missing_held=set(portfolio.state['positions'])-set(prices)
    if missing_held: log.error('Missing held prices %s; no new buys',sorted(missing_held))
    portfolio.day_check(prices,now)
    portfolio.exits(prices,now)
    # Request Trends only for a bounded shortlist of markets that meet hard entry gates.
    # This avoids spending Google requests on coins that cannot be purchased.
    risk = cfg['risk']
    preliminary = []
    for symbol, market in markets.items():
        if symbol in portfolio.state['positions']:
            continue
        price = market['price']
        if not (0 < price < 1 and price * (1 + risk['assumed_slippage_pct_per_side']) < 1):
            continue
        if not (0 <= market['change_24h_pct'] <= risk['max_entry_price_change_24h_pct']):
            continue
        if market['volume_usd_24h'] < risk['min_24h_quote_volume_usd'] or market['spread_pct'] > risk['max_spread_pct']:
            continue
        preliminary.append((evaluate(market).market_score, symbol))
    preliminary.sort(reverse=True)
    trend_limit = max(1, min(10, int(cfg.get('trends', {}).get('max_symbols_per_refresh', 8))))
    shortlist = [symbol for _, symbol in preliminary[:trend_limit]]
    trend_scores = trends.scores(shortlist)
    log.info('ENTRY PRECHECK candidates=%d trends_requested=%d trends_confirmed=%d',
             len(preliminary), len(shortlist), len(trend_scores))
    candidates=[]
    for symbol,m in markets.items():
        if symbol in portfolio.state['positions']: continue
        sig=evaluate(m,trend_scores.get(symbol))
        candidates.append((sig.score,symbol,sig,m))
    candidates.sort(reverse=True,key=lambda x:x[0])
    purchased=[]
    checks=0
    if not missing_held and not throttled and not portfolio.halted(prices):
        for score,symbol,sig,m in candidates:
            if not entry_allowed(sig,m,cfg): continue
            if cfg.get('advanced_signals',{}).get('enabled',False):
                if checks>=int(cfg['advanced_signals'].get('max_confirmation_checks_per_scan',5)): break
                checks+=1
                try: ok,reason=confirm(feed,symbol,cfg)
                except Exception as exc:
                    log.warning('Advanced confirmation unavailable %s: %s',symbol,exc)
                    continue
                if not ok:
                    log.info('Advanced confirmation rejected %s: %s',symbol,reason)
                    continue
            if portfolio.buy(symbol,m['price'],prices,now):
                purchased.append(symbol)
                log.info('PAPER BUY %s price=%.8f score=%.1f',symbol,m['price'],score)
    top=[{'symbol':s,'score':round(score,1),'eligible':entry_allowed(sig,m,cfg),'trend_available':sig.trend_score is not None} for score,s,sig,m in candidates[:10]]
    status={'timestamp_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(now)),
            'mode':'paper','markets_checked':len(markets),'markets_requested':len(symbols),
            'cash_usd':round(portfolio.state['cash'],2),'equity_usd':round(portfolio.equity(prices),2),
            'positions':list(portfolio.state['positions']),'paper_buys':purchased,
            'halted_for_day':portfolio.halted(prices),'missing_held_prices':sorted(missing_held),
            'coinbase_throttled':throttled,'advanced_checks':checks,'top_signals':top,
            'trends_confirmed_symbols':sorted(trend_scores),
            'trends_coverage_count':len(trend_scores),
            'entry_eligible_count':sum(entry_allowed(sig,m,cfg) for _,_,sig,m in candidates)}
    write_status(status_path,status)
    log.info('MARKET SCAN COMPLETE checked=%d equity=$%.2f cash=$%.2f positions=%d paper_buys=%d',len(markets),status['equity_usd'],status['cash_usd'],len(status['positions']),len(purchased))
    return status
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',default='config.yaml')
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(name)s: %(message)s',force=True)
    log.info('BUZZ HUNTER 3.0 STARTING - PAPER MODE ONLY')
    cfg=yaml.safe_load(Path(args.config).read_text())
    validate(cfg)
    data_dir=Path(os.getenv('BUZZ_DATA_DIR','/data' if Path('/data').is_dir() else 'data'))
    if not data_dir.is_dir():
        log.warning('Paper data directory %s does not exist yet; checking persistent storage configuration', data_dir)
    log.info('Paper data directory: %s (RAILWAY_VOLUME_MOUNT_PATH=%s)', data_dir, os.getenv('RAILWAY_VOLUME_MOUNT_PATH', 'unset'))
    mounted = os.getenv('RAILWAY_VOLUME_MOUNT_PATH')
    if os.getenv('RAILWAY_PROJECT_ID') and (not mounted or Path(mounted).resolve() != data_dir.resolve()):
        log.warning('Paper data directory does not match Railway volume mount; persistence may be at risk')
    portfolio=PaperPortfolio(data_dir/'paper_state.json',cfg)
    feed,trends=CoinbaseFeed(),TrendsFeed(cfg)
    while True:
        try: scan(cfg,feed,trends,portfolio,data_dir/'status.json')
        except Exception: log.exception('SCAN FAILED; retrying')
        if args.once: break
        time.sleep(max(30,int(cfg['poll_seconds'])))
if __name__=='__main__': main()
