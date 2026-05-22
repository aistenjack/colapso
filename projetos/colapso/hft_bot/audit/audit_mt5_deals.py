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
    return s

def get_deals_range(symbol, from_dt, to_dt):
    deals = mt5.history_deals_get(from_dt, to_dt, group=f"*{symbol}*")
    return list(deals) if deals else []

def analyze():
    s = connect_mt5()
    symbol = s.trading.symbol
    magic = s.trading.magic_number
    point = 1.0

    now = datetime.now()
    from_today = now.replace(hour=9, minute=0, second=0, microsecond=0)
    to_today = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    from_yesterday = (now - timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    to_yesterday = (now - timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=999999)

    from_2days = (now - timedelta(days=2)).replace(hour=9, minute=0, second=0, microsecond=0)
    to_2days = (now - timedelta(days=2)).replace(hour=23, minute=59, second=59, microsecond=999999)

    from_5days = (now - timedelta(days=5)).replace(hour=9, minute=0, second=0, microsecond=0)

    deals_today = get_deals_range(symbol, from_today, to_today)
    deals_yesterday = get_deals_range(symbol, from_yesterday, to_yesterday)
    deals_2days = get_deals_range(symbol, from_2days, to_2days)
    deals_5days = get_deals_range(symbol, from_5days, now)

    print(f"=== DEALS MT5 (magic={magic}) ===")
    print(f"Today:     {len(deals_today)}")
    print(f"Yesterday: {len(deals_yesterday)}")
    print(f"2 days:    {len(deals_2days)}")
    print(f"Last 5d:   {len(deals_5days)}")

    all_deals = deals_5days
    our_deals = [d for d in all_deals if d.magic == magic]

    entries = [d for d in our_deals if d.entry == mt5.DEAL_ENTRY_IN]
    exits = [d for d in our_deals if d.entry == mt5.DEAL_ENTRY_OUT]

    print(f"\nOur deals (last 5d): {len(our_deals)}")
    print(f"  Entries: {len(entries)}")
    print(f"  Exits:   {len(exits)}")

    trade_list = []
    for ex in sorted(exits, key=lambda x: x.time):
        matching = [e for e in entries if e.position_id == ex.position_id]
        entry = matching[0] if matching else None
        pnl = ex.profit + ex.commission + ex.swap
        side = 'BUY' if ex.type == mt5.DEAL_TYPE_SELL else 'SELL'
        entry_price = entry.price if entry else 0.0
        exit_price = ex.price
        entry_time = datetime.fromtimestamp(entry.time) if entry else None
        exit_time = datetime.fromtimestamp(ex.time)
        hold_s = (ex.time - entry.time) if entry else 0

        trade_list.append({
            'position': ex.position_id,
            'side': side,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'pnl': ex.profit,
            'pnl_total': pnl,
            'commission': ex.commission,
            'entry_time': entry_time,
            'exit_time': exit_time,
            'hold_s': hold_s,
            'volume': ex.volume,
            'day': exit_time.strftime('%Y-%m-%d'),
        })

    print(f"\n{'='*70}")
    print(f"ESTATISTICAS GERAIS (ultimos 5 dias)")
    print(f"{'='*70}")

    if not trade_list:
        print("Nenhuma trade encontrada.")
        mt5.shutdown()
        return

    pnls = [t['pnl'] for t in trade_list]
    pnls_total = [t['pnl_total'] for t in trade_list]
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
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    rr = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')

    sorted_trades = sorted(trade_list, key=lambda x: x['exit_time'])
    first_t = sorted_trades[0]['exit_time']
    last_t = sorted_trades[-1]['exit_time']
    session_min = (last_t - first_t).total_seconds() / 60.0
    tpm = total / session_min if session_min > 0 else 0.0

    intervals = []
    for i in range(1, len(sorted_trades)):
        gap = (sorted_trades[i]['entry_time'] - sorted_trades[i-1]['exit_time']).total_seconds()
        if gap < 0:
            gap = (sorted_trades[i]['exit_time'] - sorted_trades[i-1]['exit_time']).total_seconds()
        intervals.append(gap)
    avg_interval = sum(intervals) / len(intervals) if intervals else 0.0

    streak_w = 0
    streak_l = 0
    max_sw = 0
    max_sl = 0
    for p in pnls:
        if p > 0:
            streak_w += 1
            streak_l = 0
            max_sw = max(max_sw, streak_w)
        elif p < 0:
            streak_l += 1
            streak_w = 0
            max_sl = max(max_sl, streak_l)
        else:
            streak_w = 0
            streak_l = 0

    print(f"  Total trades:       {total}")
    print(f"  Wins:               {len(wins)}")
    print(f"  Losses:             {len(losses)}")
    print(f"  Breakeven:          {len(zeroes)}")
    print(f"  Win Rate:           {wr:.1f}%")
    print(f"  Profit Factor:      {pf:.2f}")
    print(f"  PnL Total (pts):    {total_pnl:+.0f}")
    print(f"  PnL Medio/trade:    {avg_pnl:+.2f}")
    print(f"  Avg Win:            {avg_win:+.1f}")
    print(f"  Avg Loss:           {avg_loss:+.1f}")
    print(f"  R:R:                {rr:.2f}")
    print(f"  Trades/min:         {tpm:.2f}")
    print(f"  Avg intervalo:      {avg_interval:.1f}s")
    print(f"  Avg hold:           {sum(t['hold_s'] for t in trade_list)/total:.1f}s")
    print(f"  Max win streak:     {max_sw}")
    print(f"  Max loss streak:    {max_sl}")
    print(f"  Sessao:             {first_t} -> {last_t} ({session_min:.0f}min)")

    print(f"\n{'='*70}")
    print(f"POR DIA")
    print(f"{'='*70}")

    by_day = defaultdict(list)
    for t in trade_list:
        by_day[t['day']].append(t)

    for day in sorted(by_day.keys()):
        day_trades = by_day[day]
        day_pnls = [t['pnl'] for t in day_trades]
        day_wins = [p for p in day_pnls if p > 0]
        day_losses = [p for p in day_pnls if p < 0]
        day_wr = len(day_wins) / len(day_pnls) * 100.0 if day_pnls else 0.0
        day_pnl = sum(day_pnls)
        day_avg_win = sum(day_wins)/len(day_wins) if day_wins else 0.0
        day_avg_loss = sum(day_losses)/len(day_losses) if day_losses else 0.0
        day_rr = abs(day_avg_win/day_avg_loss) if day_avg_loss != 0 else float('inf')

        d_first = min(t['entry_time'] for t in day_trades if t['entry_time'])
        d_last = max(t['exit_time'] for t in day_trades)
        d_min = (d_last - d_first).total_seconds() / 60.0
        d_tpm = len(day_trades) / d_min if d_min > 0 else 0.0

        print(f"  {day}: {len(day_trades):3d} trades | WR={day_wr:5.1f}% | PnL={day_pnl:+6.0f} | avgW={day_avg_win:+.0f} avgL={day_avg_loss:+.0f} | RR={day_rr:.2f} | TPM={d_tpm:.2f}")

    print(f"\n{'='*70}")
    print(f"POR HORA DO DIA (todos dias)")
    print(f"{'='*70}")

    by_hour = defaultdict(list)
    for t in trade_list:
        h = t['exit_time'].hour
        by_hour[h].append(t['pnl'])

    for h in sorted(by_hour.keys()):
        hp = by_hour[h]
        hw = [p for p in hp if p > 0]
        hl = [p for p in hp if p < 0]
        hwr = len(hw)/len(hp)*100.0 if hp else 0.0
        print(f"  {h:02d}:00  {len(hp):4d} trades | WR={hwr:5.1f}% | PnL={sum(hp):+6.0f}")

    print(f"\n{'='*70}")
    print(f"DISTRIBUICAO DE PnL POR TRADE")
    print(f"{'='*70}")

    pnl_ranges = defaultdict(int)
    for p in pnls:
        if p >= 20:
            pnl_ranges['+20+'] += 1
        elif p >= 10:
            pnl_ranges['+10 a +20'] += 1
        elif p >= 5:
            pnl_ranges['+5 a +10'] += 1
        elif p >= 1:
            pnl_ranges['+1 a +5'] += 1
        elif p > 0:
            pnl_ranges['0 a +1'] += 1
        elif p == 0:
            pnl_ranges['=0'] += 1
        elif p > -1:
            pnl_ranges['-1 a 0'] += 1
        elif p > -5:
            pnl_ranges['-5 a -1'] += 1
        elif p > -10:
            pnl_ranges['-10 a -5'] += 1
        elif p > -20:
            pnl_ranges['-20 a -10'] += 1
        else:
            pnl_ranges['-20+'] += 1

    for key in ['+20+', '+10 a +20', '+5 a +10', '+1 a +5', '0 a +1', '=0', '-1 a 0', '-5 a -1', '-10 a -5', '-20 a -10', '-20+']:
        if pnl_ranges[key] > 0:
            print(f"  {key:15s}: {pnl_ranges[key]:4d}")

    print(f"\n{'='*70}")
    print(f"LOSS TRADES DETALHADOS (top 20 piores)")
    print(f"{'='*70}")

    loss_trades = [(t['pnl'], t) for t in trade_list if t['pnl'] < 0]
    loss_trades.sort(key=lambda x: x[0])
    for pnl, t in loss_trades[:20]:
        print(f"  {t['exit_time']} | {t['side']:4s} | entry={t['entry_price']:.0f} exit={t['exit_price']:.0f} | PnL={pnl:+.0f} | hold={t['hold_s']:.0f}s")

    print(f"\n{'='*70}")
    print(f"WIN TRADES DETALHADOS (top 20 melhores)")
    print(f"{'='*70}")

    win_trades = [(t['pnl'], t) for t in trade_list if t['pnl'] > 0]
    win_trades.sort(key=lambda x: -x[0])
    for pnl, t in win_trades[:20]:
        print(f"  {t['exit_time']} | {t['side']:4s} | entry={t['entry_price']:.0f} exit={t['exit_price']:.0f} | PnL={pnl:+.0f} | hold={t['hold_s']:.0f}s")

    print(f"\n{'='*70}")
    print(f"GARGALOS IDENTIFICADOS")
    print(f"{'='*70}")

    print(f"\n  1. FREQUENCIA:")
    print(f"     TPM real = {tpm:.2f} (target >= 3.0)")
    if tpm < 1.0:
        print(f"     *** CRITICO: TPM {tpm:.2f} muito abaixo do target 3.0")
    elif tpm < 3.0:
        print(f"     *** ABAIXO: TPM {tpm:.2f} abaixo do target 3.0")

    print(f"\n  2. ACERTIVIDADE:")
    print(f"     WR = {wr:.1f}% (target >= 60%)")
    if wr < 50:
        print(f"     *** CRITICO: WR {wr:.1f}% muito abaixo do target 60%")
    elif wr < 60:
        print(f"     *** ABAIXO: WR {wr:.1f}% abaixo do target 60%")

    print(f"\n  3. R:R RATIO:")
    print(f"     R:R = {rr:.2f}")
    if rr < 0.5:
        print(f"     *** CRITICO: R:R muito baixo - avg loss muito maior que avg win")
    elif rr < 1.0:
        print(f"     *** ABAIXO: R:R < 1.0 - losses maiores que wins")

    big_losses = [p for p in pnls if p <= -10]
    big_wins = [p for p in pnls if p >= 10]
    print(f"\n  4. OUTLIERS:")
    print(f"     Big wins (>=+10):  {len(big_wins)} trades, sum={sum(big_wins):+.0f}")
    print(f"     Big losses (<=-10):{len(big_losses)} trades, sum={sum(big_losses):+.0f}")
    if len(big_losses) > 0 and abs(sum(big_losses)) > sum(big_wins):
        print(f"     *** Big losses superam big wins - stop loss pode estar largo demais")

    hold_times = [t['hold_s'] for t in trade_list]
    avg_hold = sum(hold_times)/len(hold_times)
    print(f"\n  5. HOLD TIME:")
    print(f"     Avg hold: {avg_hold:.1f}s")
    very_long = [t for t in trade_list if t['hold_s'] > 120]
    if very_long:
        vl_pnl = sum(t['pnl'] for t in very_long)
        print(f"     Trades >120s: {len(very_long)} (avg PnL={vl_pnl/len(very_long):+.1f})")
        if vl_pnl < 0:
            print(f"     *** Trades longos tendem a perder - timeout pode estar alto")

    by_side = defaultdict(list)
    for t in trade_list:
        by_side[t['side']].append(t['pnl'])

    print(f"\n  6. POR SIDE:")
    for side in ['BUY', 'SELL']:
        sp = by_side.get(side, [])
        if sp:
            sw = [p for p in sp if p > 0]
            sl = [p for p in sp if p < 0]
            swr = len(sw)/len(sp)*100.0
            print(f"     {side}: {len(sp)} trades WR={swr:.1f}% PnL={sum(sp):+.0f}")

    mt5.shutdown()
    print("\nMT5 desconectado.")

if __name__ == "__main__":
    analyze()
