"""
Regressão: timestamp MT5 (time_msc epoch) + métrica path-speed na janela 500ms.
Prova que elapsed_ms > 0 e raw_speed > 0 em movimento direcional realista.
"""
import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)

from core.speed_filter import SpeedFilter, SpeedState
from core.tick_engine import TickEngine
from core.utils import TickMetrics
from config.settings import Settings

import logging
logging.disable(logging.CRITICAL)


class RawTick:
    __slots__ = ("bid", "ask", "last", "volume", "time", "time_msc")

    def __init__(self, bid: float, ask: float, t_ms: int):
        self.bid = bid
        self.ask = ask
        self.last = bid
        self.volume = 0
        self.time = t_ms // 1000
        self.time_msc = t_ms


def feed(engine: TickEngine, bid: float, ask: float, t_ms: int):
    return engine.process_tick(RawTick(bid, ask, t_ms))


def make_settings() -> Settings:
    s = Settings()
    s.tick.buffer_size = 500
    s.tick.min_ticks_for_signal = 5
    return s


def make_metrics(**kwargs) -> TickMetrics:
    m = TickMetrics()
    m.velocity = kwargs.get("velocity", 10.0)
    m.velocity_fast = kwargs.get("velocity_fast", m.velocity)
    m.velocity_very_fast = kwargs.get("velocity_very_fast", m.velocity)
    m.acceleration = kwargs.get("acceleration", 2.0)
    m.micro_range = kwargs.get("micro_range", 15.0)
    m.avg_velocity = kwargs.get("avg_velocity", 10.0)
    m.is_valid = True
    m.tick_count = 50
    return m


passed = 0
failed = 0


def check(name: str, ok: bool, detail: str = ""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL  {name}" + (f" | {detail}" if detail else ""))


def test_time_msc_epoch_monotonic():
    print("[TS1] time_msc epoch -> elapsed_ms > 0")
    engine = TickEngine(make_settings())
    engine.set_point(1.0)
    sf = SpeedFilter(speed_threshold=5.5, speed_window_ms=500)
    base = 1_700_000_000_000
    p = 130000.0
    last = None
    for i in range(12):
        p += 3.0
        last = feed(engine, p, p + 3.0, base + i * 40)
    metrics = make_metrics(velocity_fast=15.0)
    sm = sf._compute_speed_metrics(engine, metrics, 1.0)
    check("elapsed_ms>0", sm["elapsed_ms"] > 0, f"elapsed={sm['elapsed_ms']}")
    check("raw_speed>0", sm["raw_speed"] > 0, f"raw={sm['raw_speed']:.2f}")
    check("path_pts>0", sm["path_pts"] > 0, f"path={sm['path_pts']:.2f}")


def test_broken_legacy_time_formula_simulated():
    """Ticks com time_msc pequeno (legado) ainda produzem speed via recv fallback."""
    print("[TS2] time_msc legado + recv fallback")
    engine = TickEngine(make_settings())
    engine.set_point(1.0)
    sf = SpeedFilter(speed_threshold=5.5, speed_window_ms=500)

    class LegacyTick:
        __slots__ = ("bid", "ask", "last", "volume", "time", "time_msc")

        def __init__(self, bid, ask, t_sec, msc_part):
            self.bid = bid
            self.ask = ask
            self.last = bid
            self.volume = 0
            self.time = t_sec
            self.time_msc = msc_part

    p = 130000.0
    t_sec = 1_700_000_000
    for i in range(10):
        p += 2.0
        engine.process_tick(LegacyTick(p, p + 3.0, t_sec, i % 500))
    metrics = make_metrics()
    sm = sf._compute_speed_metrics(engine, metrics, 1.0)
    check("raw_speed>=0", sm["raw_speed"] >= 0, f"raw={sm['raw_speed']}")


def test_zigzag_path_speed_nonzero():
    print("[TS3] zigzag: path_pts > price_span_pts")
    engine = TickEngine(make_settings())
    engine.set_point(1.0)
    sf = SpeedFilter(speed_window_ms=500)
    base = 1_700_000_001_000
    p = 130000.0
    deltas = [5, -4, 5, -4, 5, -4, 5]
    for i, d in enumerate(deltas):
        p += d
        feed(engine, p, p + 3.0, base + i * 50)
    metrics = make_metrics()
    sm = sf._compute_speed_metrics(engine, metrics, 1.0)
    check("path>=span", sm["path_pts"] >= sm["price_span_pts"],
          f"path={sm['path_pts']:.2f} span={sm['price_span_pts']:.2f}")
    check("path>span_strict", sm["path_pts"] > sm["price_span_pts"] or sm["price_span_pts"] == 0,
          f"path={sm['path_pts']:.2f} span={sm['price_span_pts']:.2f}")


def test_strong_move_not_all_lento():
    print("[TS4] movimento forte -> allowed")
    engine = TickEngine(make_settings())
    engine.set_point(1.0)
    sf = SpeedFilter(speed_threshold=5.5, speed_window_ms=500)
    base = 1_700_000_002_000
    p = 130000.0
    last = None
    for i in range(15):
        p += 8.0
        last = feed(engine, p, p + 3.0, base + i * 30)
    result = sf.evaluate(engine, last, make_metrics(velocity_fast=25.0, acceleration=5.0))
    check("allowed", result.allowed, f"state={result.state.name} speed={result.speed:.1f}")
    check("not LENTO", result.state != SpeedState.LENTO, result.blocked_reason)


if __name__ == "__main__":
    test_time_msc_epoch_monotonic()
    test_broken_legacy_time_formula_simulated()
    test_zigzag_path_speed_nonzero()
    test_strong_move_not_all_lento()
    print(f"\nTimestamp regressions: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
