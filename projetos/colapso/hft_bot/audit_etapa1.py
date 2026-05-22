import sys, os
sys.path.insert(0, r'D:\Documentos\Projects\colapso\hft_bot')
import MetaTrader5 as mt5
from config.settings import Settings
from datetime import datetime, timedelta
from collections import defaultdict

MIN_TRADES_REQUIRED = 50
MIN_BASELINE_REQUIRED = 50
IDEAL_TRADES = 100
MIN_SESSION_DURATION_MIN = 60
MIN_SESSIONS_REPRESENTED = 2

SESSION_BUCKETS = {
    "OPEN": ("09:00", "10:30"),
    "MIDDAY": ("10:30", "14:00"),
    "CLOSE": ("14:00", "18:00"),
}

BASELINE_CONFIG_LABEL = "offset=8.0"
TEST_CONFIG_LABEL = "offset=12.0"
CONFIG_PARAM = "trailing_virtual_offset_pts"
CONFIG_CHANGE = "8.0 -> 12.0"

LOG_PATHS = [
    r'D:\Documentos\Projects\colapso\hft_bot\logs\system.log',
    r'D:\Documentos\Projects\colapso\hft_bot\logs\trades.log',
]
RESTART_MARKERS = ["HFT Bot iniciando", "HFT Bot rodando", "STOP CONFIG"]

MANUAL_DEPLOY_TIME = None

s = Settings()
mt5.initialize(path=s.mt5.path)
if s.mt5.login:
    mt5.login(login=s.mt5.login, password=s.mt5.password, server=s.mt5.server)

symbol = s.trading.symbol
magic = s.trading.magic_number
today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
from_dt = today.replace(hour=6, 0, 0)
to_dt = datetime.now()

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


def get_session(exit_t):
    t_str = exit_t.strftime('%H:%M')
    for name, (start, end) in SESSION_BUCKETS.items():
        if start <= t_str < end:
            return name
    return None


# ======================================================================
# SPLIT DETECTION — Priority: 1) LOG 2) MANUAL 3) GAP FALLBACK
# ======================================================================
print("=" * 70)
print("  ETAPA 1 AUDITORIA: " + CONFIG_PARAM + " " + CONFIG_CHANGE)
print("=" * 70)
print(f"  Date: {from_dt.strftime('%Y-%m-%d')}")
print(f"  Total deals: {len(our)} | Entries: {len(entries)} | Exits: {len(exits)}")
print(f"  Matched trades: {len(trades)}")
print()

split_method = None
split_time = None
split_reason = None

# METHOD 1: LOG DETECTION
log_restart_times = []
for log_path in LOG_PATHS:
    if not os.path.exists(log_path):
        continue
    try:
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                line_ts = None
                for marker in RESTART_MARKERS:
                    if marker in line:
                        try:
                            ts_str = line[:19]
                            line_ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
                        except ValueError:
                            pass
                        if line_ts and line_ts >= from_dt:
                            log_restart_times.append((line_ts, marker, log_path, line.rstrip()[:120]))
                        break
    except Exception as e:
        print(f"  [WARN] Could not read {log_path}: {e}")

log_restart_times.sort(key=lambda x: x[0])

if log_restart_times:
    today_restarts = [r for r in log_restart_times if r[0].date() == from_dt.date()]
    if today_restarts:
        print("  LOG DETECTION — restart markers found today:")
        for ts, marker, path, line_preview in today_restarts[-10:]:
            fname = os.path.basename(path)
            print(f"    {ts.strftime('%H:%M:%S')} [{marker}] ({fname})")
        
        last_restart = today_restarts[-1][0]
        if len(today_restarts) >= 2:
            has_trades_before = any(t['exit_t'] < last_restart for t in trades)
            if has_trades_before:
                split_method = "LOG DETECTED"
                split_time = last_restart
                split_reason = f"Last restart marker today at {last_restart.strftime('%H:%M:%S')} with trades before and after"
        if not split_method and len(today_restarts) >= 1:
            has_trades_before = any(t['exit_t'] < last_restart for t in trades)
            if has_trades_before:
                split_method = "LOG DETECTED"
                split_time = last_restart
                split_reason = f"Only restart marker today at {last_restart.strftime('%H:%M:%S')} with trades before"

# METHOD 2: MANUAL TIMESTAMP
if not split_method and MANUAL_DEPLOY_TIME is not None:
    split_method = "MANUAL TIMESTAMP"
    split_time = MANUAL_DEPLOY_TIME
    split_reason = f"Manually set deploy time: {MANUAL_DEPLOY_TIME.strftime('%H:%M:%S')}"

# METHOD 3: GAP FALLBACK
if not split_method:
    gaps = []
    for i in range(1, len(trades)):
        if trades[i]['entry_t'] and trades[i-1]['exit_t']:
            gap_s = (trades[i]['entry_t'] - trades[i-1]['exit_t']).total_seconds()
            if gap_s > 120:
                gaps.append((gap_s, i, trades[i-1]['exit_t'], trades[i]['entry_t']))
    gaps.sort(reverse=True)
    if gaps:
        biggest = gaps[0]
        split_method = "GAP FALLBACK"
        split_time = biggest[2] + timedelta(seconds=1)
        split_reason = f"Gap={biggest[0]:.0f}s between {biggest[2].strftime('%H:%M:%S')} and {biggest[3].strftime('%H:%M:%S')} (lowest confidence)"

if not split_method:
    print("\n  *** CANNOT DETERMINE DEPLOY TIME ***")
    print("  No log markers, no manual timestamp, no significant gap found.")
    print("  Set MANUAL_DEPLOY_TIME in the script or restart the bot to generate log markers.")
    mt5.shutdown()
    sys.exit(1)

print(f"\n  Split method: {split_method}")
print(f"  Deploy time:  {split_time.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"  Reason:       {split_reason}")

# Split trades
baseline = [t for t in trades if t['exit_t'] < split_time]
test = [t for t in trades if t['exit_t'] >= split_time]

print(f"\n  BASELINE ({BASELINE_CONFIG_LABEL}): {len(baseline)} trades", end='')
if baseline:
    print(f" ({baseline[0]['entry_t'].strftime('%H:%M')}-{baseline[-1]['exit_t'].strftime('%H:%M')})")
else:
    print()
print(f"  TEST ({TEST_CONFIG_LABEL}):    {len(test)} trades", end='')
if test:
    print(f" ({test[0]['entry_t'].strftime('%H:%M')}-{test[-1]['exit_t'].strftime('%H:%M')})")
else:
    print()

# ======================================================================
# SAMPLE SIZE VALIDATION
# ======================================================================
print(f"\n{'='*70}")
print(f"  SAMPLE SIZE CHECK")
print(f"{'='*70}")
print(f"  Minimum required: {MIN_TRADES_REQUIRED} (baseline & test)")
print(f"  Good: 50+ | Ideal: {IDEAL_TRADES}+")
print(f"  Baseline trades: {len(baseline)}")
print(f"  Test trades:     {len(test)}")

def get_active_duration(trade_list):
    if len(trade_list) < 2:
        return 0
    return (trade_list[-1]['exit_t'] - trade_list[0]['entry_t']).total_seconds() / 60

def get_sessions_represented(trade_list):
    sessions = set()
    for t in trade_list:
        s = get_session(t['exit_t'])
        if s:
            sessions.add(s)
    return sessions

baseline_duration = get_active_duration(baseline)
test_duration = get_active_duration(test)
baseline_sessions = get_sessions_represented(baseline)
test_sessions = get_sessions_represented(test)

print(f"  Baseline active duration: {baseline_duration:.0f} min")
print(f"  Test active duration:     {test_duration:.0f} min")
print(f"  Baseline sessions: {sorted(baseline_sessions) if baseline_sessions else 'none'}")
print(f"  Test sessions:     {sorted(test_sessions) if test_sessions else 'none'}")

insufficient = False
reasons = []

if len(baseline) < MIN_BASELINE_REQUIRED:
    insufficient = True
    reasons.append(f"Baseline has {len(baseline)} trades (need {MIN_BASELINE_REQUIRED})")
if len(test) < MIN_TRADES_REQUIRED:
    insufficient = True
    reasons.append(f"Test has {len(test)} trades (need {MIN_TRADES_REQUIRED})")
if test_duration < MIN_SESSION_DURATION_MIN:
    insufficient = True
    reasons.append(f"Test active duration {test_duration:.0f} min < {MIN_SESSION_DURATION_MIN} min required")
if len(test_sessions) < MIN_SESSIONS_REPRESENTED:
    insufficient = True
    reasons.append(f"Test covers {len(test_sessions)} session(s) (need {MIN_SESSIONS_REPRESENTED})")

if insufficient:
    print(f"\n  *** INSUFFICIENT DATA ***")
    for r in reasons:
        print(f"    - {r}")
    if len(test) < MIN_TRADES_REQUIRED:
        print(f"    Need {MIN_TRADES_REQUIRED - len(test)} more test trades")
    if len(baseline) < MIN_BASELINE_REQUIRED:
        print(f"    Need {MIN_BASELINE_REQUIRED - len(baseline)} more baseline trades")
    print(f"\n  Classification: INSUFFICIENT DATA")
    print(f"  No verdict will be issued.")
    print(f"\n  Current test trades ({TEST_CONFIG_LABEL}):")
    for t in test[:50]:
        print(f"    {t['exit_t'].strftime('%H:%M:%S')} {t['side']:4s} entry={t['entry']:.0f} exit={t['exit']:.0f} pnl={t['pnl']:+.0f} hold={t['hold_s']:.0f}s")
    if len(test) > 50:
        print(f"    ... and {len(test)-50} more")
    mt5.shutdown()
    sys.exit(0)

# Confidence level
min_sample = min(len(baseline), len(test))
if min_sample >= IDEAL_TRADES:
    confidence = "HIGH CONFIDENCE"
elif min_sample >= 50:
    confidence = "MEDIUM CONFIDENCE"
else:
    confidence = "LOW CONFIDENCE"

print(f"\n  Confidence level: {confidence}")
if confidence != "HIGH CONFIDENCE":
    print(f"  [CAUTION] Sample size {min_sample} < {IDEAL_TRADES}. Results may contain noise.")


# ======================================================================
# SESSION DISTRIBUTION CHECK
# ======================================================================
print(f"\n{'='*70}")
print(f"  SESSION DISTRIBUTION CHECK")
print(f"{'='*70}")

def session_stats(trade_list):
    by_session = defaultdict(list)
    for t in trade_list:
        s = get_session(t['exit_t'])
        if s:
            by_session[s].append(t)
    return by_session

b_sess = session_stats(baseline)
t_sess = session_stats(test)

print(f"  {'Session':10s} | {'Baseline N':>10s} | {'Test N':>10s} | {'B WR%':>7s} | {'T WR%':>7s} | {'B PnL':>8s} | {'T PnL':>8s} | {'B TPM':>7s} | {'T TPM':>7s} | {'B avgH':>7s} | {'T avgH':>7s} | {'B avgW':>7s} | {'T avgW':>7s} | {'B avgL':>7s} | {'T avgL':>7s}")
print(f"  {'-'*10}-+-{'-'*10}-+-{'-'*10}-+-{'-'*7}-+-{'-'*7}-+-{'-'*8}-+-{'-'*8}-+-{'-'*7}-+-{'-'*7}-+-{'-'*7}-+-{'-'*7}-+-{'-'*7}-+-{'-'*7}-+-{'-'*7}-+-{'-'*7}")

session_imbalance = False
for sess_name in ["OPEN", "MIDDAY", "CLOSE"]:
    bt = b_sess.get(sess_name, [])
    tt = t_sess.get(sess_name, [])
    bn, tn = len(bt), len(tt)
    
    if bt:
        bw = [x for x in bt if x['pnl'] > 0]
        bwr = len(bw)/bn*100
        bpnl = sum(x['pnl'] for x in bt)
        bdur = get_active_duration(bt)
        btpm = bn/bdur if bdur > 0 else 0
        bhold = sum(x['hold_s'] for x in bt)/bn
        baw = sum(x['pnl'] for x in bw)/len(bw) if bw else 0
        bal = abs(sum(x['pnl'] for x in bt if x['pnl'] < 0)/max(1,len([x for x in bt if x['pnl'] < 0])))
    else:
        bwr = bpnl = btpm = bhold = baw = bal = 0
    
    if tt:
        tw = [x for x in tt if x['pnl'] > 0]
        twr = len(tw)/tn*100
        tpnl = sum(x['pnl'] for x in tt)
        tdur = get_active_duration(tt)
        ttpm = tn/tdur if tdur > 0 else 0
        thold = sum(x['hold_s'] for x in tt)/tn
        taw = sum(x['pnl'] for x in tw)/len(tw) if tw else 0
        tal = abs(sum(x['pnl'] for x in tt if x['pnl'] < 0)/max(1,len([x for x in tt if x['pnl'] < 0])))
    else:
        twr = tpnl = ttpm = thold = taw = tal = 0
    
    if bn == 0 and tn > 20:
        session_imbalance = True
    elif tn == 0 and bn > 20:
        session_imbalance = True
    elif bn > 0 and tn > 0:
        ratio = max(bn, tn) / min(bn, tn)
        if ratio > 3.0:
            session_imbalance = True
    
    print(f"  {sess_name:10s} | {bn:10d} | {tn:10d} | {bwr:6.1f}% | {twr:6.1f}% | {bpnl:+7.0f} | {tpnl:+7.0f} | {btpm:6.2f} | {ttpm:6.2f} | {bhold:6.1f} | {thold:6.1f} | {baw:+6.1f} | {taw:+6.1f} | {bal:+6.1f} | {tal:+6.1f}")

if session_imbalance:
    print(f"\n  [CAUTION] Session distribution imbalance detected")
    print(f"  Comparison may be biased by different market conditions.")


# ======================================================================
# FULL ANALYSIS FUNCTION
# ======================================================================
def full_analysis(trade_list, label):
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
    
    micro_wins = [t for t in trade_list if 0 < t['pnl'] <= 2]
    small_wins_3_5 = [t for t in trade_list if 2 < t['pnl'] <= 5]
    med_wins = [t for t in trade_list if 5 < t['pnl'] <= 10]
    big_wins = [t for t in trade_list if t['pnl'] > 10]
    big_wins_list = [t for t in trade_list if t['pnl'] >= 10]
    big_losses_list = [t for t in trade_list if t['pnl'] <= -10]
    
    # Winner truncation metrics
    winner_10_plus = [t for t in trade_list if t['pnl'] >= 10]
    winner_20_plus = [t for t in trade_list if t['pnl'] >= 20]
    winner_30_plus = [t for t in trade_list if t['pnl'] >= 30]
    winner_10_plus_pct = len(winner_10_plus)/total*100 if total else 0
    winner_20_plus_pct = len(winner_20_plus)/total*100 if total else 0
    winner_30_plus_pct = len(winner_30_plus)/total*100 if total else 0
    
    session_min = (trade_list[-1]['exit_t'] - trade_list[0]['entry_t']).total_seconds()/60 if len(trade_list)>1 else 0
    tpm = total/session_min if session_min else 0
    avg_hold = sum(t['hold_s'] for t in trade_list)/total
    
    buys = [t for t in trade_list if t['side'] == 'BUY']
    sells = [t for t in trade_list if t['side'] == 'SELL']
    buy_wr = len([t for t in buys if t['pnl'] > 0])/len(buys)*100 if buys else 0
    sell_wr = len([t for t in sells if t['pnl'] > 0])/len(sells)*100 if sells else 0
    
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
    
    # Drawdown streak analysis
    max_consecutive_loss_pnl = 0
    cur_loss_streak_pnl = 0
    max_drawdown_streak = 0
    cur_drawdown = 0
    for p in pnls:
        if p < 0:
            cur_loss_streak_pnl += p
            cur_drawdown += p
            max_consecutive_loss_pnl = min(max_consecutive_loss_pnl, cur_loss_streak_pnl)
            max_drawdown_streak = min(max_drawdown_streak, cur_drawdown)
        else:
            cur_loss_streak_pnl = 0
            if p > 0:
                cur_drawdown = min(0, cur_drawdown + p)
    
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")
    print(f"  Period: {trade_list[0]['entry_t'].strftime('%H:%M:%S')} -> {trade_list[-1]['exit_t'].strftime('%H:%M:%S')}")
    print(f"  Duration: {session_min:.0f} min")
    print(f"  Total trades: {total}")
    print(f"  WR: {wr:.1f}%")
    print(f"  PnL Total: {pnl_total:+.0f} pts")
    print(f"  R:R: {rr:.2f}")
    print(f"  Avg Win: {avg_w:+.1f}")
    print(f"  Avg Loss: {avg_l:+.1f}")
    print(f"  TPM: {tpm:.2f}")
    print(f"  Avg Hold: {avg_hold:.1f}s")
    print(f"  Max win streak: {max_win_streak} | Max loss streak: {max_loss_streak}")
    print(f"  BUY: {len(buys)} WR={buy_wr:.1f}% PnL={sum(t['pnl'] for t in buys):+.0f}")
    print(f"  SELL: {len(sells)} WR={sell_wr:.1f}% PnL={sum(t['pnl'] for t in sells):+.0f}")
    
    print(f"\n  WINNER DISTRIBUTION:")
    print(f"    Micro wins (+1/+2):   {len(micro_wins):4d} ({len(micro_wins)/total*100:5.1f}%) sum={sum(t['pnl'] for t in micro_wins):+.0f}")
    print(f"    Small wins (+3/+5):   {len(small_wins_3_5):4d} ({len(small_wins_3_5)/total*100:5.1f}%) sum={sum(t['pnl'] for t in small_wins_3_5):+.0f}")
    print(f"    Med wins (+6/+10):    {len(med_wins):4d} ({len(med_wins)/total*100:5.1f}%) sum={sum(t['pnl'] for t in med_wins):+.0f}")
    print(f"    Big wins (>+10):      {len(big_wins):4d} ({len(big_wins)/total*100:5.1f}%) sum={sum(t['pnl'] for t in big_wins):+.0f}")
    
    print(f"\n  WINNER TRUNCATION METRICS:")
    print(f"    +10 winners:  {len(winner_10_plus):4d} ({winner_10_plus_pct:5.1f}%) sum={sum(t['pnl'] for t in winner_10_plus):+.0f}")
    print(f"    +20 winners:  {len(winner_20_plus):4d} ({winner_20_plus_pct:5.1f}%) sum={sum(t['pnl'] for t in winner_20_plus):+.0f}")
    print(f"    +30 winners:  {len(winner_30_plus):4d} ({winner_30_plus_pct:5.1f}%) sum={sum(t['pnl'] for t in winner_30_plus):+.0f}")
    
    print(f"\n  LOSS DISTRIBUTION:")
    micro_losses = [t for t in trade_list if -2 <= t['pnl'] < 0]
    small_losses = [t for t in trade_list if -5 <= t['pnl'] < -2]
    med_losses = [t for t in trade_list if -10 <= t['pnl'] < -5]
    loss_exit_range = [t for t in trade_list if -18 <= t['pnl'] < -10]
    loss_max_range = [t for t in trade_list if -35 <= t['pnl'] < -18]
    over_loss_max = [t for t in trade_list if t['pnl'] < -35]
    print(f"    Micro loss (-1/-2):   {len(micro_losses):4d} ({len(micro_losses)/total*100:5.1f}%) sum={sum(t['pnl'] for t in micro_losses):+.0f}")
    print(f"    Small loss (-3/-5):   {len(small_losses):4d} ({len(small_losses)/total*100:5.1f}%) sum={sum(t['pnl'] for t in small_losses):+.0f}")
    print(f"    Med loss (-6/-10):    {len(med_losses):4d} ({len(med_losses)/total*100:5.1f}%) sum={sum(t['pnl'] for t in med_losses):+.0f}")
    print(f"    Loss exit (-11/-18):  {len(loss_exit_range):4d} ({len(loss_exit_range)/total*100:5.1f}%) sum={sum(t['pnl'] for t in loss_exit_range):+.0f}")
    print(f"    Loss max (-19/-35):   {len(loss_max_range):4d} ({len(loss_max_range)/total*100:5.1f}%) sum={sum(t['pnl'] for t in loss_max_range):+.0f}")
    print(f"    Over loss max (<-35): {len(over_loss_max):4d} ({len(over_loss_max)/total*100:5.1f}%) sum={sum(t['pnl'] for t in over_loss_max):+.0f}")
    
    print(f"\n  BIG WINS: {len(big_wins_list)} sum={sum(t['pnl'] for t in big_wins_list):+.0f}")
    print(f"  BIG LOSSES: {len(big_losses_list)} sum={sum(t['pnl'] for t in big_losses_list):+.0f}")
    print(f"  BREAKEVEN: {len(breakevens)} ({len(breakevens)/total*100:.1f}%)")
    
    print(f"\n  EXIT REASON INFERENCE:")
    be_count = len(breakevens)
    vtrail_cut = len(micro_wins)
    loss_exit_count = len(loss_exit_range) + len(loss_max_range) + len(over_loss_max)
    reversal_count = len([t for t in trade_list if t['pnl'] < -5 and t['hold_s'] < 8])
    slow_loss = len([t for t in trade_list if t['pnl'] < -5 and t['hold_s'] >= 8])
    print(f"    Breakeven_stop (pnl=0):    {be_count:4d} ({be_count/total*100:5.1f}%)")
    print(f"    Vtrail cut (+1/+2):        {vtrail_cut:4d} ({vtrail_cut/total*100:5.1f}%)")
    print(f"    Loss_exit gate:            {loss_exit_count:4d} ({loss_exit_count/total*100:5.1f}%)")
    print(f"    Quick reversal (<8s L>-5): {reversal_count:4d}")
    print(f"    Slow loss (>=8s L>-5):     {slow_loss:4d}")
    
    print(f"\n  HOLD TIME vs PnL:")
    hold_buckets = {'0-2s': [], '3-5s': [], '6-10s': [], '11-30s': [], '31-60s': [], '60+s': []}
    for t in trade_list:
        h = t['hold_s']
        if h <= 2: hold_buckets['0-2s'].append(t)
        elif h <= 5: hold_buckets['3-5s'].append(t)
        elif h <= 10: hold_buckets['6-10s'].append(t)
        elif h <= 30: hold_buckets['11-30s'].append(t)
        elif h <= 60: hold_buckets['31-60s'].append(t)
        else: hold_buckets['60+s'].append(t)
    for bucket, btrades in hold_buckets.items():
        if btrades:
            bp = [t['pnl'] for t in btrades]
            bwr = len([p for p in bp if p > 0])/len(bp)*100
            print(f"    {bucket}: {len(bp):4d} WR={bwr:5.1f}% PnL={sum(bp):+6.0f} avgPnL={sum(bp)/len(bp):+5.1f}")
    
    print(f"\n  TOP 10 WINNERS:")
    sorted_w = sorted(trade_list, key=lambda x: x['pnl'], reverse=True)[:10]
    for i, t in enumerate(sorted_w):
        print(f"    {i+1:2d}. {t['exit_t'].strftime('%H:%M:%S')} {t['side']:4s} pnl={t['pnl']:+.0f} hold={t['hold_s']:.0f}s entry={t['entry']:.0f} exit={t['exit']:.0f}")
    
    print(f"\n  TOP 10 LOSERS:")
    sorted_l = sorted(trade_list, key=lambda x: x['pnl'])[:10]
    for i, t in enumerate(sorted_l):
        print(f"    {i+1:2d}. {t['exit_t'].strftime('%H:%M:%S')} {t['side']:4s} pnl={t['pnl']:+.0f} hold={t['hold_s']:.0f}s entry={t['entry']:.0f} exit={t['exit']:.0f}")
    
    print(f"\n  REENTRY / ECHO QUALITY:")
    same_dir_after_loss = 0
    same_dir_after_loss_win = 0
    same_dir_after_loss_pnl = 0.0
    opp_dir_after_loss = 0
    opp_dir_after_loss_win = 0
    opp_dir_after_loss_pnl = 0.0
    for i in range(1, len(trade_list)):
        prev = trade_list[i-1]
        curr = trade_list[i]
        if prev['pnl'] < 0:
            same_side = (prev['side'] == curr['side'])
            if same_side:
                same_dir_after_loss += 1
                same_dir_after_loss_pnl += curr['pnl']
                if curr['pnl'] > 0: same_dir_after_loss_win += 1
            else:
                opp_dir_after_loss += 1
                opp_dir_after_loss_pnl += curr['pnl']
                if curr['pnl'] > 0: opp_dir_after_loss_win += 1
    
    if same_dir_after_loss:
        print(f"    Same-dir after loss: {same_dir_after_loss} WR={same_dir_after_loss_win/same_dir_after_loss*100:.1f}% avgPnL={same_dir_after_loss_pnl/same_dir_after_loss:+.1f}")
    else:
        print(f"    Same-dir after loss: 0")
    if opp_dir_after_loss:
        print(f"    Opp-dir after loss: {opp_dir_after_loss} WR={opp_dir_after_loss_win/opp_dir_after_loss*100:.1f}% avgPnL={opp_dir_after_loss_pnl/opp_dir_after_loss:+.1f}")
    else:
        print(f"    Opp-dir after loss: 0")
    
    print(f"\n  DRAWDOWN ANALYSIS:")
    print(f"    Max consecutive loss PnL: {max_consecutive_loss_pnl:+.0f} pts")
    print(f"    Max drawdown streak:      {max_drawdown_streak:+.0f} pts")
    
    return {
        'total': total, 'wr': wr, 'pnl': pnl_total,
        'avg_w': avg_w, 'avg_l': avg_l, 'rr': rr,
        'tpm': tpm, 'avg_hold': avg_hold,
        'micro_wins_pct': len(micro_wins)/total*100 if total else 0,
        'micro_wins_count': len(micro_wins),
        'big_losses_count': len(big_losses_list),
        'breakeven_pct': len(breakevens)/total*100 if total else 0,
        'max_loss_streak': max_loss_streak,
        'winner_10_plus_pct': winner_10_plus_pct,
        'winner_20_plus_pct': winner_20_plus_pct,
        'winner_30_plus_pct': winner_30_plus_pct,
        'winner_10_plus_count': len(winner_10_plus),
        'winner_20_plus_count': len(winner_20_plus),
        'winner_30_plus_count': len(winner_30_plus),
        'max_consecutive_loss_pnl': max_consecutive_loss_pnl,
        'max_drawdown_streak': max_drawdown_streak,
    }


b = full_analysis(baseline, f"BASELINE ({BASELINE_CONFIG_LABEL})")
t = full_analysis(test, f"TEST ({TEST_CONFIG_LABEL})")

# ======================================================================
# COMPARISON TABLE
# ======================================================================
print(f"\n\n{'='*70}")
print(f"  COMPARISON TABLE: BASELINE vs TEST")
print(f"{'='*70}")

if b and t:
    metrics = [
        ('WR', 'wr', '%', False),
        ('PnL', 'pnl', 'pts', False),
        ('R:R', 'rr', '', False),
        ('Avg Win', 'avg_w', 'pts', False),
        ('Avg Loss', 'avg_l', 'pts', True),
        ('TPM', 'tpm', '/min', False),
        ('Avg Hold', 'avg_hold', 's', True),
        ('Micro wins %', 'micro_wins_pct', '%', True),
        ('Micro wins #', 'micro_wins_count', '', True),
        ('+10 winners %', 'winner_10_plus_pct', '%', False),
        ('+20 winners %', 'winner_20_plus_pct', '%', False),
        ('+30 winners %', 'winner_30_plus_pct', '%', False),
        ('+10 winners #', 'winner_10_plus_count', '', False),
        ('+20 winners #', 'winner_20_plus_count', '', False),
        ('+30 winners #', 'winner_30_plus_count', '', False),
        ('Big losses #', 'big_losses_count', '', True),
        ('Breakeven %', 'breakeven_pct', '%', True),
        ('Max loss streak', 'max_loss_streak', '', True),
        ('Max consec loss PnL', 'max_consecutive_loss_pnl', 'pts', True),
        ('Max drawdown streak', 'max_drawdown_streak', 'pts', True),
    ]
    
    print(f"  {'Metric':22s} | {'Baseline(8)':>12s} | {'Test(12)':>12s} | {'Delta':>12s} | Verdict")
    print(f"  {'-'*22}-+-{'-'*12}-+-{'-'*12}-+-{'-'*12}-+-{'-'*10}")
    
    for name, key, unit, lower_is_better in metrics:
        bv = b[key]
        tv = t[key]
        delta = tv - bv
        if unit == '%':
            s1 = f"{bv:11.1f}%"
            s2 = f"{tv:11.1f}%"
            s3 = f"{delta:+11.1f}%"
        elif key in ('pnl', 'avg_w', 'avg_l', 'max_consecutive_loss_pnl', 'max_drawdown_streak'):
            s1 = f"{bv:+11.0f} "
            s2 = f"{tv:+11.0f} "
            s3 = f"{delta:+11.0f} "
        elif key in ('winner_10_plus_count', 'winner_20_plus_count', 'winner_30_plus_count'):
            s1 = f"{bv:11d} "
            s2 = f"{tv:11d} "
            s3 = f"{delta:+11d} "
        else:
            s1 = f"{bv:11.1f} "
            s2 = f"{tv:11.1f} "
            s3 = f"{delta:+11.1f} "
        
        if lower_is_better:
            v = "MELHOROU" if delta < 0 else ("PIOROU" if delta > 0 else "IGUAL")
        else:
            v = "MELHOROU" if delta > 0 else ("PIOROU" if delta < 0 else "IGUAL")
        
        print(f"  {name:22s} | {s1} | {s2} | {s3} | {v}")
    
    # ======================================================================
    # CRITERIA CHECK
    # ======================================================================
    print(f"\n{'='*70}")
    print(f"  CRITERIA CHECK")
    print(f"{'='*70}")
    
    criteria = []
    hard_fails = 0
    
    # --- PASS/FAIL criteria ---
    
    # 1. avgWin subir
    if t['avg_w'] > b['avg_w']:
        criteria.append(("1. avgWin subir", "PASS", f"{b['avg_w']:+.1f} -> {t['avg_w']:+.1f}"))
    else:
        criteria.append(("1. avgWin subir", "FAIL", f"{b['avg_w']:+.1f} -> {t['avg_w']:+.1f}"))
    
    # 2. micro wins cair
    if t['micro_wins_pct'] < b['micro_wins_pct']:
        criteria.append(("2. Micro wins cair", "PASS", f"{b['micro_wins_pct']:.1f}% -> {t['micro_wins_pct']:.1f}%"))
    else:
        criteria.append(("2. Micro wins cair", "FAIL", f"{b['micro_wins_pct']:.1f}% -> {t['micro_wins_pct']:.1f}%"))
    
    # 3. R:R melhorar
    if t['rr'] > b['rr']:
        criteria.append(("3. R:R melhorar", "PASS", f"{b['rr']:.2f} -> {t['rr']:.2f}"))
    else:
        criteria.append(("3. R:R melhorar", "FAIL", f"{b['rr']:.2f} -> {t['rr']:.2f}"))
    
    # 4. TPM (HFT critical)
    if t['tpm'] < 2.0:
        criteria.append(("4. TPM HFT critical", "HARD FAIL", f"{t['tpm']:.2f} (< 2.0 = dead HFT)"))
        hard_fails += 1
    elif t['tpm'] < 3.0:
        criteria.append(("4. TPM HFT critical", "FAIL", f"{t['tpm']:.2f} (2.0-3.0 = slow)"))
    elif t['tpm'] >= 5.0:
        criteria.append(("4. TPM HFT critical", "PASS (EXCELLENT)", f"{t['tpm']:.2f}"))
    else:
        criteria.append(("4. TPM HFT critical", "PASS", f"{t['tpm']:.2f}"))
    
    # 5. avgLoss nao piorar >15%
    max_allowed_avg_l = b['avg_l'] * 1.15
    if t['avg_l'] <= max_allowed_avg_l:
        criteria.append(("5. AvgLoss <= 15% piora", "PASS", f"{b['avg_l']:.1f} -> {t['avg_l']:.1f} (max {max_allowed_avg_l:.1f})"))
    else:
        criteria.append(("5. AvgLoss <= 15% piora", "FAIL", f"{b['avg_l']:.1f} -> {t['avg_l']:.1f} (max {max_allowed_avg_l:.1f})"))
    
    # 6. +10 winners subir (winner truncation proof)
    if t['winner_10_plus_pct'] > b['winner_10_plus_pct']:
        criteria.append(("6. +10 winners subir", "PASS", f"{b['winner_10_plus_pct']:.1f}% -> {t['winner_10_plus_pct']:.1f}%"))
    elif t['winner_10_plus_pct'] == b['winner_10_plus_pct']:
        criteria.append(("6. +10 winners subir", "NEUTRAL", f"{b['winner_10_plus_pct']:.1f}% -> {t['winner_10_plus_pct']:.1f}%"))
    else:
        criteria.append(("6. +10 winners subir", "FAIL", f"{b['winner_10_plus_pct']:.1f}% -> {t['winner_10_plus_pct']:.1f}%"))
    
    # --- HARD FAIL criteria ---
    
    # H1. avgLoss >25% piora
    if t['avg_l'] > b['avg_l'] * 1.25:
        criteria.append(("H1. AvgLoss >25% piora", "HARD FAIL", f"{b['avg_l']:.1f} -> {t['avg_l']:.1f} (1.25x={b['avg_l']*1.25:.1f})"))
        hard_fails += 1
    
    # H2. avgHold explodir >2x
    if t['avg_hold'] > b['avg_hold'] * 2.0:
        criteria.append(("H2. Hold time >2x", "HARD FAIL", f"{b['avg_hold']:.1f}s -> {t['avg_hold']:.1f}s (2x={b['avg_hold']*2.0:.1f}s)"))
        hard_fails += 1
    
    # H3. R:R piorar (hard)
    if t['rr'] < b['rr']:
        criteria.append(("H3. R:R piorou", "HARD FAIL", f"{b['rr']:.2f} -> {t['rr']:.2f}"))
        hard_fails += 1
    
    # H4. Drawdown streak > 1.5x baseline
    b_dd = abs(b['max_drawdown_streak']) if b['max_drawdown_streak'] != 0 else 1
    t_dd = abs(t['max_drawdown_streak'])
    if t_dd > b_dd * 1.5:
        criteria.append(("H4. Drawdown >1.5x baseline", "HARD FAIL", f"{b['max_drawdown_streak']:+.0f} -> {t['max_drawdown_streak']:+.0f} (1.5x={b_dd*1.5:.0f})"))
        hard_fails += 1
    
    # H5. TPM < 2.0 (already checked above but redundant explicit)
    # Already in criteria #4
    
    for name, status, detail in criteria:
        if status.startswith("PASS"):
            mark = "OK"
        elif status == "FAIL":
            mark = "XX"
        elif status == "NEUTRAL":
            mark = "--"
        else:
            mark = "!!"
        print(f"  [{mark}] {name:30s} | {detail}")
    
    passes = sum(1 for _, s, _ in criteria if s.startswith("PASS"))
    fails = sum(1 for _, s, _ in criteria if s == "FAIL")
    neutrals = sum(1 for _, s, _ in criteria if s == "NEUTRAL")
    
    print(f"\n  PASS: {passes}/6 | FAIL: {fails}/6 | NEUTRAL: {neutrals} | HARD FAIL: {hard_fails}/4")
    
    # ======================================================================
    # FALSE IMPROVEMENT CHECK
    # ======================================================================
    print(f"\n{'='*70}")
    print(f"  FALSE IMPROVEMENT CHECK")
    print(f"{'='*70}")
    
    false_improvement = False
    false_reasons = []
    
    # If avgHold increased but +10/+20 winners did NOT increase
    hold_increased = t['avg_hold'] > b['avg_hold'] * 1.15
    big_win_decreased = t['winner_10_plus_pct'] <= b['winner_10_plus_pct']
    
    if hold_increased and big_win_decreased:
        false_improvement = True
        false_reasons.append(f"avgHold UP ({b['avg_hold']:.1f}s -> {t['avg_hold']:.1f}s) but +10 winners NOT UP ({b['winner_10_plus_pct']:.1f}% -> {t['winner_10_plus_pct']:.1f}%)")
    
    if avg_w_up := (t['avg_w'] > b['avg_w']):
        micro_down = t['micro_wins_pct'] < b['micro_wins_pct']
        big_win_up = t['winner_10_plus_pct'] > b['winner_10_plus_pct']
        if not big_win_up and not micro_down:
            false_improvement = True
            false_reasons.append(f"avgWin UP but neither micro wins DOWN nor +10 winners UP — gain may be from noise")
    
    if false_improvement:
        print(f"  WARNING: FALSE IMPROVEMENT detected!")
        for r in false_reasons:
            print(f"    - {r}")
        print(f"  Interpretation: offset=12 may be holding positions longer")
        print(f"  without actually capturing more movement. Winners are not")
        print(f"  bigger, just held longer — exposing to more risk.")
    else:
        print(f"  No false improvement signals detected.")
        if hold_increased:
            print(f"  avgHold UP + big winners UP = genuine improvement (trades run further in real moves)")
        if not hold_increased:
            print(f"  avgHold stable — no evidence of artificial holding")
    
    # ======================================================================
    # FINAL CLASSIFICATION
    # ======================================================================
    print(f"\n{'='*70}")
    print(f"  FINAL CLASSIFICATION")
    print(f"{'='*70}")
    print(f"  Hypothesis: {CONFIG_PARAM} offset=8 cuts winners prematurely")
    print(f"  Expected signals: avgWin UP, micro wins DOWN, R:R UP, avgHold UP moderate, +10 winners UP")
    print(f"  Split method: {split_method}")
    print(f"  Baseline sample: {b['total']} trades ({baseline_duration:.0f} min)")
    print(f"  Test sample:     {t['total']} trades ({test_duration:.0f} min)")
    print(f"  Confidence:      {confidence}")
    
    if split_method == "GAP FALLBACK":
        print(f"  [CAUTION] Split based on gap heuristic — lower confidence")
    if session_imbalance:
        print(f"  [CAUTION] Session distribution imbalance — comparison may be biased")
    if confidence != "HIGH CONFIDENCE":
        print(f"  [CAUTION] {confidence} — results should be confirmed with more data")
    
    print()
    
    # Classification logic
    classification = None
    action = None
    next_step = None
    justification = []
    
    if hard_fails > 0:
        classification = "HARD FAIL"
        action = "Voltar para offset=8.0 imediatamente"
        justification.append(f"{hard_fails} hard fail(s) em metricas criticas")
        if t['tpm'] < 2.0:
            justification.append("TPM abaixo de 2.0 — HFT nao operacional")
        if t['avg_l'] > b['avg_l'] * 1.25:
            justification.append(f"avgLoss disparou {b['avg_l']:.1f} -> {t['avg_l']:.1f}")
        if t['rr'] < b['rr']:
            justification.append(f"R:R piorou {b['rr']:.2f} -> {t['rr']:.2f}")
        if t_dd > b_dd * 1.5:
            justification.append(f"Drawdown streak {t['max_drawdown_streak']:+.0f} > 1.5x baseline {b['max_drawdown_streak']:+.0f}")
    elif false_improvement:
        classification = "FALSE IMPROVEMENT"
        action = "Nao manter offset=12.0; voltar para 8.0 ou testar intermediario (10 ou 11)"
        justification.append("avgHold subiu mas big winners nao aumentaram")
        justification.append("Ganho aparente e de exposicao, nao de captura real")
        next_step = "Testar offset=10 ou 11 como intermediario"
    elif fails == 0 and not false_improvement:
        classification = "APPROVED"
        action = "Manter offset=12.0"
        justification.append("Todos criterios passaram")
        justification.append("Sem sinais de false improvement")
        if passes >= 5:
            next_step = "Considerar ETAPA 2 (offset 12->15)"
        else:
            next_step = "Coletar mais dados antes de ETAPA 2"
    elif passes >= 4 and fails <= 1 and not false_improvement:
        classification = "PARTIAL APPROVAL"
        action = "Manter offset=12.0 e coletar mais dados"
        justification.append(f"{passes}/6 pass, {fails}/6 fail — maioria positiva")
        if t['avg_w'] > b['avg_w'] and t['winner_10_plus_pct'] > b['winner_10_plus_pct']:
            justification.append("avgWin e +10 winners subiram — melhora real")
        next_step = "Nao avancar para ETAPA 2 ate confirmar com mais trades"
    elif passes >= fails and not false_improvement:
        classification = "INCONCLUSIVE"
        action = "Manter offset=12.0 mas coletar mais dados antes de concluir"
        justification.append(f"{passes} pass vs {fails} fail — sinal fraco")
        next_step = "Testar intermediario offset=10 ou 11 se dados nao clarificarem"
    else:
        classification = "REJECTED"
        action = "Voltar para offset=8.0 ou testar intermediario (10 ou 11)"
        justification.append(f"{fails}/6 fail sem hard fail — sinais de melhora insuficientes")
        next_step = "Testar offset=10 ou 11 como opcao intermediaria"
    
    print(f"  Classification: {classification}")
    print(f"  Action:         {action}")
    if next_step:
        print(f"  Next step:      {next_step}")
    print(f"\n  Justification:")
    for j in justification:
        print(f"    - {j}")
    
    # Summary metrics
    print(f"\n  SUMMARY METRICS:")
    print(f"    {'Metric':20s} | {'Baseline':>10s} | {'Test':>10s} | {'Delta':>10s}")
    print(f"    {'-'*20}-+-{'-'*10}-+-{'-'*10}-+-{'-'*10}")
    summary = [
        ('WR', b['wr'], t['wr'], '%'),
        ('PnL', b['pnl'], t['pnl'], 'pts'),
        ('R:R', b['rr'], t['rr'], ''),
        ('avgWin', b['avg_w'], t['avg_w'], 'pts'),
        ('avgLoss', b['avg_l'], t['avg_l'], 'pts'),
        ('TPM', b['tpm'], t['tpm'], '/min'),
        ('avgHold', b['avg_hold'], t['avg_hold'], 's'),
        ('micro wins %', b['micro_wins_pct'], t['micro_wins_pct'], '%'),
        ('+10 winners %', b['winner_10_plus_pct'], t['winner_10_plus_pct'], '%'),
        ('+20 winners %', b['winner_20_plus_pct'], t['winner_20_plus_pct'], '%'),
        ('+30 winners %', b['winner_30_plus_pct'], t['winner_30_plus_pct'], '%'),
        ('drawdown streak', b['max_drawdown_streak'], t['max_drawdown_streak'], 'pts'),
        ('breakeven %', b['breakeven_pct'], t['breakeven_pct'], '%'),
    ]
    for name, bv, tv, unit in summary:
        d = tv - bv
        if unit == 'pts' and name in ('PnL', 'drawdown streak'):
            print(f"    {name:20s} | {bv:+9.0f} | {tv:+9.0f} | {d:+9.0f}")
        elif unit == 'pts':
            print(f"    {name:20s} | {bv:+9.1f} | {tv:+9.1f} | {d:+9.1f}")
        elif unit == '%':
            print(f"    {name:20s} | {bv:8.1f}% | {tv:8.1f}% | {d:+8.1f}%")
        elif unit == '/min':
            print(f"    {name:20s} | {bv:9.2f} | {tv:9.2f} | {d:+9.2f}")
        elif unit == 's':
            print(f"    {name:20s} | {bv:9.1f} | {tv:9.1f} | {d:+9.1f}")
        else:
            print(f"    {name:20s} | {bv:9.2f} | {tv:9.2f} | {d:+9.2f}")
    
    # Explicit final recommendation
    print(f"\n  EXPLICIT RECOMMENDATION:")
    if classification == "APPROVED":
        print(f"    >>> Manter offset=12 <<<")
    elif classification == "PARTIAL APPROVAL":
        print(f"    >>> Manter offset=12 (monitorar) <<<")
    elif classification == "INCONCLUSIVE":
        print(f"    >>> Testar intermediario (offset=10 ou 11) <<<")
    elif classification == "FALSE IMPROVEMENT":
        print(f"    >>> Voltar para offset=8 ou testar 10/11 <<<")
    elif classification == "REJECTED":
        print(f"    >>> Voltar para offset=8 <<<")
    elif classification == "HARD FAIL":
        print(f"    >>> Voltar para offset=8 IMEDIATAMENTE <<<")
else:
    print("  Insufficient data for comparison.")

mt5.shutdown()
print("\nDone.")
