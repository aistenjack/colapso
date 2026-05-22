import sys, os
sys.path.insert(0, r'D:\Documentos\Projects\colapso\hft_bot')
import MetaTrader5 as mt5
from config.settings import Settings
from datetime import datetime, timedelta
from collections import defaultdict, Counter

s = Settings()
mt5.initialize(path=s.mt5.path)
if s.mt5.login:
    mt5.login(login=s.mt5.login, password=s.mt5.password, server=s.mt5.server)

symbol = s.trading.symbol
magic = s.trading.magic_number

from_dt = datetime(2026, 5, 20, 6, 0, 0)
to_dt = datetime(2026, 5, 20, 23, 59, 59)

deals = mt5.history_deals_get(from_dt, to_dt, group=f'*{symbol}*')
our = [d for d in deals if d.magic == magic]

entries = sorted([d for d in our if d.entry == 0], key=lambda x: x.time)
exits = sorted([d for d in our if d.entry == 1], key=lambda x: x.time)

print(f"Total deals: {len(our)} | Entries: {len(entries)} | Exits: {len(exits)}")

trades = []
used_entries = set()
for ex in exits:
    matching = [e for e in entries if e.position_id == ex.position_id and e.position_id not in used_entries]
    if not matching:
        matching = [e for e in entries if e.position_id == ex.position_id]
    entry = matching[0] if matching else None
    if entry:
        used_entries.add(entry.position_id)
    
    pnl = ex.profit
    side = 'BUY' if ex.type == 1 else 'SELL'
    entry_px = entry.price if entry else 0.0
    exit_px = ex.price
    entry_t = datetime.fromtimestamp(entry.time) if entry else None
    exit_t = datetime.fromtimestamp(ex.time)
    hold_s = (ex.time - entry.time) if entry else 0
    entry_type = entry.type if entry else -1
    
    if entry:
        is_reversal = (entry.type == 0 and ex.type == 1) or (entry.type == 1 and ex.type == 0)
    else:
        is_reversal = False
    
    trades.append({
        'side': side, 'entry': entry_px, 'exit': exit_px,
        'pnl': pnl, 'hold_s': hold_s,
        'exit_t': exit_t, 'entry_t': entry_t,
        'position_id': ex.position_id,
        'is_reversal': is_reversal,
        'entry_type': entry_type,
    })

trades.sort(key=lambda x: x['exit_t'])

print(f"Matched trades: {len(trades)}")
print()

# V12.14+ code was modified 20/05 10:38-10:53
# Bot likely restarted around that time
# Find a gap in trading activity that suggests restart
print("=== TRADE TIMELINE (looking for restart gap) ===")
for i, t in enumerate(trades):
    if t['exit_t'].hour >= 9 and t['exit_t'].hour <= 11:
        gap = ""
        if i > 0:
            gap_s = (t['entry_t'] - trades[i-1]['exit_t']).total_seconds() if t['entry_t'] and trades[i-1]['exit_t'] else 0
            if gap_s > 30:
                gap = f" <<< GAP={gap_s:.0f}s"
        print(f"  {t['exit_t'].strftime('%H:%M:%S')} {t['side']:4s} entry={t['entry']:.0f} exit={t['exit']:.0f} pnl={t['pnl']:+.0f} hold={t['hold_s']:.0f}s rev={t['is_reversal']}{gap}")

# Find the biggest gap between 09:30 and 11:00
print()
print("=== BIGGEST GAPS (potential restart) 09:00-11:30 ===")
gaps = []
for i in range(1, len(trades)):
    if trades[i]['entry_t'] and trades[i-1]['exit_t']:
        if 9 <= trades[i]['exit_t'].hour <= 11:
            gap_s = (trades[i]['entry_t'] - trades[i-1]['exit_t']).total_seconds()
            if gap_s > 10:
                gaps.append((gap_s, i, trades[i-1], trades[i]))

gaps.sort(reverse=True)
for gap_s, idx, prev_t, next_t in gaps[:10]:
    print(f"  Gap={gap_s:.0f}s between {prev_t['exit_t'].strftime('%H:%M:%S')} ({prev_t['side']} pnl={prev_t['pnl']:+.0f}) and {next_t['entry_t'].strftime('%H:%M:%S')} ({next_t['side']})")

# Detailed minute-by-minute trade count to find the gap
print()
print("=== TRADES PER MINUTE 09:00-11:30 ===")
by_minute = defaultdict(int)
for t in trades:
    if 9 <= t['exit_t'].hour <= 11:
        key = t['exit_t'].strftime('%H:%M')
        by_minute[key] += 1

for m in sorted(by_minute.keys()):
    if 9 <= int(m.split(':')[0]) <= 11:
        bar = '#' * by_minute[m]
        print(f"  {m}: {by_minute[m]:3d} {bar}")

# Side distribution per 30-min window
print()
print("=== SIDE + REVERSAL DISTRIBUTION PER 30min WINDOW ===")
windows = defaultdict(lambda: {'buy': 0, 'sell': 0, 'reversal': 0, 'total': 0})
for t in trades:
    h = t['exit_t'].hour
    m = t['exit_t'].minute
    window = f"{h:02d}:{m//30*30:02d}"
    windows[window]['total'] += 1
    if t['side'] == 'BUY':
        windows[window]['buy'] += 1
    else:
        windows[window]['sell'] += 1
    if t['is_reversal']:
        windows[window]['reversal'] += 1

for w in sorted(windows.keys()):
    d = windows[w]
    rev_pct = d['reversal']/d['total']*100 if d['total'] else 0
    print(f"  {w} | {d['total']:4d} trades | BUY={d['buy']:3d} SELL={d['sell']:3d} | Rev={d['reversal']:3d} ({rev_pct:.0f}%)")

mt5.shutdown()
