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
    
    trades.append({
        'side': side, 'entry': entry_px, 'exit': exit_px,
        'pnl': pnl, 'hold_s': hold_s,
        'exit_t': exit_t, 'entry_t': entry_t,
        'position_id': ex.position_id,
    })

trades.sort(key=lambda x: x['exit_t'])

# SPLIT: V12.14+ restart at ~09:43 (gap after 09:18:10)
SPLIT_TIME = datetime(2026, 5, 20, 9, 43, 0)

before = [t for t in trades if t['exit_t'] < SPLIT_TIME]
after = [t for t in trades if t['exit_t'] >= SPLIT_TIME]

def compute_stats(trade_list, label):
    if not trade_list:
        print(f"\n{'='*70}")
        print(f"  {label}: NO TRADES")
        print(f"{'='*70}")
        return {}
    
    pnls = [t['pnl'] for t in trade_list]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    breakevens = [p for p in pnls if p == 0]
    total = len(pnls)
    
    wr = len(wins)/total*100 if total else 0
    avg_w = sum(wins)/len(wins) if wins else 0
    avg_l = abs(sum(losses)/len(losses)) if losses else 0
    rr = avg_w/avg_l if avg_l > 0 else 0
    pnl_total = sum(pnls)
    
    big_wins = [p for p in pnls if p >= 10]
    big_losses = [p for p in pnls if p <= -10]
    
    session_min = (trade_list[-1]['exit_t'] - trade_list[0]['entry_t']).total_seconds()/60 if len(trade_list)>1 else 0
    tpm = total/session_min if session_min else 0
    
    avg_hold = sum(t['hold_s'] for t in trade_list)/total
    
    buys = [t for t in trade_list if t['side'] == 'BUY']
    sells = [t for t in trade_list if t['side'] == 'SELL']
    buy_wr = len([t for t in buys if t['pnl'] > 0])/len(buys)*100 if buys else 0
    sell_wr = len([t for t in sells if t['pnl'] > 0])/len(sells)*100 if sells else 0
    
    # Hold time buckets
    hold_buckets = {'0-2s': [], '3-5s': [], '6-10s': [], '11-30s': [], '31-60s': [], '60+s': []}
    for t in trade_list:
        h = t['hold_s']
        if h <= 2: hold_buckets['0-2s'].append(t)
        elif h <= 5: hold_buckets['3-5s'].append(t)
        elif h <= 10: hold_buckets['6-10s'].append(t)
        elif h <= 30: hold_buckets['11-30s'].append(t)
        elif h <= 60: hold_buckets['31-60s'].append(t)
        else: hold_buckets['60+s'].append(t)
    
    # Streaks
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
    
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")
    print(f"  Period: {trade_list[0]['entry_t'].strftime('%H:%M:%S')} -> {trade_list[-1]['exit_t'].strftime('%H:%M:%S')}")
    print(f"  Duration: {session_min:.0f} min")
    print(f"  Total trades: {total}")
    print(f"  Wins: {len(wins)} | Losses: {len(losses)} | Breakeven: {len(breakevens)}")
    print(f"  WR: {wr:.1f}%")
    print(f"  PnL Total: {pnl_total:+.0f} pts")
    print(f"  Avg Win: {avg_w:+.1f} | Avg Loss: {avg_l:+.1f} | R:R: {rr:.2f}")
    print(f"  TPM: {tpm:.2f}")
    print(f"  Avg Hold: {avg_hold:.1f}s")
    print(f"  Big wins (>=+10): {len(big_wins)} sum={sum(big_wins):+.0f}")
    print(f"  Big losses (<=-10): {len(big_losses)} sum={sum(big_losses):+.0f}")
    print(f"  Breakeven freq: {len(breakevens)/total*100:.1f}%")
    print(f"  Max win streak: {max_win_streak} | Max loss streak: {max_loss_streak}")
    print(f"  BUY: {len(buys)} WR={buy_wr:.1f}% PnL={sum(t['pnl'] for t in buys):+.0f}")
    print(f"  SELL: {len(sells)} WR={sell_wr:.1f}% PnL={sum(t['pnl'] for t in sells):+.0f}")
    
    print(f"\n  Hold time distribution:")
    for bucket, btrades in hold_buckets.items():
        if btrades:
            bp = [t['pnl'] for t in btrades]
            bw = [p for p in bp if p > 0]
            bl = [p for p in bp if p < 0]
            bwr = len(bw)/len(bp)*100 if bp else 0
            print(f"    {bucket}: {len(bp):4d} trades WR={bwr:.1f}% PnL={sum(bp):+.0f} avgPnL={sum(bp)/len(bp):+.1f}")
    
    # PnL distribution
    print(f"\n  PnL distribution:")
    bins = [(-999,-20), (-20,-10), (-10,-5), (-5,-1), (-1,0), (0,0), (0,1), (1,5), (5,10), (10,20), (20,999)]
    for lo, hi in bins:
        if lo == 0 and hi == 0:
            count = len([p for p in pnls if p == 0])
            label_str = "=0"
        elif hi > 0 and lo >= 0:
            count = len([p for p in pnls if lo < p <= hi])
            label_str = f"+{lo} to +{hi}" if lo > 0 else f"0 to +{hi}"
        else:
            count = len([p for p in pnls if lo <= p < hi])
            label_str = f"{lo} to {hi}"
        if count > 0:
            bar = '#' * min(count, 50)
            print(f"    {label_str:>12s}: {count:4d} {bar}")
    
    return {
        'total': total, 'wr': wr, 'pnl': pnl_total,
        'avg_w': avg_w, 'avg_l': avg_l, 'rr': rr,
        'tpm': tpm, 'big_wins': len(big_wins), 'big_losses': len(big_losses),
        'breakeven_pct': len(breakevens)/total*100 if total else 0,
        'trades': trade_list, 'pnls': pnls,
    }

b_stats = compute_stats(before, "BEFORE V12.14+ (06:00-09:18)")
a_stats = compute_stats(after, "AFTER V12.14+ (09:43-...)")


# ========== COUNTERFACTUAL SIMULATIONS ==========
print(f"\n{'='*70}")
print(f"  COUNTERFACTUAL SIMULATIONS (using ALL today's trades)")
print(f"{'='*70}")

all_trades = trades

# Helper: simulate changed config on a trade
# For a BUY: adverse = entry - low_point (we don't have intra-trade high/low)
# We only have entry/exit prices. We need to infer what happened.
# Key insight: we know exit price + PnL. For losses:
#   BUY trade: pnl = exit - entry. If pnl < 0, exit < entry.
#   The ACTUAL loss = entry - exit (for BUY).
#   But we don't know the MAX adverse excursion (MAE).
#   We DO know the final exit. So we can only simulate what happens
#   if we change the exit THRESHOLD, not the intra-trade path.

# For loss_min/loss_max: these are adverse thresholds checked on each tick.
# If adverse >= loss_min AND we're past min_hold -> loss_exit
# If adverse > loss_max -> immediate loss_exit
# We can't simulate tick-by-tick, but we CAN:
# 1. For trades that exited with loss > X: they WOULD have exited at X if threshold was X
# 2. For trades that exited with small loss: if we LOWER loss_min, more trades get caught

# === M1: loss_max_pts 35 -> 20 ===
# Hypothesis: trades with loss > 20pts would have been cut at 20pts
# For trades with loss <= 20: unchanged
# For trades with loss > 20: pnl becomes -20 instead of actual loss
# CAVEAT: some trades that lost >20 may have first been profitable then reversed
# We can't know the path, but given avg hold=15s and these are momentum trades,
# it's unlikely they went +20 then back to -20. Conservative: assume cut at -20.

print("\n--- M1: loss_max_pts 35->20 ---")
print("  Hypothesis: cut big losses at -20pts instead of letting them reach -35+")
print("  Method: for trades with pnl < -20, cap loss at -20")
print()

m1_trades = []
for t in all_trades:
    nt = dict(t)
    if t['pnl'] < -20:
        nt['pnl'] = -20
        nt['simulated'] = True
        nt['original_pnl'] = t['pnl']
    else:
        nt['simulated'] = False
    m1_trades.append(nt)

m1_pnls = [t['pnl'] for t in m1_trades]
m1_wins = [p for p in m1_pnls if p > 0]
m1_losses = [p for p in m1_pnls if p < 0]
m1_total = len(m1_pnls)
m1_wr = len(m1_wins)/m1_total*100 if m1_total else 0
m1_avg_w = sum(m1_wins)/len(m1_wins) if m1_wins else 0
m1_avg_l = abs(sum(m1_losses)/len(m1_losses)) if m1_losses else 0
m1_rr = m1_avg_w/m1_avg_l if m1_avg_l > 0 else 0
m1_pnl = sum(m1_pnls)

affected_m1 = [t for t in m1_trades if t.get('simulated')]
affected_pnl_m1 = sum(t['original_pnl'] for t in affected_m1) - sum(t['pnl'] for t in affected_m1)

print(f"  Trades affected: {len(affected_m1)}")
print(f"  PnL saved by capping: {affected_pnl_m1:+.0f} pts")
print(f"  Original PnL: {sum(t['pnl'] for t in all_trades):+.0f} | Simulated PnL: {m1_pnl:+.0f}")
print(f"  WR: {sum(1 for t in all_trades if t['pnl']>0)/m1_total*100:.1f}% -> {m1_wr:.1f}%")
print(f"  Avg Win: {sum(p for p in [t['pnl'] for t in all_trades] if p>0)/max(1,len([p for p in [t['pnl'] for t in all_trades] if p>0])):+.1f} -> {m1_avg_w:+.1f}")
print(f"  Avg Loss: {abs(sum(p for p in [t['pnl'] for t in all_trades] if p<0)/max(1,len([p for p in [t['pnl'] for t in all_trades] if p<0]))):+.1f} -> {m1_avg_l:+.1f}")
print(f"  R:R: {sum(p for p in [t['pnl'] for t in all_trades] if p>0)/max(1,sum(abs(p) for p in [t['pnl'] for t in all_trades] if p<0)) if any(p<0 for p in [t['pnl'] for t in all_trades]) else 0:.2f} -> {m1_rr:.2f}")

# Show affected trades
if affected_m1:
    print(f"\n  Affected trades (loss > -20 capped to -20):")
    for t in affected_m1[:20]:
        print(f"    {t['exit_t'].strftime('%H:%M:%S')} {t['side']:4s} original={t['original_pnl']:+.0f} -> capped=-20 saved={t['original_pnl']+20:+.0f}")


# === M2: trailing_virtual_offset_pts 8 -> 15 ===
# Hypothesis: current offset=8 is too tight, cuts winners at breakeven too early
# Effect: trades that hit breakeven_stop at ~+1-2pts would have run further
# We can't simulate trailing behavior without tick data, BUT we can infer:
# Trades with pnl +1 to +5 that were likely cut by virtual trailing:
# If offset was 15, they would need +15+8=+23pts adverse to be stopped
# More likely: they'd run longer and potentially get bigger wins
# We CANNOT simulate this precisely without tick data.
# BUT we can estimate: among winning trades, count how many have pnl <= +5 (likely vtrail cuts)
# and estimate what their PnL would be if they ran to +15 avg instead

print(f"\n--- M2: trailing_virtual_offset_pts 8->15 ---")
print("  Hypothesis: virtual trailing at 8pts cuts winners too early")
print("  Limitation: CANNOT simulate without intra-trade tick data")
print("  Proxy: count trades likely cut by virtual trailing (pnl +1 to +5)")
print()

vtrail_cut_candidates = [t for t in all_trades if 0 < t['pnl'] <= 5]
micro_wins = [t for t in all_trades if t['pnl'] == 1]
small_wins = [t for t in all_trades if 1 < t['pnl'] <= 5]
bigger_wins = [t for t in all_trades if t['pnl'] > 5]

print(f"  Micro wins (pnl=+1): {len(micro_wins)} trades, sum={sum(t['pnl'] for t in micro_wins):+.0f}")
print(f"  Small wins (pnl=+2 to +5): {len(small_wins)} trades, sum={sum(t['pnl'] for t in small_wins):+.0f}")
print(f"  Bigger wins (pnl>+5): {len(bigger_wins)} trades, sum={sum(t['pnl'] for t in bigger_wins):+.0f}")
print(f"  Total vtrail candidates (pnl +1 to +5): {len(vtrail_cut_candidates)}")
print(f"  These account for {len(vtrail_cut_candidates)/max(1,len([t for t in all_trades if t['pnl']>0]))*100:.0f}% of all wins")
print(f"  If offset=15, some of these +1/+2 wins could have been +5/+10 wins")
print(f"  Conservative estimate: 30% of +1/+2 trades reach +5 avg instead")
pct_upgraded = 0.30
upgraded = [t for t in all_trades if 0 < t['pnl'] <= 2]
estimated_gain = len(upgraded) * pct_upgraded * (5 - 1.5)
print(f"  Est. trades upgraded: {len(upgraded)*pct_upgraded:.0f}")
print(f"  Est. PnL gain: {estimated_gain:+.0f} pts")
print(f"  Risk: some trades that won +1/+2 would reverse to losses if held longer")
print(f"  Conservative risk: 10% of upgraded trades become -5 losses")
estimated_risk = len(upgraded) * pct_upgraded * 0.10 * 5
print(f"  Est. PnL risk: {estimated_risk:+.0f} pts")
print(f"  Net est. impact: {estimated_gain - estimated_risk:+.0f} pts")


# === M3: loss_min_pts 18 -> 12 ===
# Hypothesis: enter exit zone earlier, cut losses before they reach 18-35pts
# Effect: trades currently exiting at 18-35pts adverse would exit at 12pts
# But: more trades would be caught in the exit zone, including some that would
# have recovered. This could hurt WR.
# We can identify trades that exited with loss >= 12 (already caught)
# and trades with loss between 12-18 (NEW catches with lower threshold)
# Problem: we don't know which winning trades dipped to -12 to -18 first

print(f"\n--- M3: loss_min_pts 18->12 ---")
print("  Hypothesis: enter exit zone at 12pts adverse instead of 18pts")
print("  Effect: losses between 12-18pts get cut earlier")
print()

# Trades with loss between 12-18 (these would be NEW catches)
loss_12_18 = [t for t in all_trades if -18 <= t['pnl'] <= -12]
loss_18_plus = [t for t in all_trades if t['pnl'] < -18]
loss_below_12 = [t for t in all_trades if -12 < t['pnl'] < 0]

print(f"  Current loss distribution:")
print(f"    Loss 0 to -12: {len(loss_below_12)} trades, sum={sum(t['pnl'] for t in loss_below_12):+.0f}")
print(f"    Loss -12 to -18: {len(loss_12_18)} trades, sum={sum(t['pnl'] for t in loss_12_18):+.0f} [NEW catches]")
print(f"    Loss > -18: {len(loss_18_plus)} trades, sum={sum(t['pnl'] for t in loss_18_plus):+.0f}")

# With loss_min=12, any trade going adverse >=12 would trigger loss_exit
# But loss_exit also checks min_hold_seconds (5s) and uses reversal logic
# Some trades in the -12 to -18 range may have recovered to small wins
# We need to count: trades that ended as wins but MAY have dipped to -12 to -18 first
# Since we can't know intra-trade MAE, we approximate:

# Conservative: Assume ALL trades with final loss in [-12, -18] would be caught at -12
# And 0% of winning trades would be falsely caught (they didn't dip that far)
print(f"\n  Direct impact: {len(loss_12_18)} trades in [-12,-18] would exit at -12 instead")
savings_m3 = sum(-12 - t['pnl'] for t in loss_12_18)
print(f"  PnL savings from earlier exit: {savings_m3:+.0f} pts")

# Count how many trades ended as small wins (0 to +5) but might have had MAE >= 12
# Without tick data, we estimate based on hold time: longer holds more likely to dip
small_wins_long_hold = [t for t in all_trades if 0 < t['pnl'] <= 5 and t['hold_s'] >= 10]
small_wins_short_hold = [t for t in all_trades if 0 < t['pnl'] <= 5 and t['hold_s'] < 10]
print(f"\n  Risk analysis: small wins that might have dipped to -12 first")
print(f"    Small wins (pnl 0-+5) with hold >= 10s: {len(small_wins_long_hold)} (more likely to have dipped)")
print(f"    Small wins (pnl 0-+5) with hold < 10s: {len(small_wins_short_hold)} (less likely)")
print(f"    Conservative: 20% of {len(small_wins_long_hold)} long-hold small wins would be falsely cut at -12")
false_cuts_m3 = int(len(small_wins_long_hold) * 0.20)
false_cut_pnl_m3 = false_cuts_m3 * 12
print(f"    Est. false cuts: {false_cuts_m3} trades")
print(f"    Est. false cut PnL loss: -{false_cut_pnl_m3:.0f} pts (these would have been small wins)")
print(f"\n  Net M3 impact: {savings_m3:.0f} - {false_cut_pnl_m3:.0f} = {savings_m3 - false_cut_pnl_m3:+.0f} pts")
print(f"  Frequency impact: MORE exits at -12 -> more reentries -> TPM could increase")


# ========== FULL COMPARISON TABLE ==========
print(f"\n\n{'='*70}")
print(f"  FULL COMPARISON: ACTUAL vs SIMULATED (all today's trades)")
print(f"{'='*70}")

orig_pnls = [t['pnl'] for t in all_trades]
orig_wins = [p for p in orig_pnls if p > 0]
orig_losses = [p for p in orig_pnls if p < 0]
orig_wr = len(orig_wins)/len(orig_pnls)*100 if orig_pnls else 0
orig_avg_w = sum(orig_wins)/len(orig_wins) if orig_wins else 0
orig_avg_l = abs(sum(orig_losses)/len(orig_losses)) if orig_losses else 0
orig_rr = orig_avg_w/orig_avg_l if orig_avg_l else 0
orig_pnl = sum(orig_pnls)

def print_stat_row(label, wr, pnl, avg_w, avg_l, rr, n_trades):
    print(f"  {label:25s} | WR={wr:5.1f}% | PnL={pnl:+6.0f} | avgW={avg_w:+4.1f} | avgL={avg_l:+4.1f} | RR={rr:.2f} | N={n_trades}")

print_stat_row("ACTUAL", orig_wr, orig_pnl, orig_avg_w, orig_avg_l, orig_rr, len(orig_pnls))
print_stat_row("M1 (loss_max=20)", m1_wr, m1_pnl, m1_avg_w, m1_avg_l, m1_rr, m1_total)
print()
print("  M2 (vtrail offset=15): CANNOT simulate precisely (no tick data)")
print(f"    Est. net impact: +{estimated_gain - estimated_risk:.0f} pts (speculative)")
print()
print("  M3 (loss_min=12):")
m3_sim_pnl = orig_pnl + savings_m3 - false_cut_pnl_m3
m3_sim_losses_list = []
for t in all_trades:
    if -18 <= t['pnl'] <= -12:
        m3_sim_losses_list.append(-12)
    elif t['pnl'] < 0 and false_cuts_m3 > 0:
        m3_sim_losses_list.append(t['pnl'])
        false_cuts_m3 -= 1
    else:
        m3_sim_losses_list.append(t['pnl'])
m3_losses_sim = [p for p in m3_sim_losses_list if p < 0]
m3_avg_l = abs(sum(m3_losses_sim)/len(m3_losses_sim)) if m3_losses_sim else 0
m3_rr = orig_avg_w/m3_avg_l if m3_avg_l else 0
print(f"    Sim PnL={m3_sim_pnl:+.0f} | avgL~{m3_avg_l:.1f} | RR~{m3_rr:.2f}")


# ========== EXIT REASON ANALYSIS ==========
print(f"\n\n{'='*70}")
print(f"  EXIT REASON INFERENCE (based on PnL patterns)")
print(f"{'='*70}")

for label, trade_set in [("BEFORE", before), ("AFTER", after), ("ALL TODAY", all_trades)]:
    pnls_list = [t['pnl'] for t in trade_set]
    if not pnls_list:
        continue
    
    be_count = len([p for p in pnls_list if p == 0])
    micro_win = len([p for p in pnls_list if 0 < p <= 2])
    small_win = len([p for p in pnls_list if 2 < p <= 5])
    med_win = len([p for p in pnls_list if 5 < p <= 10])
    big_win = len([p for p in pnls_list if p > 10])
    
    micro_loss = len([p for p in pnls_list if -2 <= p < 0])
    small_loss = len([p for p in pnls_list if -5 <= p < -2])
    med_loss = len([p for p in pnls_list if -10 <= p < -5])
    loss_exit_range = len([p for p in pnls_list if -18 <= p < -10])
    loss_max_range = len([p for p in pnls_list if -35 <= p < -18])
    over_loss_max = len([p for p in pnls_list if p < -35])
    
    total_t = len(pnls_list)
    
    print(f"\n  {label} ({total_t} trades):")
    print(f"    Breakeven (pnl=0):       {be_count:4d} ({be_count/total_t*100:5.1f}%)  [likely: vtrail breakeven_stop]")
    print(f"    Micro wins (+1 to +2):   {micro_win:4d} ({micro_win/total_t*100:5.1f}%)  [likely: vtrail cut too early]")
    print(f"    Small wins (+3 to +5):   {small_win:4d} ({small_win/total_t*100:5.1f}%)")
    print(f"    Med wins (+6 to +10):    {med_win:4d} ({med_win/total_t*100:5.1f}%)")
    print(f"    Big wins (>+10):         {big_win:4d} ({big_win/total_t*100:5.1f}%)")
    print(f"    Micro losses (-1 to -2): {micro_loss:4d} ({micro_loss/total_t*100:5.1f}%)")
    print(f"    Small loss (-3 to -5):   {small_loss:4d} ({small_loss/total_t*100:5.1f}%)")
    print(f"    Med loss (-6 to -10):    {med_loss:4d} ({med_loss/total_t*100:5.1f}%)")
    print(f"    Loss exit (-11 to -18):  {loss_exit_range:4d} ({loss_exit_range/total_t*100:5.1f}%)  [loss_exit gate]")
    print(f"    Loss max (-19 to -35):   {loss_max_range:4d} ({loss_max_range/total_t*100:5.1f}%)  [loss_max or reversal]")
    print(f"    Over loss max (<-35):    {over_loss_max:4d} ({over_loss_max/total_t*100:5.1f}%)  [SL breach or reversal]")
    
    # Estimated exit reason distribution
    reversal_count = len([t for t in trade_set if t['pnl'] < -5 and t['hold_s'] < 8])
    slow_loss = len([t for t in trade_set if t['pnl'] < -5 and t['hold_s'] >= 8])
    print(f"\n    Inferred exit reasons:")
    print(f"      Quick reversal (<8s, loss>-5): {reversal_count}")
    print(f"      Slow loss (>=8s, loss>-5):     {slow_loss}")


# ========== ECHO TRADE ANALYSIS ==========
print(f"\n\n{'='*70}")
print(f"  ECHO TRADE / REENTRY QUALITY ANALYSIS")
print(f"{'='*70}")

for label, trade_set in [("BEFORE", before), ("AFTER", after)]:
    if len(trade_set) < 2:
        continue
    print(f"\n  {label}:")
    
    same_dir_after_loss = 0
    same_dir_after_loss_win = 0
    same_dir_after_loss_pnl = 0
    opp_dir_after_loss = 0
    opp_dir_after_loss_win = 0
    opp_dir_after_loss_pnl = 0
    quick_reentry = 0
    quick_reentry_win = 0
    
    for i in range(1, len(trade_set)):
        prev = trade_set[i-1]
        curr = trade_set[i]
        
        if prev['pnl'] < 0:
            same_side = (prev['side'] == curr['side'])
            gap_s = (curr['entry_t'] - prev['exit_t']).total_seconds() if curr['entry_t'] and prev['exit_t'] else 999
            
            if same_side:
                same_dir_after_loss += 1
                same_dir_after_loss_pnl += curr['pnl']
                if curr['pnl'] > 0:
                    same_dir_after_loss_win += 1
                if gap_s < 5:
                    quick_reentry += 1
                    if curr['pnl'] > 0:
                        quick_reentry_win += 1
            else:
                opp_dir_after_loss += 1
                opp_dir_after_loss_pnl += curr['pnl']
                if curr['pnl'] > 0:
                    opp_dir_after_loss_win += 1
    
    if same_dir_after_loss:
        print(f"    Same-dir after loss: {same_dir_after_loss} WR={same_dir_after_loss_win/same_dir_after_loss*100:.1f}% avgPnL={same_dir_after_loss_pnl/same_dir_after_loss:+.1f}")
    if opp_dir_after_loss:
        print(f"    Opp-dir after loss: {opp_dir_after_loss} WR={opp_dir_after_loss_win/opp_dir_after_loss*100:.1f}% avgPnL={opp_dir_after_loss_pnl/opp_dir_after_loss:+.1f}")
    if quick_reentry:
        print(f"    Quick reentry (<5s same-dir): {quick_reentry} WR={quick_reentry_win/quick_reentry*100:.1f}%")
    
    # Consecutive same-direction trades
    consec_same = 0
    consec_same_win = 0
    consec_same_pnl = 0
    for i in range(1, len(trade_set)):
        prev = trade_set[i-1]
        curr = trade_set[i]
        if prev['side'] == curr['side'] and prev['pnl'] > 0:
            consec_same += 1
            consec_same_pnl += curr['pnl']
            if curr['pnl'] > 0:
                consec_same_win += 1
    if consec_same:
        print(f"    Same-dir after WIN: {consec_same} WR={consec_same_win/consec_same*100:.1f}% avgPnL={consec_same_pnl/consec_same:+.1f}")


mt5.shutdown()
print("\n\nDone.")
