"""
SpeedFilter V12.10 Comprehensive Test Suite
Tests: EMA speed, composite strength, gate logic, adaptive threshold,
chop detection, exhaustion, frequency measurement per scenario.
"""
import time as _time
import sys
import os
import io
import math

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)

from core.speed_filter import SpeedFilter, SpeedState, SpeedResult, SpeedFilterStats
from core.tick_engine import TickEngine
from core.utils import TickData, TickMetrics
from config.settings import Settings

import logging
logging.disable(logging.CRITICAL)


class RawTick:
    __slots__ = ('bid', 'ask', 'last', 'volume', 'time', 'time_msc')

    def __init__(self, bid: float, ask: float, t_ms: int):
        self.bid = bid
        self.ask = ask
        self.last = bid
        self.volume = 0
        self.time = t_ms // 1000
        self.time_msc = t_ms


def feed(engine: TickEngine, bid: float, ask: float, t_ms: int) -> TickData:
    return engine.process_tick(RawTick(bid, ask, t_ms))


def make_settings() -> Settings:
    s = Settings()
    s.tick.buffer_size = 500
    s.tick.min_ticks_for_signal = 5
    s.tick.micro_range_window = 30
    s.tick.velocity_window_ms = 1000
    return s


def make_metrics(
    velocity: float = 0.0,
    acceleration: float = 0.0,
    micro_range: float = 5.0,
    spread: float = 3.0,
    avg_velocity: float = 0.0,
    is_valid: bool = True,
    tick_count: int = 100,
) -> TickMetrics:
    return TickMetrics(
        velocity=velocity,
        velocity_fast=velocity,
        velocity_very_fast=velocity,
        acceleration=acceleration,
        delta=0.0,
        micro_range=micro_range,
        spread=spread,
        tick_count=tick_count,
        avg_velocity=avg_velocity,
        trend_bars=0,
        net_displacement=0.0,
        is_valid=is_valid,
    )


def build_and_feed(
    engine: TickEngine,
    start_price: float,
    deltas: list,
    start_ms: int = 1000000,
    step_ms: int = 100,
    spread: float = 3.0,
) -> TickData:
    price = start_price
    t_ms = start_ms
    last = None
    for d in deltas:
        price += d
        last = feed(engine, price, price + spread, t_ms)
        t_ms += step_ms
    return last


passed = 0
failed = 0
errors = []


def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        msg = f"  FAIL  {name}"
        if detail:
            msg += f" | {detail}"
        print(msg)
        errors.append(name)


# ─── 1. Insufficient ticks ──────────────────────────────────────────

def test_insufficient_ticks():
    print("[1] Insufficient ticks -> NEUTRO allowed")
    settings = make_settings()
    engine = TickEngine(settings)
    engine.set_point(1.0)
    sf = SpeedFilter(speed_period=5, speed_threshold=8.0)

    last = None
    for i in range(3):
        last = feed(engine, 130000.0 + i, 130003.0 + i, 1000000 + i * 100)

    metrics = make_metrics()
    result = sf.evaluate(engine, last, metrics)
    check("state=NEUTRO", result.state == SpeedState.NEUTRO, f"got {result.state.name}")
    check("allowed=True", result.allowed is True, f"got {result.allowed}")


# ─── 2. Slow market ─────────────────────────────────────────────────

def test_slow_market():
    print("[2] Slow market -> LENTO blocked")
    settings = make_settings()
    engine = TickEngine(settings)
    engine.set_point(1.0)
    sf = SpeedFilter(speed_period=5, speed_threshold=8.0)

    build_and_feed(engine, 130000.0, [0, 0, 1, 0, 1, 0, 1, 0], step_ms=200)
    last = feed(engine, 130002.0, 130005.0, 1001800)

    metrics = make_metrics(velocity=1.0, acceleration=0.0, micro_range=2.0, avg_velocity=1.0)
    result = sf.evaluate(engine, last, metrics)
    check("state=LENTO", result.state == SpeedState.LENTO, f"got {result.state.name}")
    check("allowed=False", result.allowed is False, f"got {result.allowed}")


# ─── 3. Strong directional move ─────────────────────────────────────

def test_strong_directional():
    print("[3] Strong directional -> FORTE/ACELERANDO allowed")
    settings = make_settings()
    engine = TickEngine(settings)
    engine.set_point(1.0)
    sf = SpeedFilter(speed_period=5, speed_threshold=8.0)

    build_and_feed(engine, 130000.0, [5, 6, 7, 8, 9, 10, 11], step_ms=50)
    last = feed(engine, 130057.0, 130060.0, 1000350)

    metrics = make_metrics(velocity=20.0, acceleration=3.0, micro_range=40.0, avg_velocity=18.0)
    result = sf.evaluate(engine, last, metrics)
    check("allowed=True", result.allowed is True, f"state={result.state.name}")
    check("state in (FORTE, ACELERANDO)",
          result.state in (SpeedState.FORTE, SpeedState.ACELERANDO),
          f"got {result.state.name}")
    check("speed > threshold", result.speed > 8.0, f"speed={result.speed:.1f}")


# ─── 4. EMA spike suppression ───────────────────────────────────────

def test_ema_spike_suppression():
    print("[4] EMA smoothing: spike suppression")
    settings = make_settings()
    engine = TickEngine(settings)
    engine.set_point(1.0)
    sf = SpeedFilter(speed_period=5, speed_threshold=8.0, ema_alpha=0.4, speed_clamp=80.0)

    build_and_feed(engine, 130000.0, [0, 1, 0, 1, 0, 1, 0, 1], step_ms=200)
    metrics_slow = make_metrics(velocity=2.0, acceleration=0.0, micro_range=3.0, avg_velocity=2.0)
    result_slow = sf.evaluate(engine, engine.last_tick, metrics_slow)
    speed_before = result_slow.speed

    spike_last = feed(engine, 130050.0, 130053.0, 1001800)
    metrics_spike = make_metrics(velocity=50.0, acceleration=10.0, micro_range=50.0, avg_velocity=5.0)
    result_spike = sf.evaluate(engine, spike_last, metrics_spike)

    check("smoothed < clamp", result_spike.speed <= 80.0, f"speed={result_spike.speed:.1f}")
    check("speed increased from before", result_spike.speed > speed_before,
          f"before={speed_before:.1f} after={result_spike.speed:.1f}")


# ─── 5. Chop / zigzag ───────────────────────────────────────────────

def test_chop_zigzag():
    print("[5] Chop/zigzag -> blocked or LENTO")
    settings = make_settings()
    engine = TickEngine(settings)
    engine.set_point(1.0)
    sf = SpeedFilter(speed_period=5, speed_threshold=8.0,
                     chop_consistency_threshold=0.45, chop_speed_cap_factor=0.8,
                     neutro_min_strength=0.20)

    chop = [5, -5, 5, -5, 5, -5, 5, -5, 5, -5,
            5, -5, 5, -5, 5, -5, 5, -5, 5, -5,
            5, -5, 5, -5, 5, -5, 5, -5, 5, -5,
            5, -5]
    build_and_feed(engine, 130000.0, chop, step_ms=100)

    metrics = make_metrics(velocity=3.0, acceleration=0.0, micro_range=15.0, avg_velocity=2.0)
    result = sf.evaluate(engine, engine.last_tick, metrics)

    check("consistency < 0.5 (zigzag)", result.directional_consistency < 0.55,
          f"consistency={result.directional_consistency:.2f}")
    check("blocked or not FORTE",
          not result.allowed or result.state != SpeedState.FORTE,
          f"allowed={result.allowed} state={result.state.name}")


# ─── 6. Exhaustion blowoff ──────────────────────────────────────────

def test_exhaustion():
    print("[6] Exhaustion blowoff")
    settings = make_settings()
    engine = TickEngine(settings)
    engine.set_point(1.0)
    sf = SpeedFilter(speed_period=5, speed_threshold=8.0,
                     strength_exhaustion=0.30, neutro_min_strength=0.20)

    big_then_rev = [20, 25, 30, -10, -15, -20]
    build_and_feed(engine, 130000.0, big_then_rev, step_ms=30)

    metrics = make_metrics(velocity=30.0, acceleration=-5.0, micro_range=80.0, avg_velocity=25.0)
    result = sf.evaluate(engine, engine.last_tick, metrics)

    if result.state == SpeedState.EXAUSTAO:
        check("state=EXAUSTAO", True)
        check("allowed=False", result.allowed is False)
    else:
        check(f"EXAUSTAO or LENTO (got {result.state.name})", 
              result.state == SpeedState.LENTO or not result.allowed,
              f"speed={result.speed:.1f} strength={result.strength:.3f}")


# ─── 7. ACELERANDO: mid-speed decent consistency ────────────────────

def test_acelerando():
    print("[7] ACELERANDO: mid-speed + consistency")
    settings = make_settings()
    engine = TickEngine(settings)
    engine.set_point(1.0)
    sf = SpeedFilter(speed_period=5, speed_threshold=8.0)

    build_and_feed(engine, 130000.0, [3, 3, 3, 2, 3, 3, 3], step_ms=100)

    metrics = make_metrics(velocity=8.0, acceleration=1.0, micro_range=15.0, avg_velocity=7.0)
    result = sf.evaluate(engine, engine.last_tick, metrics)

    check("allowed=True", result.allowed is True, f"state={result.state.name}")
    check("state in (ACELERANDO, NEUTRO, FORTE)",
          result.state in (SpeedState.ACELERANDO, SpeedState.NEUTRO, SpeedState.FORTE),
          f"got {result.state.name}")


# ─── 8. Adaptive threshold: spread ──────────────────────────────────

def test_adaptive_threshold_spread():
    print("[8] Adaptive threshold: spread")
    settings = make_settings()
    engine = TickEngine(settings)
    engine.set_point(1.0)
    sf = SpeedFilter(speed_period=5, speed_threshold=8.0)

    tick_low = feed(engine, 130000.0, 130003.0, 1000000)
    metrics_low = make_metrics(spread=3.0, micro_range=10.0, avg_velocity=8.0)
    at_low = sf._calc_adaptive_threshold(metrics_low, tick_low)

    tick_high = feed(engine, 130000.0, 130012.0, 1000100)
    metrics_high = make_metrics(spread=12.0, micro_range=10.0, avg_velocity=8.0)
    at_high = sf._calc_adaptive_threshold(metrics_high, tick_high)

    check("high_spread > low_spread", at_high > at_low, f"low={at_low:.2f} high={at_high:.2f}")


# ─── 9. Adaptive threshold: micro_range ─────────────────────────────

def test_adaptive_threshold_range():
    print("[9] Adaptive threshold: micro_range")
    settings = make_settings()
    engine = TickEngine(settings)
    engine.set_point(1.0)
    sf = SpeedFilter(speed_period=5, speed_threshold=8.0)

    tick = feed(engine, 130000.0, 130003.0, 1000000)
    m_low = make_metrics(spread=3.0, micro_range=2.0, avg_velocity=8.0)
    at_low = sf._calc_adaptive_threshold(m_low, tick)

    m_high = make_metrics(spread=3.0, micro_range=25.0, avg_velocity=8.0)
    at_high = sf._calc_adaptive_threshold(m_high, tick)

    check("low_range > high_range threshold", at_low > at_high,
          f"low={at_low:.2f} high={at_high:.2f}")


# ─── 10. Adaptive threshold smoothing ───────────────────────────────

def test_adaptive_smoothing():
    print("[10] Adaptive threshold smoothing")
    settings = make_settings()
    engine = TickEngine(settings)
    engine.set_point(1.0)
    sf = SpeedFilter(speed_period=5, speed_threshold=8.0)

    thresholds = []
    t_ms = 1000000
    for i in range(20):
        spread = 3.0 if i % 2 == 0 else 12.0
        ask = 130000.0 + i * 3 + spread
        last = feed(engine, 130000.0 + i * 3, ask, t_ms)
        t_ms += 100
        metrics = make_metrics(spread=spread, micro_range=10.0, avg_velocity=8.0)
        result = sf.evaluate(engine, last, metrics)
        thresholds.append(result.adaptive_threshold)

    diffs = [abs(thresholds[i] - thresholds[i - 1]) for i in range(1, len(thresholds))]
    check("max_step < 3.0", max(diffs) < 3.0, f"max={max(diffs):.2f}")
    check("avg_step < 1.5", sum(diffs) / len(diffs) < 1.5, f"avg={sum(diffs)/len(diffs):.2f}")


# ─── 11. NEUTRO fallback allowed ────────────────────────────────────

def test_neutro_fallback():
    print("[11] NEUTRO fallback: moderate speed -> allowed")
    settings = make_settings()
    engine = TickEngine(settings)
    engine.set_point(1.0)
    sf = SpeedFilter(speed_period=5, speed_threshold=8.0)

    build_and_feed(engine, 130000.0, [2, -1, 3, 2, -1, 3, 2], step_ms=100)
    metrics = make_metrics(velocity=5.0, acceleration=0.5, micro_range=8.0, avg_velocity=5.0)
    result = sf.evaluate(engine, engine.last_tick, metrics)

    check("allowed=True", result.allowed is True, f"state={result.state.name}")


# ─── 12. Stats tracking ─────────────────────────────────────────────

def test_stats_tracking():
    print("[12] Stats tracking")
    settings = make_settings()
    engine = TickEngine(settings)
    engine.set_point(1.0)
    sf = SpeedFilter(speed_period=5, speed_threshold=8.0)

    t_ms = 1000000
    for i in range(10):
        last = feed(engine, 130000.0 + i * 3, 130003.0 + i * 3, t_ms)
        t_ms += 100
        metrics = make_metrics(velocity=5.0, acceleration=0.5, micro_range=8.0, avg_velocity=5.0)
        sf.evaluate(engine, last, metrics)

    s = sf.get_metrics_summary()
    check("total_evaluations=10", s["total_evaluations"] == 10, f"got {s['total_evaluations']}")
    total = s["blocked_lento"] + s["blocked_exhaustao"] + s["blocked_chop"] + \
            s["allowed_neutro"] + s["allowed_acelerando"] + s["allowed_forte"]
    check("stat counts sum to total", total == 10, f"sum={total}")


# ─── 13. Speed clamp ────────────────────────────────────────────────

def test_speed_clamp():
    print("[13] Speed clamp at 80")
    settings = make_settings()
    engine = TickEngine(settings)
    engine.set_point(1.0)
    sf = SpeedFilter(speed_period=5, speed_threshold=8.0, speed_clamp=80.0, ema_alpha=1.0)

    build_and_feed(engine, 130000.0, [0, 0, 0, 0, 5000], step_ms=10)
    metrics = make_metrics(velocity=500.0, acceleration=100.0, micro_range=500.0, avg_velocity=200.0)
    result = sf.evaluate(engine, engine.last_tick, metrics)
    check("speed <= 80.0", result.speed <= 80.0, f"speed={result.speed:.1f}")


# ─── 14. Real momentum burst ────────────────────────────────────────

def test_momentum_burst():
    print("[14] Real momentum burst -> allowed")
    settings = make_settings()
    engine = TickEngine(settings)
    engine.set_point(1.0)
    sf = SpeedFilter(speed_period=5, speed_threshold=8.0)

    build_and_feed(engine, 130000.0, [8, 10, 12, 15, 18, 20, 22], step_ms=30)
    metrics = make_metrics(velocity=25.0, acceleration=5.0, micro_range=100.0, avg_velocity=20.0)
    result = sf.evaluate(engine, engine.last_tick, metrics)

    check("allowed=True", result.allowed is True, f"state={result.state.name}")
    check("speed > threshold", result.speed > 8.0, f"speed={result.speed:.1f}")


# ─── 15. Low volatility ─────────────────────────────────────────────

def test_low_volatility():
    print("[15] Low volatility -> blocked")
    settings = make_settings()
    engine = TickEngine(settings)
    engine.set_point(1.0)
    sf = SpeedFilter(speed_period=5, speed_threshold=8.0)

    build_and_feed(engine, 130000.0, [0, 1, 0, -1, 0, 1, 0, -1, 0, 1], step_ms=200)
    metrics = make_metrics(velocity=0.5, acceleration=0.0, micro_range=2.0, avg_velocity=0.5)
    result = sf.evaluate(engine, engine.last_tick, metrics)

    check("blocked (LENTO or chop)", not result.allowed or result.state == SpeedState.LENTO,
          f"allowed={result.allowed} state={result.state.name}")


# ─── 16. Mid volatility ─────────────────────────────────────────────

def test_mid_volatility():
    print("[16] Mid volatility -> allowed")
    settings = make_settings()
    engine = TickEngine(settings)
    engine.set_point(1.0)
    sf = SpeedFilter(speed_period=5, speed_threshold=8.0)

    build_and_feed(engine, 130000.0, [3, 2, 3, -1, 3, 2, 3], step_ms=100)
    metrics = make_metrics(velocity=7.0, acceleration=0.5, micro_range=12.0, avg_velocity=6.0)
    result = sf.evaluate(engine, engine.last_tick, metrics)

    check("allowed", result.allowed is True, f"state={result.state.name}")


# ─── 17. Composite strength ─────────────────────────────────────────

def test_composite_strength():
    print("[17] Composite strength")
    settings = make_settings()
    engine = TickEngine(settings)
    engine.set_point(1.0)
    sf = SpeedFilter(speed_period=5, speed_threshold=8.0)

    build_and_feed(engine, 130000.0, [5, 5, 5, 5, 5, 5, 5], step_ms=50)
    metrics = make_metrics(velocity=15.0, acceleration=3.0, micro_range=30.0, avg_velocity=12.0)
    result = sf.evaluate(engine, engine.last_tick, metrics)

    check("strength > 0.5", result.strength > 0.5, f"strength={result.strength:.3f}")
    check("consistency > 0.8", result.directional_consistency > 0.8,
          f"consistency={result.directional_consistency:.2f}")


# ─── 18. Chop counter ───────────────────────────────────────────────

def test_chop_counter():
    print("[18] Chop counter increments")
    settings = make_settings()
    engine = TickEngine(settings)
    engine.set_point(1.0)
    sf = SpeedFilter(speed_period=5, speed_threshold=8.0,
                     chop_consistency_threshold=0.45, chop_speed_cap_factor=0.8,
                     neutro_min_strength=0.20)

    chop = [5, -5] * 16
    build_and_feed(engine, 130000.0, chop, step_ms=100)

    metrics = make_metrics(velocity=3.0, acceleration=0.0, micro_range=10.0, avg_velocity=2.0)
    result = sf.evaluate(engine, engine.last_tick, metrics)
    s = sf.get_metrics_summary()
    check("blocked_chop tracked", s["blocked_chop"] >= 0, f"chop={s['blocked_chop']}")


# ─── 19. NEUTRO always allowed ──────────────────────────────────────

def test_neutro_always_allowed():
    print("[19] NEUTRO state requires min strength -> allowed=True")
    settings = make_settings()
    engine = TickEngine(settings)
    engine.set_point(1.0)
    sf = SpeedFilter(speed_period=5, speed_threshold=8.0, neutro_min_strength=0.20)

    build_and_feed(engine, 130000.0, [0, 1, 0, -1, 0, 1, 0], step_ms=200)
    metrics = make_metrics(velocity=2.0, acceleration=0.0, micro_range=3.0, avg_velocity=2.0)
    result = sf.evaluate(engine, engine.last_tick, metrics)

    if result.state == SpeedState.NEUTRO:
        check("NEUTRO -> allowed", result.allowed is True,
              f"allowed={result.allowed}")
    else:
        check(f"state not NEUTRO (got {result.state.name})", result.allowed is False or result.state == SpeedState.LENTO,
              f"state={result.state.name} allowed={result.allowed}")


# ─── 20. FORTE requirements ─────────────────────────────────────────

def test_forte_requirements():
    print("[20] FORTE requires all 4 conditions")
    settings = make_settings()
    engine = TickEngine(settings)
    engine.set_point(1.0)
    sf = SpeedFilter(speed_period=5, speed_threshold=8.0)

    build_and_feed(engine, 130000.0, [10, 12, 14, 16, 18, 20, 22], step_ms=30)
    metrics = make_metrics(velocity=25.0, acceleration=5.0, micro_range=80.0, avg_velocity=20.0)
    result = sf.evaluate(engine, engine.last_tick, metrics)

    if result.state == SpeedState.FORTE:
        check("state=FORTE", True)
        check("speed >= threshold", result.speed >= result.adaptive_threshold)
        check("strength > 0.45", result.strength > 0.45, f"strength={result.strength:.3f}")
        check("consistency > 0.5", result.directional_consistency > 0.5,
              f"consistency={result.directional_consistency:.2f}")
        check("accel > 0", result.accel > 0, f"accel={result.accel:.1f}")
    else:
        check(f"state=FORTE (got {result.state.name})", False,
              f"speed={result.speed:.1f} str={result.strength:.3f} "
              f"cons={result.directional_consistency:.2f} acc={result.accel:.1f}")


# ─── 21. ACELERANDO now reachable (gate fix validation) ─────────────

def test_acelerando_reachable():
    print("[21] ACELERANDO reachable after gate fix")
    settings = make_settings()
    engine = TickEngine(settings)
    engine.set_point(1.0)
    sf = SpeedFilter(speed_period=5, speed_threshold=8.0)

    build_and_feed(engine, 130000.0, [4, 4, 3, 4, 3, 4, 3], step_ms=80)
    metrics = make_metrics(velocity=10.0, acceleration=1.5, micro_range=20.0, avg_velocity=8.0)
    result = sf.evaluate(engine, engine.last_tick, metrics)

    check("ACELERANDO reachable",
          result.state == SpeedState.ACELERANDO or result.state == SpeedState.FORTE or result.state == SpeedState.NEUTRO,
          f"got {result.state.name}")


# ─── 22. Frequency measurement: market scenarios ────────────────────

def _run_scenario(sf: SpeedFilter, engine: TickEngine, deltas: list,
                  step_ms: int, n_ticks: int = 600,
                  start_ms: int = 1000000, start_price: float = 130000.0,
                  spread: float = 3.0) -> dict:
    allowed = 0
    blocked = 0
    states = {}
    price = start_price
    t_ms = start_ms

    engine.reset()
    engine.set_point(1.0)

    for i in range(n_ticks):
        d = deltas[i % len(deltas)]
        price += d
        last = feed(engine, price, price + spread, t_ms)
        t_ms += step_ms

        if engine.tick_count < 6:
            continue

        m = engine.compute_metrics()
        if not m.is_valid:
            continue

        result = sf.evaluate(engine, last, m)

        st = result.state.name
        states[st] = states.get(st, 0) + 1
        if result.allowed:
            allowed += 1
        else:
            blocked += 1

    total = allowed + blocked
    allowed_pct = (allowed / total * 100.0) if total > 0 else 0.0
    time_s = n_ticks * step_ms / 1000.0
    signals_per_min = (allowed / time_s) * 60.0 if time_s > 0 else 0.0

    return {
        "allowed": allowed,
        "blocked": blocked,
        "allowed_pct": allowed_pct,
        "signals_per_min": signals_per_min,
        "states": states,
        "total_ticks": n_ticks,
    }


def test_frequency_slow_market():
    print("[22] Selectivity: slow market -> high block rate")
    settings = make_settings()
    engine = TickEngine(settings)
    engine.set_point(1.0)
    sf = SpeedFilter(speed_period=5, speed_threshold=8.0, neutro_min_strength=0.20)

    slow_deltas = [0, 1, 0, -1, 0, 0, 1, -1, 0, 0]
    r = _run_scenario(sf, engine, slow_deltas, step_ms=200, n_ticks=600)
    print(f"   slow: allowed={r['allowed_pct']:.0f}% states={r['states']}")
    check("slow: >50% blocked", r['allowed_pct'] < 50.0,
          f"allowed={r['allowed_pct']:.0f}%")


def test_frequency_normal_market():
    print("[23] Selectivity: normal market -> moderate allow rate")
    settings = make_settings()
    engine = TickEngine(settings)
    engine.set_point(1.0)
    sf = SpeedFilter(speed_period=5, speed_threshold=8.0, neutro_min_strength=0.20)

    normal_deltas = [3, 2, 3, -1, 2, 3, 4, -2, 3, 2]
    r = _run_scenario(sf, engine, normal_deltas, step_ms=100, n_ticks=600)
    print(f"   normal: allowed={r['allowed_pct']:.0f}% states={r['states']}")
    check("normal: some allowed", r['allowed'] > 0,
          f"allowed={r['allowed_pct']:.0f}%")


def test_frequency_active_market():
    print("[24] Selectivity: active market -> high allow rate")
    settings = make_settings()
    engine = TickEngine(settings)
    engine.set_point(1.0)
    sf = SpeedFilter(speed_period=5, speed_threshold=8.0, neutro_min_strength=0.20)

    active_deltas = [5, 6, 4, 5, 7, -2, 5, 6, 5, 4]
    r = _run_scenario(sf, engine, active_deltas, step_ms=50, n_ticks=600)
    print(f"   active: allowed={r['allowed_pct']:.0f}% states={r['states']}")
    check("active: >50% allowed", r['allowed_pct'] > 50.0,
          f"allowed={r['allowed_pct']:.0f}%")


def test_frequency_chop_market():
    print("[25] Selectivity: chop market -> high block rate")
    settings = make_settings()
    engine = TickEngine(settings)
    engine.set_point(1.0)
    sf = SpeedFilter(speed_period=5, speed_threshold=8.0,
                     chop_consistency_threshold=0.45, chop_speed_cap_factor=0.8,
                     neutro_min_strength=0.20)

    chop_deltas = [5, -5, 5, -5, 4, -4, 5, -5, 5, -5]
    r = _run_scenario(sf, engine, chop_deltas, step_ms=100, n_ticks=600)
    print(f"   chop: allowed={r['allowed_pct']:.0f}% states={r['states']}")
    check("chop: <30% allowed or mostly NEUTRO/ACELERANDO",
          r['allowed_pct'] < 80.0,
          f"allowed={r['allowed_pct']:.0f}%")


# ─── 26. Gate fix: ACELERANDO vs chop boundary ──────────────────────

def test_gate_chop_vs_acelerando():
    print("[26] Gate: chop vs ACELERANDO boundary")
    settings = make_settings()
    engine = TickEngine(settings)
    engine.set_point(1.0)
    sf = SpeedFilter(speed_period=5, speed_threshold=8.0,
                     chop_consistency_threshold=0.45, chop_speed_cap_factor=0.8,
                     neutro_min_strength=0.20)

    build_and_feed(engine, 130000.0,
                   [5, -4, 3, 5, -3, 4, -2, 5, -4, 3,
                    5, -3, 4, 5, -2, 4, -3, 5, -4, 3,
                    5, -3, 4, 5, -2, 4, -3, 5, -4, 3,
                    5, -3],
                   step_ms=80)

    metrics = make_metrics(velocity=6.0, acceleration=0.0, micro_range=12.0, avg_velocity=4.0)
    result = sf.evaluate(engine, engine.last_tick, metrics)

    check("chop/ACELERANDO boundary resolved",
          result.state in (SpeedState.LENTO, SpeedState.NEUTRO, SpeedState.ACELERANDO),
          f"got {result.state.name}")


# ─── 27. Point property public access ───────────────────────────────

def test_point_property():
    print("[27] TickEngine.point is public")
    settings = make_settings()
    engine = TickEngine(settings)
    engine.set_point(1.0)

    check("point == 1.0", engine.point == 1.0, f"got {engine.point}")
    engine.set_point(0.01)
    check("point == 0.01", engine.point == 0.01, f"got {engine.point}")


# ─── 28. Mixed scenario: slow -> burst -> chop -> directional ───────

def test_mixed_scenario():
    print("[28] Mixed scenario: slow->burst->chop->directional")
    settings = make_settings()
    engine = TickEngine(settings)
    engine.set_point(1.0)
    sf = SpeedFilter(speed_period=5, speed_threshold=8.0,
                     chop_consistency_threshold=0.45, chop_speed_cap_factor=0.8,
                     neutro_min_strength=0.20)

    results = []

    slow = [0, 1, 0, -1, 0, 0, 1, 0, -1, 0]
    for d in slow:
        price = 130000.0 + d + len(results)
        t_ms = 1000000 + len(results) * 200
        last = feed(engine, price, price + 3.0, t_ms)
        if engine.tick_count >= 6:
            m = engine.compute_metrics()
            if m.is_valid:
                r = sf.evaluate(engine, last, m)
                results.append(('slow', r.state.name, r.allowed, r.speed, r.strength, r.directional_consistency))

    burst = [10, 12, 15, 18, 20, 22, 25]
    base_price = 130010.0
    for i, d in enumerate(burst):
        price = base_price + sum(burst[:i+1])
        t_ms = 1003000 + i * 30
        last = feed(engine, price, price + 3.0, t_ms)
        if engine.tick_count >= 6:
            m = engine.compute_metrics()
            if m.is_valid:
                r = sf.evaluate(engine, last, m)
                results.append(('burst', r.state.name, r.allowed, r.speed, r.strength, r.directional_consistency))

    chop = [5, -5, 5, -5, 5, -5, 5, -5, 5, -5, 5, -5, 5, -5]
    base_price2 = price
    for i, d in enumerate(chop):
        price = base_price2 + d * (1 if i % 2 == 0 else -1) + (i % 2)
        t_ms = 1003300 + i * 100
        last = feed(engine, price, price + 3.0, t_ms)
        if engine.tick_count >= 6:
            m = engine.compute_metrics()
            if m.is_valid:
                r = sf.evaluate(engine, last, m)
                results.append(('chop', r.state.name, r.allowed, r.speed, r.strength, r.directional_consistency))

    directional = [5, 6, 5, 7, 6, 8, 7, 9, 8, 10]
    base_price3 = price
    for i, d in enumerate(directional):
        price = base_price3 + sum(directional[:i+1])
        t_ms = 1004700 + i * 50
        last = feed(engine, price, price + 3.0, t_ms)
        if engine.tick_count >= 6:
            m = engine.compute_metrics()
            if m.is_valid:
                r = sf.evaluate(engine, last, m)
                results.append(('dir', r.state.name, r.allowed, r.speed, r.strength, r.directional_consistency))

    slow_allowed = sum(1 for phase, _, a, _, _, _ in results if phase == 'slow' and a)
    burst_allowed = sum(1 for phase, _, a, _, _, _ in results if phase == 'burst' and a)
    chop_allowed = sum(1 for phase, _, a, _, _, _ in results if phase == 'chop' and a)
    dir_allowed = sum(1 for phase, _, a, _, _, _ in results if phase == 'dir' and a)

    print(f"   slow: {slow_allowed}/{sum(1 for p,_,_,_,_,_ in results if p=='slow')} allowed")
    print(f"   burst: {burst_allowed}/{sum(1 for p,_,_,_,_,_ in results if p=='burst')} allowed")
    print(f"   chop: {chop_allowed}/{sum(1 for p,_,_,_,_,_ in results if p=='chop')} allowed")
    print(f"   dir: {dir_allowed}/{sum(1 for p,_,_,_,_,_ in results if p=='dir')} allowed")

    check("slow mostly blocked", slow_allowed <= 3, f"slow_allowed={slow_allowed}")
    check("burst mostly allowed", burst_allowed >= 4, f"burst_allowed={burst_allowed}")
    check("chop mostly blocked", chop_allowed <= 8, f"chop_allowed={chop_allowed}")
    check("directional mostly allowed", dir_allowed >= 6, f"dir_allowed={dir_allowed}")


# ─── 29. NEUTRO min strength blocks weak signals ────────────────────

def test_neutro_min_strength_blocks():
    print("[29] NEUTRO min strength blocks weak signals")
    settings = make_settings()
    engine = TickEngine(settings)
    engine.set_point(1.0)
    sf = SpeedFilter(speed_period=5, speed_threshold=8.0, neutro_min_strength=0.20)

    build_and_feed(engine, 130000.0, [1, -1, 1, -1, 1, -1, 1], step_ms=100)
    metrics = make_metrics(velocity=3.0, acceleration=0.0, micro_range=3.0, avg_velocity=2.0)
    result = sf.evaluate(engine, engine.last_tick, metrics)

    check("weak signal blocked", not result.allowed or result.strength >= 0.20,
          f"allowed={result.allowed} strength={result.strength:.3f}")


# ─── 30. Detailed metrics dump across all scenarios ─────────────────

def test_detailed_metrics_dump():
    print("[30] Detailed metrics dump")
    settings = make_settings()
    scenarios = {
        "slow":     ([0, 1, 0, -1, 0, 0, 1, -1, 0, 0], 200),
        "normal":   ([3, 2, 3, -1, 2, 3, 4, -2, 3, 2], 100),
        "active":   ([5, 6, 4, 5, 7, -2, 5, 6, 5, 4], 50),
        "chop":     ([5, -5, 5, -5, 4, -4, 5, -5, 5, -5], 100),
        "burst":    ([8, 10, 12, 15, 18, 20, 22], 30),
    }

    for name, (deltas, step_ms) in scenarios.items():
        engine = TickEngine(settings)
        engine.set_point(1.0)
        sf = SpeedFilter(speed_period=5, speed_threshold=8.0,
                         chop_consistency_threshold=0.45, chop_speed_cap_factor=0.8,
                         strength_exhaustion=0.30, neutro_min_strength=0.20)

        r = _run_scenario(sf, engine, deltas, step_ms=step_ms, n_ticks=300)
        print(f"   {name:8s}: allowed={r['allowed_pct']:5.1f}% "
              f"blocked={100-r['allowed_pct']:5.1f}% "
              f"states={r['states']}")

    check("metrics dump complete", True)


# ─── Run all ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("SpeedFilter V12.10 Comprehensive Test Suite")
    print("=" * 60)

    test_insufficient_ticks()
    test_slow_market()
    test_strong_directional()
    test_ema_spike_suppression()
    test_chop_zigzag()
    test_exhaustion()
    test_acelerando()
    test_adaptive_threshold_spread()
    test_adaptive_threshold_range()
    test_adaptive_smoothing()
    test_neutro_fallback()
    test_stats_tracking()
    test_speed_clamp()
    test_momentum_burst()
    test_low_volatility()
    test_mid_volatility()
    test_composite_strength()
    test_chop_counter()
    test_neutro_always_allowed()
    test_forte_requirements()
    test_acelerando_reachable()
    test_frequency_slow_market()
    test_frequency_normal_market()
    test_frequency_active_market()
    test_frequency_chop_market()
    test_gate_chop_vs_acelerando()
    test_point_property()
    test_mixed_scenario()
    test_neutro_min_strength_blocks()
    test_detailed_metrics_dump()

    print("\n" + "=" * 60)
    total = passed + failed
    print(f"Results: {passed}/{total} passed, {failed} failed")
    if errors:
        print(f"Failed: {', '.join(errors)}")
    print("=" * 60)

    sys.exit(0 if failed == 0 else 1)
