import sys, os
sys.path.insert(0, r'D:\Documentos\Projects\colapso\hft_bot')
import MetaTrader5 as mt5
from config.settings import Settings
from datetime import datetime, timedelta
from collections import defaultdict

s = Settings()
mt5.initialize(path=s.mt5.path)
if s.mt5.login:
    mt5.login(login=s.mt5.login, password=s.mt5.password, server=s.mt5.server)

now = datetime.now()
from_dt = now.replace(hour=6, minute=0, second=0, microsecond=0)
to_dt = now

deals = mt5.history_deals_get(from_dt, to_dt, group=f'*{s.trading.symbol}*')
our = [d for d in deals if d.magic == s.trading.magic_number]

entries = [d for d in our if d.entry == 0]
exits = [d for d in our if d.entry == 1]

print(f'Today: {len(our)} deals, {len(entries)} entries, {len(exits)} exits')
print(f'Time range: {from_dt} to {to_dt}')
print()

trades = []
for ex in sorted(exits, key=lambda x: x.time):
    matching = [e for e in entries if e.position_id == ex.position_id]
    entry = matching[0] if matching else None
    pnl = ex.profit
    side = 'BUY' if ex.type == 1 else 'SELL'
    entry_px = entry.price if entry else 0.0
    exit_px = ex.price
    entry_t = datetime.fromtimestamp(entry.time) if entry else None
    exit_t = datetime.fromtimestamp(ex.time)
    hold_s = (ex.time - entry.time) if entry else 0
    trades.append({
        'side': side, 'entry': entry_px, 'exit': exit_px,
        'pnl': pnl, 'hold_s': hold_s,
        'exit_t': exit_t, 'entry_t': entry_t,
    })

pnls = [t['pnl'] for t in trades]
wins = [p for p in pnls if p > 0]
losses = [p for p in pnls if p < 0]
total = len(pnls)
wr = len(wins)/total*100 if total else 0
avg_w = sum(wins)/len(wins) if wins else 0
avg_l = sum(losses)/len(losses) if losses else 0

print(f'Total: {total} | WR: {wr:.1f}% | PnL: {sum(pnls):+.0f}')
print(f'AvgWin: {avg_w:+.1f} | AvgLoss: {avg_l:+.1f} | RR: {abs(avg_w/avg_l) if avg_l else 0:.2f}')

session_min = (trades[-1]['exit_t'] - trades[0]['entry_t']).total_seconds()/60 if len(trades)>1 else 0
tpm = total/session_min if session_min else 0
print(f'TPM: {tpm:.2f} | Session: {session_min:.0f}min')

print()
print('Last 30 trades:')
for t in trades[-30:]:
    print(f"  {t['exit_t'].strftime('%H:%M:%S')} {t['side']:4s} entry={t['entry']:.0f} exit={t['exit']:.0f} pnl={t['pnl']:+.0f} hold={t['hold_s']:.0f}s")

by_hour = defaultdict(list)
for t in trades:
    h = t['exit_t'].hour
    by_hour[h].append(t['pnl'])

print()
print('By hour:')
for h in sorted(by_hour.keys()):
    hp = by_hour[h]
    hw = [p for p in hp if p > 0]
    hl = [p for p in hp if p < 0]
    hwr = len(hw)/len(hp)*100 if hp else 0
    avgw = sum(hw)/len(hw) if hw else 0
    avgl = sum(hl)/len(hl) if hl else 0
    print(f'  {h:02d}:00 {len(hp):4d} trades WR={hwr:5.1f}% PnL={sum(hp):+6.0f} avgW={avgw:+.0f} avgL={avgl:+.0f}')

# Streak analysis
streak = 0
max_win_streak = 0
max_loss_streak = 0
cur_streak = 0
cur_is_win = None
for p in pnls:
    is_win = p > 0
    if is_win == cur_is_win:
        cur_streak += 1
    else:
        cur_is_win = is_win
        cur_streak = 1
    if is_win:
        max_win_streak = max(max_win_streak, cur_streak)
    else:
        max_loss_streak = max(max_loss_streak, cur_streak)

print(f'\nMax win streak: {max_win_streak} | Max loss streak: {max_loss_streak}')

# Big loss analysis
big_losses = [t for t in trades if t['pnl'] <= -10]
big_wins = [t for t in trades if t['pnl'] >= 10]
print(f'Big wins (>=+10): {len(big_wins)} trades, sum={sum(t["pnl"] for t in big_wins):+.0f}')
print(f'Big losses (<=-10): {len(big_losses)} trades, sum={sum(t["pnl"] for t in big_losses):+.0f}')

# Hold time vs PnL correlation
short_wins = [t for t in trades if t['hold_s'] <= 10 and t['pnl'] > 0]
short_losses = [t for t in trades if t['hold_s'] <= 10 and t['pnl'] < 0]
long_wins = [t for t in trades if t['hold_s'] > 30 and t['pnl'] > 0]
long_losses = [t for t in trades if t['hold_s'] > 30 and t['pnl'] < 0]

print(f'\nHold <=10s: {len(short_wins)}W {len(short_losses)}L avgPnL={(sum(t["pnl"] for t in short_wins)+sum(t["pnl"] for t in short_losses))/(len(short_wins)+len(short_losses)) if (len(short_wins)+len(short_losses)) else 0:+.1f}')
print(f'Hold >30s: {len(long_wins)}W {len(long_losses)}L avgPnL={(sum(t["pnl"] for t in long_wins)+sum(t["pnl"] for t in long_losses))/(len(long_wins)+len(long_losses)) if (len(long_wins)+len(long_losses)) else 0:+.1f}')

mt5.shutdown()
