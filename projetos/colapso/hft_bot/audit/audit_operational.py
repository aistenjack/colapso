import sys
import os
import re
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

from config.settings import Settings

def connect_mt5():
    s = Settings()
    path = s.mt5.path or s.mt5.terminal_path
    if not mt5.initialize(path=path):
        print(f"MT5 initialize falhou: {mt5.last_error()}")
        sys.exit(1)
    if s.mt5.login:
        if not mt5.login(login=s.mt5.login, password=s.mt5.password, server=s.mt5.server):
            print(f"MT5 login falhou: {mt5.last_error()}")
            mt5.shutdown()
            sys.exit(1)
    account = mt5.account_info()
    print(f"Conectado: conta {account.login} saldo={account.balance:.2f}")
    return s

def get_deals_today(symbol):
    now = datetime.now()
    from_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    to_dt = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    deals = mt5.history_deals_get(from_dt, to_dt, group=f"*{symbol}*")
    if deals is None:
        print("Nenhum deal encontrado hoje")
        return []
    return list(deals)

def get_deals_yesterday(symbol):
    yesterday = datetime.now() - timedelta(days=1)
    from_dt = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
    to_dt = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
    deals = mt5.history_deals_get(from_dt, to_dt, group=f"*{symbol}*")
    if deals is None:
        print("Nenhum deal encontrado ontem")
        return []
    return list(deals)

def analyze_deals(deals, magic_number=123456):
    our_deals = [d for d in deals if d.magic == magic_number]
    print(f"\nTotal deals MT5 (todos): {len(deals)}")
    print(f"Total deals MT5 (nosso magic={magic_number}): {len(our_deals)}")

    entries = []
    exits = []
    for d in our_deals:
        if d.entry == mt5.DEAL_ENTRY_IN:
            entries.append(d)
        elif d.entry == mt5.DEAL_ENTRY_OUT:
            exits.append(d)
        elif d.entry == mt5.DEAL_ENTRY_INOUT:
            entries.append(d)
            exits.append(d)

    print(f"  Entries (DEAL_ENTRY_IN): {len(entries)}")
    print(f"  Exits (DEAL_ENTRY_OUT): {len(exits)}")

    trades = []
    for ex in exits:
        matching_entries = [e for e in entries if e.order == ex.order or abs(e.time - ex.time) < 300]
        entry = matching_entries[0] if matching_entries else None
        trades.append({
            'ticket': ex.order,
            'entry_time': datetime.fromtimestamp(entry.time) if entry else None,
            'exit_time': datetime.fromtimestamp(ex.time),
            'side': 'BUY' if ex.type == mt5.DEAL_TYPE_BUY else 'SELL',
            'entry_price': entry.price if entry else 0.0,
            'exit_price': ex.price,
            'volume': ex.volume,
            'pnl': ex.profit,
            'commission': ex.commission,
            'swap': ex.swap,
            'slippage': 0.0,
        })

    return trades

def parse_trades_log(log_path):
    trades = []
    pnl_pattern = re.compile(r'PnL realizado atualizado: (-?[\d.]+) \(trade\)')
    ticket_pattern = re.compile(r'Posi..o fechada \| Ticket: (\d+)')
    exec_pattern = re.compile(r'\[EXEC\] ORDEM EXECUTADA \| Ticket: (\d+) \| Pre..o: ([\d.]+) \| Lat.ncia: ([\d.]+)ms \| Slip: (-?[\d.]+) ticks')
    side_pattern = re.compile(r'\[EXEC\] Executando (BUY|SELL)')

    current = {}
    with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            date_match = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
            ts = date_match.group(1) if date_match else None

            m_exec = exec_pattern.search(line)
            if m_exec:
                current = {
                    'ticket': int(m_exec.group(1)),
                    'entry_price': float(m_exec.group(2)),
                    'latency_ms': float(m_exec.group(3)),
                    'slippage': float(m_exec.group(4)),
                    'timestamp': ts,
                }
                continue

            m_side = side_pattern.search(line)
            if m_side and ts:
                current['side'] = m_side.group(1)
                current['entry_ts'] = ts
                continue

            m_pnl = pnl_pattern.search(line)
            if m_pnl and ts:
                current['pnl'] = float(m_pnl.group(1))
                current['close_ts'] = ts
                if 'ticket' in current and 'pnl' in current:
                    trades.append(current.copy())
                current = {}
                continue

    return trades

def parse_system_log(log_path):
    signals = []
    blocks = []
    reentry_scores = []
    adaptive_thresholds = []
    speed_filters = []
    hft_metrics = []

    with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            date_match = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
            ts = date_match.group(1) if date_match else None

            if '[SIGNAL ENTRY]' in line:
                m = re.search(r'type=(\w+) reason=(\S+) velocity=([\d.-]+) vel_fast=([\d.-]+) displacement=([\d.-]+) acc=([\d.-]+)', line)
                if m:
                    signals.append({
                        'ts': ts, 'type': m.group(1), 'reason': m.group(2),
                        'velocity': float(m.group(3)), 'vel_fast': float(m.group(4)),
                        'displacement': float(m.group(5)), 'acceleration': float(m.group(6)),
                    })

            elif '[SIGNAL BLOCKED]' in line:
                m = re.search(r'reason=(\S+)', line)
                if m:
                    blocks.append({'ts': ts, 'reason': m.group(1)})

            elif '[REVERSAL BLOCKED]' in line:
                m = re.search(r'reason=(\S+)', line)
                if m:
                    blocks.append({'ts': ts, 'reason': f'reversal_{m.group(1)}'})

            elif '[REENTRY SCORE]' in line:
                m = re.search(
                    r'retrace=([\d.]+) breakout=([\d.]+) structure=([\d.]+) '
                    r'consistency=([\d.]+) velocity=([\d.]+) chop_pen=([\d.]+) spread_pen=([\d.]+) '
                    r'final=([\d.]+) threshold=([\d.]+) echo=(\S+) mode=(\S+) decision=(\S+) '
                    r'price_dist=([\d.]+) close_pnl=([-\d.]+)',
                    line
                )
                if m:
                    reentry_scores.append({
                        'ts': ts,
                        'retrace': float(m.group(1)), 'breakout': float(m.group(2)),
                        'structure': float(m.group(3)), 'consistency': float(m.group(4)),
                        'velocity': float(m.group(5)), 'chop_pen': float(m.group(6)),
                        'spread_pen': float(m.group(7)), 'final': float(m.group(8)),
                        'threshold': float(m.group(9)), 'echo': m.group(10),
                        'mode': m.group(11), 'decision': m.group(12),
                        'price_dist': float(m.group(13)), 'close_pnl': float(m.group(14)),
                    })

            elif '[ADAPTIVE THRESHOLD]' in line:
                m = re.search(
                    r'freq=([\d.]+) target_freq=([\d.]+) recent_wr=([\d.]+)% '
                    r'recent_pnl=([-\d.]+) base=([\d.]+) adjusted=([\d.]+) reason=(\S+)',
                    line
                )
                if m:
                    adaptive_thresholds.append({
                        'ts': ts,
                        'freq': float(m.group(1)), 'target_freq': float(m.group(2)),
                        'recent_wr': float(m.group(3)), 'recent_pnl': float(m.group(4)),
                        'base': float(m.group(5)), 'adjusted': float(m.group(6)),
                        'reason': m.group(7),
                    })

            elif '[SPEED FILTER]' in line:
                m = re.search(r'estado=(\w+)', line)
                if m:
                    speed_filters.append({'ts': ts, 'state': m.group(1)})

            elif '[HFT METRICS]' in line:
                m = re.search(
                    r'trades_last_minute=(\d+).*avg_latency_ms=([\d.]+).*winrate_session=(\d+)%.*'
                    r'avg_hold_seconds=([\d.]+).*total_wins=(\d+).*total_losses=(\d+)',
                    line
                )
                if m:
                    hft_metrics.append({
                        'ts': ts,
                        'trades_last_minute': int(m.group(1)),
                        'avg_latency_ms': float(m.group(2)),
                        'winrate_session': int(m.group(3)),
                        'avg_hold_seconds': float(m.group(4)),
                        'total_wins': int(m.group(5)),
                        'total_losses': int(m.group(6)),
                    })

    return signals, blocks, reentry_scores, adaptive_thresholds, speed_filters, hft_metrics

def print_general_stats(trades):
    if not trades:
        print("\n=== ESTATÍSTICAS GERAIS ===\nNenhuma trade encontrada.")
        return

    pnls = [t.get('pnl', 0.0) for t in trades if 'pnl' in t]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    zeroes = [p for p in pnls if p == 0]

    total = len(pnls)
    wr = len(wins) / total * 100.0 if total > 0 else 0.0
    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
    pf = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    total_pnl = sum(pnls)
    avg_pnl = total_pnl / total if total > 0 else 0.0

    times = []
    for t in trades:
        if 'entry_ts' in t and 'close_ts' in t:
            try:
                et = datetime.strptime(t['entry_ts'], '%Y-%m-%d %H:%M:%S')
                ct = datetime.strptime(t['close_ts'], '%Y-%m-%d %H:%M:%S')
                times.append((et, ct))
            except:
                pass

    if times:
        first_time = min(t[0] for t in times)
        last_time = max(t[1] for t in times)
        session_duration_min = (last_time - first_time).total_seconds() / 60.0
        trades_per_min = total / session_duration_min if session_duration_min > 0 else 0.0

        intervals = []
        sorted_times = sorted(times, key=lambda x: x[0])
        for i in range(1, len(sorted_times)):
            gap = (sorted_times[i][0] - sorted_times[i-1][0]).total_seconds()
            intervals.append(gap)
        avg_interval = sum(intervals) / len(intervals) if intervals else 0.0
    else:
        session_duration_min = 0
        trades_per_min = 0.0
        avg_interval = 0.0
        first_time = last_time = None

    streak_wins = 0
    streak_losses = 0
    max_streak_wins = 0
    max_streak_losses = 0
    for p in pnls:
        if p > 0:
            streak_wins += 1
            streak_losses = 0
            max_streak_wins = max(max_streak_wins, streak_wins)
        elif p < 0:
            streak_losses += 1
            streak_wins = 0
            max_streak_losses = max(max_streak_losses, streak_losses)
        else:
            streak_wins = 0
            streak_losses = 0

    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    rr_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')

    print("\n" + "="*70)
    print("ESTATÍSTICAS GERAIS")
    print("="*70)
    print(f"  Total de operações:    {total}")
    print(f"  Wins:                  {len(wins)}")
    print(f"  Losses:                {len(losses)}")
    print(f"  Zero (breakeven):      {len(zeroes)}")
    print(f"  Win Rate:              {wr:.1f}%")
    print(f"  Profit Factor:         {pf:.2f}")
    print(f"  PnL Total:             {total_pnl:+.0f} pts")
    print(f"  PnL Médio/trade:       {avg_pnl:+.2f} pts")
    print(f"  Avg Win:               {avg_win:+.1f} pts")
    print(f"  Avg Loss:              {avg_loss:+.1f} pts")
    print(f"  R:R ratio:             {rr_ratio:.2f}")
    print(f"  Trades/min:            {trades_per_min:.2f}")
    print(f"  Avg tempo entre trades:{avg_interval:.1f}s")
    print(f"  Sessão:                {first_time} → {last_time} ({session_duration_min:.0f} min)")
    print(f"  Max win streak:        {max_streak_wins}")
    print(f"  Max loss streak:       {max_streak_losses}")

    return {'total': total, 'wr': wr, 'pf': pf, 'pnl': total_pnl, 'tpm': trades_per_min}

def print_block_analysis(blocks):
    if not blocks:
        print("\n  Nenhum bloqueio registrado.")
        return

    reasons = defaultdict(int)
    for b in blocks:
        reasons[b['reason']] += 1

    print("\n" + "="*70)
    print("ANÁLISE DE BLOQUEIOS")
    print("="*70)
    total_blocks = len(blocks)
    print(f"  Total bloqueios: {total_blocks}")
    for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
        pct = count / total_blocks * 100.0
        print(f"    {reason:40s}: {count:5d} ({pct:5.1f}%)")

def print_speed_filter_analysis(speed_filters):
    if not speed_filters:
        print("\n  Nenhum dado SpeedFilter.")
        return

    states = defaultdict(int)
    for sf in speed_filters:
        states[sf['state']] += 1

    total = len(speed_filters)
    blocked = states.get('LENTO', 0) + states.get('EXAUSTAO', 0)

    print("\n" + "="*70)
    print("ANÁLISE SPEEDFILTER")
    print("="*70)
    print(f"  Total evaluations: {total}")
    print(f"  Blocked (LENTO+EXAUSTAO): {blocked} ({blocked/total*100:.1f}%)")
    print(f"  Allowed (FORTE+ACELERANDO+NEUTRO): {total-blocked} ({(total-blocked)/total*100:.1f}%)")
    for state, count in sorted(states.items(), key=lambda x: -x[1]):
        pct = count / total * 100.0
        print(f"    {state:15s}: {count:6d} ({pct:5.1f}%)")

def print_reentry_analysis(reentry_scores):
    if not reentry_scores:
        print("\n  Nenhum dado REENTRY SCORE.")
        return

    allowed = [r for r in reentry_scores if r['decision'] == 'ALLOW']
    blocked = [r for r in reentry_scores if r['decision'] == 'BLOCK']
    echo = [r for r in reentry_scores if r['echo'] == 'YES']

    print("\n" + "="*70)
    print("ANÁLISE REENTRY ENGINE")
    print("="*70)
    print(f"  Total evaluations: {len(reentry_scores)}")
    print(f"  Allowed:           {len(allowed)}")
    print(f"  Blocked:           {len(blocked)}")
    print(f"  Echo-blocked:      {len(echo)}")

    modes = defaultdict(int)
    for r in reentry_scores:
        modes[r['mode']] += 1
    print(f"\n  Por mode:")
    for mode, count in sorted(modes.items(), key=lambda x: -x[1]):
        print(f"    {mode:20s}: {count}")

    if allowed:
        print(f"\n  Score stats (ALLOWED):")
        finals = [r['final'] for r in allowed]
        print(f"    final_score: min={min(finals):.3f} avg={sum(finals)/len(finals):.3f} max={max(finals):.3f}")

    if blocked:
        print(f"\n  Score stats (BLOCKED):")
        finals = [r['final'] for r in blocked]
        print(f"    final_score: min={min(finals):.3f} avg={sum(finals)/len(finals):.3f} max={max(finals):.3f}")
        thresholds = [r['threshold'] for r in blocked]
        print(f"    threshold:   min={min(thresholds):.3f} avg={sum(thresholds)/len(thresholds):.3f} max={max(thresholds):.3f}")

    threshold_ranges = defaultdict(lambda: {'allow': 0, 'block': 0})
    for r in reentry_scores:
        t = r['threshold']
        if t < 0.40:
            key = '0.30-0.40'
        elif t < 0.50:
            key = '0.40-0.50'
        elif t < 0.60:
            key = '0.50-0.60'
        elif t < 0.70:
            key = '0.60-0.70'
        else:
            key = '0.70+'
        if r['decision'] == 'ALLOW':
            threshold_ranges[key]['allow'] += 1
        else:
            threshold_ranges[key]['block'] += 1

    print(f"\n  Threshold ranges:")
    for key in ['0.30-0.40', '0.40-0.50', '0.50-0.60', '0.60-0.70', '0.70+']:
        a = threshold_ranges[key]['allow']
        b = threshold_ranges[key]['block']
        total_t = a + b
        if total_t > 0:
            print(f"    {key}: allow={a} block={b} ({a/total_t*100:.0f}% allow rate)")

    score_components = ['retrace', 'breakout', 'structure', 'consistency', 'velocity', 'chop_pen', 'spread_pen', 'final']
    print(f"\n  Avg score components (all):")
    for comp in score_components:
        vals = [r[comp] for r in reentry_scores]
        print(f"    {comp:15s}: avg={sum(vals)/len(vals):.3f} min={min(vals):.3f} max={max(vals):.3f}")

def print_adaptive_threshold_analysis(adaptive_thresholds):
    if not adaptive_thresholds:
        print("\n  Nenhum dado ADAPTIVE THRESHOLD.")
        return

    print("\n" + "="*70)
    print("ANÁLISE ADAPTIVE THRESHOLD")
    print("="*70)
    print(f"  Total adjustments: {len(adaptive_thresholds)}")

    reasons = defaultdict(int)
    for at in adaptive_thresholds:
        reasons[at['reason']] += 1

    print(f"\n  Razões de ajuste:")
    for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"    {reason:40s}: {count}")

    freqs = [at['freq'] for at in adaptive_thresholds]
    wrs = [at['recent_wr'] for at in adaptive_thresholds]
    pnls = [at['recent_pnl'] for at in adaptive_thresholds]
    bases = [at['base'] for at in adaptive_thresholds]
    adjusted = [at['adjusted'] for at in adaptive_thresholds]

    print(f"\n  Freq:     min={min(freqs):.1f} avg={sum(freqs)/len(freqs):.1f} max={max(freqs):.1f}")
    print(f"  WR:       min={min(wrs):.0f}% avg={sum(wrs)/len(wrs):.0f}% max={max(wrs):.0f}%")
    print(f"  PnL:      min={min(pnls):.0f} avg={sum(pnls)/len(pnls):.0f} max={max(pnls):.0f}")
    print(f"  Base:     min={min(bases):.3f} max={max(bases):.3f}")
    print(f"  Adjusted: min={min(adjusted):.3f} avg={sum(adjusted)/len(adjusted):.3f} max={max(adjusted):.3f}")

    tightened = sum(1 for a in adaptive_thresholds if a['adjusted'] > a['base'])
    relaxed = sum(1 for a in adaptive_thresholds if a['adjusted'] < a['base'])
    neutral = sum(1 for a in adaptive_thresholds if a['adjusted'] == a['base'])
    print(f"\n  Tightened: {tightened} | Relaxed: {relaxed} | Neutral: {neutral}")

def print_signal_analysis(signals):
    if not signals:
        print("\n  Nenhum signal registrado.")
        return

    print("\n" + "="*70)
    print("ANÁLISE DE SINAIS")
    print("="*70)
    print(f"  Total signals: {len(signals)}")

    reasons = defaultdict(int)
    for s in signals:
        reasons[s['reason']] += 1

    print(f"\n  Por reason:")
    for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"    {reason:35s}: {count}")

    vel_fast = [s['vel_fast'] for s in signals]
    disp = [s['displacement'] for s in signals]
    acc = [s['acceleration'] for s in signals]

    print(f"\n  vel_fast:    min={min(vel_fast):.1f} avg={sum(vel_fast)/len(vel_fast):.1f} max={max(vel_fast):.1f}")
    print(f"  displacement:min={min(disp):.1f} avg={sum(disp)/len(disp):.1f} max={max(disp):.1f}")
    print(f"  acceleration:min={min(acc):.1f} avg={sum(acc)/len(acc):.1f} max={max(acc):.1f}")

def print_hft_metrics_analysis(hft_metrics):
    if not hft_metrics:
        print("\n  Nenhum HFT METRICS.")
        return

    last = hft_metrics[-1]
    print("\n" + "="*70)
    print("ÚLTIMO HFT METRICS")
    print("="*70)
    print(f"  trades_last_minute: {last['trades_last_minute']}")
    print(f"  avg_latency_ms:     {last['avg_latency_ms']:.1f}")
    print(f"  winrate_session:    {last['winrate_session']}%")
    print(f"  avg_hold_seconds:   {last['avg_hold_seconds']:.1f}")
    print(f"  total_wins:         {last['total_wins']}")
    print(f"  total_losses:       {last['total_losses']}")

    wrs = [m['winrate_session'] for m in hft_metrics]
    tpms = [m['trades_last_minute'] for m in hft_metrics]
    print(f"\n  WR ao longo da sessão: min={min(wrs)}% avg={sum(wrs)/len(wrs):.0f}% max={max(wrs)}%")
    print(f"  TPM ao longo da sessão: min={min(tpms)} avg={sum(tpms)/len(tpms):.1f} max={max(tpms)}")

def print_bottleneck_analysis(trades, blocks, speed_filters, reentry_scores, adaptive_thresholds, signals):
    print("\n" + "="*70)
    print("IDENTIFICAÇÃO DE GARGALOS")
    print("="*70)

    pnls = [t.get('pnl', 0.0) for t in trades if 'pnl' in t]

    if pnls:
        losses = [(i, p) for i, p in enumerate(pnls) if p < 0]
        print(f"\n1. Onde o bot está perdendo dinheiro:")
        print(f"   Total losses: {len(losses)} trades, sum={sum(p for _, p in losses):.0f} pts")
        avg_loss = sum(p for _, p in losses) / len(losses) if losses else 0.0
        print(f"   Avg loss: {avg_loss:.1f} pts")

        big_losses = [(i, p) for i, p in losses if p <= -10]
        if big_losses:
            print(f"   Big losses (<=-10pts): {len(big_losses)} trades, sum={sum(p for _, p in big_losses):.0f} pts")
            print(f"   *** Big losses são {len(big_losses)/len(losses)*100:.0f}% dos losses mas representam {abs(sum(p for _, p in big_losses))/abs(sum(p for _, p in losses))*100:.0f}% do PnL negativo")

    if blocks:
        print(f"\n2. Onde está bloqueando trade demais:")
        reasons = defaultdict(int)
        for b in blocks:
            reasons[b['reason']] += 1
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1])[:5]:
            print(f"   {reason}: {count} bloqueios")

    if speed_filters:
        lento_count = sum(1 for sf in speed_filters if sf['state'] == 'LENTO')
        exaustao_count = sum(1 for sf in speed_filters if sf['state'] == 'EXAUSTAO')
        total_sf = len(speed_filters)
        blocked_sf = lento_count + exaustao_count
        print(f"\n3. SpeedFilter impacto na frequência:")
        print(f"   LENTO: {lento_count} ({lento_count/total_sf*100:.1f}%)")
        print(f"   EXAUSTAO: {exaustao_count} ({exaustao_count/total_sf*100:.1f}%)")
        print(f"   Total blocked: {blocked_sf} ({blocked_sf/total_sf*100:.1f}%)")
        if blocked_sf > total_sf * 0.5:
            print(f"   *** ALERTA: SpeedFilter bloqueia >50% dos ticks → reduzindo frequência drasticamente")
        elif blocked_sf > total_sf * 0.3:
            print(f"   *** ATENÇÃO: SpeedFilter bloqueia >30% dos ticks")

    if reentry_scores:
        blocked_re = [r for r in reentry_scores if r['decision'] == 'BLOCK']
        echo_re = [r for r in reentry_scores if r['echo'] == 'YES']
        print(f"\n4. Reentry Engine impacto:")
        print(f"   Total evals: {len(reentry_scores)}")
        print(f"   Blocked: {len(blocked_re)} ({len(blocked_re)/len(reentry_scores)*100:.1f}%)")
        print(f"   Echo-blocked: {len(echo_re)} ({len(echo_re)/len(reentry_scores)*100:.1f}% of evals)")

        if len(blocked_re) > 0:
            low_score_blocks = [r for r in blocked_re if r['final'] < 0.2]
            mid_score_blocks = [r for r in blocked_re if 0.2 <= r['final'] < r['threshold']]
            print(f"   Blocked com score<0.2 (realmente ruim): {len(low_score_blocks)}")
            print(f"   Blocked com score 0.2-0.55 (marginal): {len(mid_score_blocks)}")
            if len(mid_score_blocks) > len(low_score_blocks):
                print(f"   *** Marginais bloqueados > realmentes ruins → threshold pode estar tight demais")

    if adaptive_thresholds:
        tight = [a for a in adaptive_thresholds if a['adjusted'] > a['base']]
        loose = [a for a in adaptive_thresholds if a['adjusted'] < a['base']]
        print(f"\n5. Adaptive threshold comportamento:")
        print(f"   Tightened: {len(tight)} | Relaxed: {len(loose)}")
        avg_adj = sum(a['adjusted'] for a in adaptive_thresholds) / len(adaptive_thresholds)
        avg_base = sum(a['base'] for a in adaptive_thresholds) / len(adaptive_thresholds)
        print(f"   Base médio: {avg_base:.3f} → Ajustado médio: {avg_adj:.3f}")
        if avg_adj > avg_base + 0.03:
            print(f"   *** Threshold consistentemente tight → pode estar cortando trades bons")
        elif avg_adj < avg_base - 0.03:
            print(f"   *** Threshold consistentemente loose → pode estar permitindo falso positivo")

def main():
    s = connect_mt5()
    symbol = s.trading.symbol
    magic = s.trading.magic_number

    print(f"\nSymbol: {symbol} | Magic: {magic}")

    deals_today = get_deals_today(symbol)
    deals_yesterday = get_deals_yesterday(symbol)

    print(f"\nDeals hoje: {len(deals_today)}")
    print(f"Deals ontem: {len(deals_yesterday)}")

    all_deals = deals_today + deals_yesterday

    trades_mt5 = analyze_deals(all_deals, magic)

    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")

    trades_log_files = ['trades.log', 'trades.log.1']
    system_log_files = ['system.log', 'system.log.1', 'system.log.2', 'system.log.3', 'system.log.4', 'system.log.5']

    all_trades_log = []
    for lf in trades_log_files:
        path = os.path.join(log_dir, lf)
        if os.path.exists(path):
            all_trades_log.extend(parse_trades_log(path))

    all_signals = []
    all_blocks = []
    all_reentry = []
    all_adaptive = []
    all_speed = []
    all_hft_metrics = []
    for lf in system_log_files:
        path = os.path.join(log_dir, lf)
        if os.path.exists(path):
            sigs, blocks, reentry, adaptive, speed, hft_m = parse_system_log(path)
            all_signals.extend(sigs)
            all_blocks.extend(blocks)
            all_reentry.extend(reentry)
            all_adaptive.extend(adaptive)
            all_speed.extend(speed)
            all_hft_metrics.extend(hft_m)

    print("\n" + "#"*70)
    print("# DADOS COLETADOS DOS LOGS")
    print("#"*70)
    print(f"  Trades (log):       {len(all_trades_log)}")
    print(f"  Signals (log):      {len(all_signals)}")
    print(f"  Blocks (log):       {len(all_blocks)}")
    print(f"  Reentry scores:     {len(all_reentry)}")
    print(f"  Adaptive thresholds:{len(all_adaptive)}")
    print(f"  SpeedFilter evals:  {len(all_speed)}")
    print(f"  HFT Metrics:        {len(all_hft_metrics)}")

    stats = print_general_stats(all_trades_log)
    print_signal_analysis(all_signals)
    print_block_analysis(all_blocks)
    print_speed_filter_analysis(all_speed)
    print_reentry_analysis(all_reentry)
    print_adaptive_threshold_analysis(all_adaptive)
    print_hft_metrics_analysis(all_hft_metrics)
    print_bottleneck_analysis(all_trades_log, all_blocks, all_speed, all_reentry, all_adaptive, all_signals)

    mt5.shutdown()
    print("\nMT5 desconectado.")

if __name__ == "__main__":
    main()
