import time
import sys

sys.path.insert(0, ".")

from core.micro_structure import MicroStructureEngine, MicroCandle, ReentryResult
from core.utils import TickData, TickMetrics, OrderSide


def make_tick(bid: float, ask: float, time_ms: int = 0) -> TickData:
    if time_ms == 0:
        time_ms = int(time.time() * 1000)
    return TickData(bid=bid, ask=ask, mid=(bid + ask) / 2.0, spread=ask - bid, time_ms=time_ms)


def make_metrics(vel_fast: float = 0.0, disp: float = 0.0, acc: float = 0.0, vel: float = 0.0) -> TickMetrics:
    m = TickMetrics()
    m.velocity_fast = vel_fast
    m.net_displacement = disp
    m.acceleration = acc
    m.velocity = vel
    m.is_valid = True
    return m


def feed_bullish_candles(eng: MicroStructureEngine, n: int = 3, base: float = 181000.0, point: float = 1.0, ticks_per: int = 15) -> None:
    for candle_i in range(n):
        start = base + candle_i * 5
        for ti in range(ticks_per):
            price = start + ti * 0.5
            tick = make_tick(price, price + 2, time_ms=int(time.time() * 1000) + candle_i * 1000 + ti * 10)
            eng.on_tick(tick)


def feed_bearish_candles(eng: MicroStructureEngine, n: int = 3, base: float = 181000.0, point: float = 1.0, ticks_per: int = 15) -> None:
    for candle_i in range(n):
        start = base - candle_i * 5
        for ti in range(ticks_per):
            price = start - ti * 0.5
            tick = make_tick(price, price + 2, time_ms=int(time.time() * 1000) + candle_i * 1000 + ti * 10)
            eng.on_tick(tick)


def feed_chop_candles(eng: MicroStructureEngine, n: int = 3, base: float = 181000.0, point: float = 1.0, ticks_per: int = 15) -> None:
    for candle_i in range(n):
        for ti in range(ticks_per):
            if ti < ticks_per // 2:
                price = base + ti * 0.5
            else:
                price = base + (ticks_per - ti) * 0.5
            tick = make_tick(price, price + 2, time_ms=int(time.time() * 1000) + candle_i * 1000 + ti * 10)
            eng.on_tick(tick)


def feed_pullback_then_resume(eng: MicroStructureEngine, close_price: float = 181000.0, point: float = 1.0) -> None:
    for ti in range(15):
        price = close_price - ti * 0.5
        tick = make_tick(price, price + 2, time_ms=int(time.time() * 1000) + ti * 10)
        eng.on_tick(tick)
    for ti in range(15):
        price = close_price - 7.0 + ti * 1.0
        tick = make_tick(price, price + 2, time_ms=int(time.time() * 1000) + 15000 + ti * 10)
        eng.on_tick(tick)
    for ti in range(15):
        price = close_price + 2.0 + ti * 0.5
        tick = make_tick(price, price + 2, time_ms=int(time.time() * 1000) + 30000 + ti * 10)
        eng.on_tick(tick)


def test_micro_pullback_healthy_allow() -> bool:
    eng = MicroStructureEngine(candle_ticks=15, point=1.0, threshold_base=0.45)
    close_price = 181000.0
    feed_pullback_then_resume(eng, close_price=close_price)
    tick = make_tick(close_price - 5.0, close_price - 3.0)
    metrics = make_metrics(vel_fast=10.0, disp=8.0, acc=3.0)
    result = eng.evaluate_reentry(tick, metrics, close_price, OrderSide.BUY, -5.0)
    ok = result.allowed and result.retrace_score > 0.2
    tag = "PASS" if ok else "FAIL"
    print(f"{tag}: test_micro_pullback_healthy_allow — allowed={result.allowed} retrace={result.retrace_score:.2f} final={result.final_score:.3f} mode={result.mode}")
    return ok


def test_breakout_strong_allow() -> bool:
    eng = MicroStructureEngine(candle_ticks=15, point=1.0)
    close_price = 181000.0
    feed_bullish_candles(eng, n=3, base=close_price - 10)
    breakout_tick = make_tick(close_price + 15.0, close_price + 17.0)
    metrics = make_metrics(vel_fast=15.0, disp=20.0, acc=5.0)
    result = eng.evaluate_reentry(breakout_tick, metrics, close_price, OrderSide.BUY, -5.0)
    ok = result.allowed and result.breakout_score > 0.2
    tag = "PASS" if ok else "FAIL"
    print(f"{tag}: test_breakout_strong_allow — allowed={result.allowed} breakout={result.breakout_score:.2f} final={result.final_score:.3f} mode={result.mode}")
    return ok


def test_echo_trade_same_price_block() -> bool:
    eng = MicroStructureEngine(candle_ticks=15, point=1.0)
    close_price = 181000.0
    feed_chop_candles(eng, n=3, base=close_price)
    echo_tick = make_tick(close_price - 1.0, close_price + 1.0)
    metrics = make_metrics(vel_fast=4.0, disp=1.0, acc=0.0)
    result = eng.evaluate_reentry(echo_tick, metrics, close_price, OrderSide.BUY, -5.0)
    ok = not result.allowed and result.final_score < 0.20
    tag = "PASS" if ok else "FAIL"
    print(f"{tag}: test_echo_trade_same_price_block — allowed={result.allowed} echo={result.echo_blocked} final={result.final_score:.3f} retrace={result.retrace_score:.2f} consistency={result.consistency_score:.2f}")
    return ok


def test_chop_lateral_block() -> bool:
    eng = MicroStructureEngine(candle_ticks=15, point=1.0)
    close_price = 181000.0
    feed_chop_candles(eng, n=3, base=close_price)
    tick = make_tick(close_price + 5.0, close_price + 7.0)
    metrics = make_metrics(vel_fast=5.0, disp=4.0, acc=0.0)
    result = eng.evaluate_reentry(tick, metrics, close_price, OrderSide.BUY, -5.0)
    ok = not result.allowed
    tag = "PASS" if ok else "FAIL"
    print(f"{tag}: test_chop_lateral_block — allowed={result.allowed} chop_pen={result.chop_penalty:.2f} structure={result.structure_score:.2f} final={result.final_score:.3f}")
    return ok


def test_fake_breakout_block() -> bool:
    eng = MicroStructureEngine(candle_ticks=15, point=1.0)
    close_price = 181000.0
    feed_bullish_candles(eng, n=2, base=close_price - 5)
    feed_bearish_candles(eng, n=1, base=close_price + 2)
    breakout_tick = make_tick(close_price + 8.0, close_price + 10.0)
    metrics = make_metrics(vel_fast=4.0, disp=3.0, acc=-2.0)
    result = eng.evaluate_reentry(breakout_tick, metrics, close_price, OrderSide.BUY, -5.0)
    ok = not result.allowed or result.final_score < 0.55
    tag = "PASS" if ok else "FAIL"
    print(f"{tag}: test_fake_breakout_block — allowed={result.allowed} breakout={result.breakout_score:.2f} velocity={result.velocity_score:.2f} final={result.final_score:.3f}")
    return ok


def test_retrace_then_reaccelerate_allow() -> bool:
    eng = MicroStructureEngine(candle_ticks=15, point=1.0, threshold_base=0.45)
    close_price = 181000.0
    feed_pullback_then_resume(eng, close_price=close_price)
    tick = make_tick(close_price - 4.0, close_price - 2.0)
    metrics = make_metrics(vel_fast=10.0, disp=8.0, acc=3.0)
    result = eng.evaluate_reentry(tick, metrics, close_price, OrderSide.BUY, -5.0)
    ok = result.allowed and result.retrace_score > 0.2
    tag = "PASS" if ok else "FAIL"
    print(f"{tag}: test_retrace_then_reaccelerate_allow — allowed={result.allowed} retrace={result.retrace_score:.2f} final={result.final_score:.3f} mode={result.mode}")
    return ok


def test_structural_reversal_block() -> bool:
    eng = MicroStructureEngine(candle_ticks=15, point=1.0)
    close_price = 181000.0
    feed_bullish_candles(eng, n=1, base=close_price - 5)
    feed_bearish_candles(eng, n=2, base=close_price)
    tick = make_tick(close_price + 4.0, close_price + 6.0)
    metrics = make_metrics(vel_fast=5.0, disp=3.0, acc=-1.0)
    result = eng.evaluate_reentry(tick, metrics, close_price, OrderSide.BUY, -5.0)
    ok = not result.allowed or result.structure_score < 0.4
    tag = "PASS" if ok else "FAIL"
    print(f"{tag}: test_structural_reversal_block — allowed={result.allowed} structure={result.structure_score:.2f} final={result.final_score:.3f}")
    return ok


def test_flip_entry_no_gate() -> bool:
    eng = MicroStructureEngine(candle_ticks=15, point=1.0)
    close_price = 181000.0
    feed_bearish_candles(eng, n=3, base=close_price)
    tick = make_tick(close_price - 5.0, close_price - 3.0)
    metrics = make_metrics(vel_fast=-8.0, disp=-6.0, acc=-2.0)
    result = eng.evaluate_reentry(tick, metrics, close_price, OrderSide.BUY, -5.0)
    ok = result.allowed and result.mode == "flip"
    tag = "PASS" if ok else "FAIL"
    print(f"{tag}: test_flip_entry_no_gate — allowed={result.allowed} mode={result.mode}")
    return ok


def test_first_trade_no_gate() -> bool:
    eng = MicroStructureEngine(candle_ticks=15, point=1.0)
    tick = make_tick(181000.0, 181002.0)
    metrics = make_metrics(vel_fast=8.0, disp=5.0)
    result = eng.evaluate_reentry(tick, metrics, 0.0, None, 0.0)
    ok = result.allowed and result.mode == "first_trade"
    tag = "PASS" if ok else "FAIL"
    print(f"{tag}: test_first_trade_no_gate — allowed={result.allowed} mode={result.mode}")
    return ok


def test_sell_side_pullback_allow() -> bool:
    eng = MicroStructureEngine(candle_ticks=15, point=1.0)
    close_price = 181000.0
    for ti in range(15):
        price = close_price + ti * 0.5
        tick = make_tick(price, price + 2, time_ms=int(time.time() * 1000) + ti * 10)
        eng.on_tick(tick)
    for ti in range(15):
        price = close_price + 7.0 - ti * 1.0
        tick = make_tick(price, price + 2, time_ms=int(time.time() * 1000) + 15000 + ti * 10)
        eng.on_tick(tick)
    for ti in range(15):
        price = close_price - 2.0 - ti * 0.5
        tick = make_tick(price, price + 2, time_ms=int(time.time() * 1000) + 30000 + ti * 10)
        eng.on_tick(tick)
    tick = make_tick(close_price + 4.0, close_price + 6.0)
    metrics = make_metrics(vel_fast=-8.0, disp=-6.0, acc=-2.0)
    result = eng.evaluate_reentry(tick, metrics, close_price, OrderSide.SELL, -5.0)
    ok = result.allowed
    tag = "PASS" if ok else "FAIL"
    print(f"{tag}: test_sell_side_pullback_allow — allowed={result.allowed} retrace={result.retrace_score:.2f} final={result.final_score:.3f}")
    return ok


def test_adaptive_threshold_relaxes() -> bool:
    eng = MicroStructureEngine(candle_ticks=15, point=1.0, threshold_base=0.55, freq_target=3.0, freq_window_s=60.0)
    initial = eng._threshold_base
    now = time.time()
    for _ in range(15):
        eng._ring_push_time(eng._eval_times, now - 1.0)
        eng._eval_times_count += 1
    eng._adapt_threshold()
    relaxed = eng._threshold_current
    ok = relaxed < initial
    tag = "PASS" if ok else "FAIL"
    print(f"{tag}: test_adaptive_threshold_relaxes — initial={initial:.3f} relaxed={relaxed:.3f}")
    return ok


def test_candle_finalization() -> bool:
    c = MicroCandle()
    c.open_price = 100.0
    c.high = 110.0
    c.low = 95.0
    c.close = 108.0
    c.tick_count = 15
    c.finalize()
    expected_body = (108.0 - 100.0) / (110.0 - 95.0)
    ok = c.direction == 1 and abs(c.body_ratio - expected_body) < 0.001 and c.strength > 0.0
    tag = "PASS" if ok else "FAIL"
    print(f"{tag}: test_candle_finalization — dir={c.direction} body={c.body_ratio:.3f} expected={expected_body:.3f} strength={c.strength:.3f}")
    return ok


def test_deep_retracement_penalty() -> bool:
    eng = MicroStructureEngine(candle_ticks=15, point=1.0)
    close_price = 181000.0
    for ti in range(15):
        price = close_price - ti * 1.0
        tick = make_tick(price, price + 2, time_ms=int(time.time() * 1000) + ti * 10)
        eng.on_tick(tick)
    deep_tick = make_tick(close_price - 25.0, close_price - 23.0)
    metrics = make_metrics(vel_fast=3.0, disp=2.0, acc=-1.0)
    result = eng.evaluate_reentry(deep_tick, metrics, close_price, OrderSide.BUY, -5.0)
    ok = result.retrace_score < 0.3
    tag = "PASS" if ok else "FAIL"
    print(f"{tag}: test_deep_retracement_penalty — retrace={result.retrace_score:.2f} final={result.final_score:.3f}")
    return ok


def test_no_retracement_no_breakout_block() -> bool:
    eng = MicroStructureEngine(candle_ticks=15, point=1.0)
    close_price = 181000.0
    feed_bullish_candles(eng, n=3, base=close_price - 2)
    tick = make_tick(close_price + 1.0, close_price + 3.0)
    metrics = make_metrics(vel_fast=5.0, disp=2.0, acc=0.5)
    result = eng.evaluate_reentry(tick, metrics, close_price, OrderSide.BUY, -5.0)
    no_retrace = result.retrace_score < 0.15
    no_breakout = result.breakout_score < 0.15
    ok = (not result.allowed) or (no_retrace and no_breakout and result.final_score < 0.55)
    tag = "PASS" if ok else "FAIL"
    print(f"{tag}: test_no_retracement_no_breakout_block — allowed={result.allowed} retrace={result.retrace_score:.2f} breakout={result.breakout_score:.2f} final={result.final_score:.3f}")
    return ok


def test_spread_penalty() -> bool:
    eng = MicroStructureEngine(candle_ticks=15, point=1.0, spread_penalty=0.10)
    close_price = 181000.0
    feed_bullish_candles(eng, n=3, base=close_price - 5)
    low_spread = make_tick(close_price + 8.0, close_price + 9.0)
    high_spread = make_tick(close_price + 8.0, close_price + 15.0)
    metrics = make_metrics(vel_fast=10.0, disp=10.0, acc=2.0)
    r_low = eng.evaluate_reentry(low_spread, metrics, close_price, OrderSide.BUY, -5.0)
    r_high = eng.evaluate_reentry(high_spread, metrics, close_price, OrderSide.BUY, -5.0)
    ok = r_high.spread_penalty > r_low.spread_penalty
    tag = "PASS" if ok else "FAIL"
    print(f"{tag}: test_spread_penalty — low_pen={r_low.spread_penalty:.3f} high_pen={r_high.spread_penalty:.3f}")
    return ok


def test_retrace_priority_over_breakout() -> bool:
    eng = MicroStructureEngine(candle_ticks=15, point=1.0, retrace_score=0.30, breakout_score=0.20)
    ok = eng._retrace_w > eng._breakout_w
    tag = "PASS" if ok else "FAIL"
    print(f"{tag}: test_retrace_priority_over_breakout — retrace_w={eng._retrace_w:.2f} breakout_w={eng._breakout_w:.2f}")
    return ok


def test_performance_benchmark() -> bool:
    eng = MicroStructureEngine(candle_ticks=15, point=1.0)
    close_price = 181000.0
    for i in range(5):
        for ti in range(15):
            price = close_price + (ti - 7) * 0.5 + i * 2
            tick = make_tick(price, price + 2, time_ms=int(time.time() * 1000) + i * 1000 + ti * 10)
            eng.on_tick(tick)

    metrics = make_metrics(vel_fast=8.0, disp=5.0, acc=1.0)
    tick = make_tick(close_price + 5.0, close_price + 7.0)

    n = 10000
    start = time.perf_counter()
    for _ in range(n):
        eng.evaluate_reentry(tick, metrics, close_price, OrderSide.BUY, -5.0)
    elapsed = time.perf_counter() - start
    per_eval_us = (elapsed / n) * 1_000_000
    per_tick_us = 0.0
    start2 = time.perf_counter()
    for _ in range(n):
        eng.on_tick(tick)
    elapsed2 = time.perf_counter() - start2
    per_tick_us = (elapsed2 / n) * 1_000_000

    ok = per_eval_us < 2000 and per_tick_us < 100
    tag = "PASS" if ok else "FAIL"
    print(f"{tag}: test_performance_benchmark — eval={per_eval_us:.1f}µs/eval tick={per_tick_us:.1f}µs/tick (target: eval<2000µs, tick<100µs)")
    return ok


def test_adaptive_threshold_tightens_high_freq() -> bool:
    eng = MicroStructureEngine(candle_ticks=15, point=1.0, threshold_base=0.55, freq_target=3.0, freq_window_s=60.0)
    initial = eng._threshold_base
    now = time.time()
    for _ in range(20):
        eng._ring_push_time(eng._eval_times, now - 1.0)
        eng._eval_times_count += 1
    for _ in range(30):
        eng._ring_push_time(eng._trade_times, now - 1.0)
        eng._trade_times_count += 1
    eng._adapt_threshold()
    tightened = eng._threshold_current
    ok = tightened > initial
    tag = "PASS" if ok else "FAIL"
    print(f"{tag}: test_adaptive_threshold_tightens_high_freq — initial={initial:.3f} tightened={tightened:.3f}")
    return ok


def test_adaptive_threshold_tightens_bad_wr() -> bool:
    eng = MicroStructureEngine(candle_ticks=15, point=1.0, threshold_base=0.55, freq_target=3.0, freq_window_s=60.0)
    initial = eng._threshold_base
    now = time.time()
    for _ in range(20):
        eng._ring_push_time(eng._eval_times, now - 1.0)
        eng._eval_times_count += 1
    for _ in range(5):
        eng._ring_push_time(eng._trade_times, now - 1.0)
        eng._trade_times_count += 1
    for _ in range(8):
        eng.notify_outcome(-5.0)
    for _ in range(2):
        eng.notify_outcome(3.0)
    eng._adapt_threshold()
    tightened = eng._threshold_current
    ok = tightened > initial
    tag = "PASS" if ok else "FAIL"
    wr = eng._wins / (eng._wins + eng._losses) * 100.0 if (eng._wins + eng._losses) > 0 else 0
    print(f"{tag}: test_adaptive_threshold_tightens_bad_wr — initial={initial:.3f} tightened={tightened:.3f} wr={wr:.0f}%")
    return ok


def test_adaptive_threshold_negative_pnl_tighten() -> bool:
    eng = MicroStructureEngine(candle_ticks=15, point=1.0, threshold_base=0.55, freq_target=3.0, freq_window_s=60.0)
    initial = eng._threshold_base
    now = time.time()
    for _ in range(20):
        eng._ring_push_time(eng._eval_times, now - 1.0)
        eng._eval_times_count += 1
    for _ in range(5):
        eng._ring_push_time(eng._trade_times, now - 1.0)
        eng._trade_times_count += 1
    for _ in range(12):
        eng.notify_outcome(-5.0)
    for _ in range(3):
        eng.notify_outcome(2.0)
    eng._adapt_threshold()
    tightened = eng._threshold_current
    ok = tightened > initial
    tag = "PASS" if ok else "FAIL"
    print(f"{tag}: test_adaptive_threshold_negative_pnl_tighten — initial={initial:.3f} tightened={tightened:.3f} pnl={eng._pnl_sum:.0f}")
    return ok


def test_echo_bypass_with_retrace() -> bool:
    eng = MicroStructureEngine(candle_ticks=15, point=1.0, echo_proximity_pts=3.0, threshold_base=0.45)
    close_price = 181000.0
    feed_pullback_then_resume(eng, close_price=close_price)
    tick = make_tick(close_price - 1.5, close_price + 0.5)
    metrics = make_metrics(vel_fast=10.0, disp=8.0, acc=3.0)
    result = eng.evaluate_reentry(tick, metrics, close_price, OrderSide.BUY, -5.0)
    ok = not result.echo_blocked
    tag = "PASS" if ok else "FAIL"
    print(f"{tag}: test_echo_bypass_with_retrace — echo={result.echo_blocked} retrace={result.retrace_score:.2f} final={result.final_score:.3f}")
    return ok


def test_weak_pullback_penalty() -> bool:
    eng = MicroStructureEngine(candle_ticks=15, point=1.0, threshold_base=0.45)
    close_price = 181000.0
    feed_pullback_then_resume(eng, close_price=close_price)
    tick = make_tick(close_price - 0.5, close_price + 1.5)
    metrics = make_metrics(vel_fast=3.0, disp=1.0, acc=0.2)
    result = eng.evaluate_reentry(tick, metrics, close_price, OrderSide.BUY, -5.0)
    is_weak = result.retrace_score < 0.15
    has_penalty = result.final_score < 0.30
    ok = is_weak and has_penalty
    tag = "PASS" if ok else "FAIL"
    print(f"{tag}: test_weak_pullback_penalty — retrace={result.retrace_score:.2f} mode={result.mode} final={result.final_score:.3f}")
    return ok


def test_weak_breakout_penalty() -> bool:
    eng = MicroStructureEngine(candle_ticks=15, point=1.0, threshold_base=0.45)
    close_price = 181000.0
    feed_chop_candles(eng, n=3, base=close_price)
    tick = make_tick(close_price + 1.0, close_price + 3.0)
    metrics = make_metrics(vel_fast=5.0, disp=2.0, acc=0.3)
    result = eng.evaluate_reentry(tick, metrics, close_price, OrderSide.BUY, -5.0)
    is_weak_breakout = result.breakout_score < 0.20
    ok = is_weak_breakout and result.final_score < 0.30
    tag = "PASS" if ok else "FAIL"
    print(f"{tag}: test_weak_breakout_penalty — breakout={result.breakout_score:.2f} mode={result.mode} final={result.final_score:.3f}")
    return ok


def test_speed_filter_chop_penalty_lento() -> bool:
    eng = MicroStructureEngine(candle_ticks=15, point=1.0, chop_penalty=0.10)
    close_price = 181000.0
    feed_bullish_candles(eng, n=3, base=close_price - 5)
    eng.set_speed_state("LENTO")
    tick = make_tick(close_price + 8.0, close_price + 10.0)
    metrics = make_metrics(vel_fast=8.0, disp=5.0, acc=1.0)
    result = eng.evaluate_reentry(tick, metrics, close_price, OrderSide.BUY, -5.0)
    ok = result.chop_penalty >= 0.08
    tag = "PASS" if ok else "FAIL"
    print(f"{tag}: test_speed_filter_chop_penalty_lento — chop_pen={result.chop_penalty:.2f}")
    return ok


def test_speed_filter_chop_penalty_exaustao() -> bool:
    eng = MicroStructureEngine(candle_ticks=15, point=1.0, chop_penalty=0.15)
    close_price = 181000.0
    feed_bullish_candles(eng, n=3, base=close_price - 5)
    eng.set_speed_state("EXAUSTAO")
    tick = make_tick(close_price + 8.0, close_price + 10.0)
    metrics = make_metrics(vel_fast=8.0, disp=5.0, acc=1.0)
    result = eng.evaluate_reentry(tick, metrics, close_price, OrderSide.BUY, -5.0)
    ok = result.chop_penalty >= 0.15
    tag = "PASS" if ok else "FAIL"
    print(f"{tag}: test_speed_filter_chop_penalty_exaustao — chop_pen={result.chop_penalty:.2f}")
    return ok


def test_speed_filter_no_penalty_forte() -> bool:
    eng = MicroStructureEngine(candle_ticks=15, point=1.0, chop_penalty=0.10)
    close_price = 181000.0
    feed_bullish_candles(eng, n=3, base=close_price - 5)
    eng.set_speed_state("FORTE")
    tick = make_tick(close_price + 8.0, close_price + 10.0)
    metrics = make_metrics(vel_fast=8.0, disp=5.0, acc=1.0)
    result = eng.evaluate_reentry(tick, metrics, close_price, OrderSide.BUY, -5.0)
    ok = result.chop_penalty < 0.08
    tag = "PASS" if ok else "FAIL"
    print(f"{tag}: test_speed_filter_no_penalty_forte — chop_pen={result.chop_penalty:.2f}")
    return ok


def test_dir_align_partial_score() -> bool:
    eng = MicroStructureEngine(candle_ticks=15, point=1.0)
    close_price = 181000.0
    feed_bullish_candles(eng, n=3, base=close_price - 5)
    tick = make_tick(close_price + 5.0, close_price + 7.0)
    metrics = make_metrics(vel_fast=1.0, disp=5.0, acc=0.0)
    result = eng.evaluate_reentry(tick, metrics, close_price, OrderSide.BUY, -5.0)
    ok = result.consistency_score >= 0.5 and result.consistency_score < 0.8
    tag = "PASS" if ok else "FAIL"
    print(f"{tag}: test_dir_align_partial_score — consistency={result.consistency_score:.2f} (dir_align=1.0 vel_ratio=0.1 disp_score=0.6)")
    return ok


if __name__ == "__main__":
    tests = [
        test_micro_pullback_healthy_allow,
        test_breakout_strong_allow,
        test_echo_trade_same_price_block,
        test_chop_lateral_block,
        test_fake_breakout_block,
        test_retrace_then_reaccelerate_allow,
        test_structural_reversal_block,
        test_flip_entry_no_gate,
        test_first_trade_no_gate,
        test_sell_side_pullback_allow,
        test_adaptive_threshold_relaxes,
        test_adaptive_threshold_tightens_high_freq,
        test_adaptive_threshold_tightens_bad_wr,
        test_adaptive_threshold_negative_pnl_tighten,
        test_candle_finalization,
        test_deep_retracement_penalty,
        test_no_retracement_no_breakout_block,
        test_spread_penalty,
        test_retrace_priority_over_breakout,
        test_echo_bypass_with_retrace,
        test_weak_pullback_penalty,
        test_weak_breakout_penalty,
        test_speed_filter_chop_penalty_lento,
        test_speed_filter_chop_penalty_exaustao,
        test_speed_filter_no_penalty_forte,
        test_dir_align_partial_score,
        test_performance_benchmark,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            if t():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"FAIL: {t.__name__} — exception: {e}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed out of {len(tests)}")
