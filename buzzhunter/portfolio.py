"""Persistent paper-only broker with UTC daily-loss lockout and atomic writes."""
import json
import os
import time
from pathlib import Path
from .core import utc_day

class PaperPortfolio:
    def __init__(self, path, config):
        self.path = Path(path)
        self.risk = config['risk']
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {
            'cash': float(config['starting_cash']), 'positions': {}, 'trades': [],
            'day': utc_day(time.time()), 'day_start_equity': float(config['starting_cash']),
            'blocked_until_day': None}
        self.state.setdefault('blocked_until_day', None)
        self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.state, indent=2))
        os.replace(temp, self.path)

    def equity(self, prices):
        return self.state['cash'] + sum(p['quantity'] * prices.get(s, p['entry_price']) for s,p in self.state['positions'].items())

    def day_check(self, prices, now):
        day = utc_day(now)
        if day != self.state['day']:
            self.state['day'] = day
            self.state['day_start_equity'] = self.equity(prices)
            self.state['blocked_until_day'] = None
            self.save()
        if self.equity(prices) <= self.state['day_start_equity'] - self.risk['max_daily_loss_usd']:
            self.state['blocked_until_day'] = day
            self.save()

    def halted(self, prices):
        return self.state['blocked_until_day'] == self.state['day'] or self.equity(prices) <= self.state['day_start_equity'] - self.risk['max_daily_loss_usd']

    def buy(self, symbol, price, prices, now):
        r = self.risk
        if symbol in self.state['positions'] or len(self.state['positions']) >= r['max_positions'] or self.halted(prices):
            return False
        exposure = sum(p['quantity'] * prices.get(s,p['entry_price']) for s,p in self.state['positions'].items())
        amount = min(r['trade_usd'], self.state['cash'] / (1+r['assumed_fee_pct_per_side']), r['max_exposure_usd']-exposure)
        if amount < 10: return False
        execution = price * (1+r['assumed_slippage_pct_per_side'])
        # Defense in depth: reject any new entry whose simulated fill is not strictly below $1.
        # This restriction applies only to buys; exits remain unrestricted by price.
        if not (0 < execution < 1.0):
            return False
        fee = amount * r['assumed_fee_pct_per_side']
        qty = amount / execution
        self.state['cash'] -= amount + fee
        self.state['positions'][symbol] = dict(quantity=qty,entry_price=execution,peak=execution,cost=amount+fee,opened=now)
        self.state['trades'].append(dict(ts=now,side='BUY',symbol=symbol,qty=qty,price=execution,fee=fee))
        self.save()
        return True

    def sell(self, symbol, price, now, reason):
        if symbol not in self.state['positions']: return False
        p = self.state['positions'].pop(symbol)
        execution = price * (1-self.risk['assumed_slippage_pct_per_side'])
        proceeds = p['quantity'] * execution
        fee = proceeds * self.risk['assumed_fee_pct_per_side']
        self.state['cash'] += proceeds-fee
        self.state['trades'].append(dict(ts=now,side='SELL',symbol=symbol,qty=p['quantity'],price=execution,fee=fee,reason=reason,pnl=proceeds-fee-p['cost']))
        self.save()
        return True

    def exits(self, prices, now):
        for symbol,p in list(self.state['positions'].items()):
            if symbol not in prices: continue
            price = prices[symbol]
            p['peak'] = max(p['peak'],price)
            if price <= p['entry_price']*(1-self.risk['stop_loss_pct']): reason='stop_loss'
            elif price >= p['entry_price']*(1+self.risk['take_profit_pct']): reason='take_profit'
            elif p['peak'] >= p['entry_price']*1.05 and price <= p['peak']*(1-self.risk['trailing_stop_pct']): reason='trailing_stop'
            else: continue
            self.sell(symbol,price,now,reason)
        self.save()
