import time as _time
import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)

from strategies.momentum_burst import MomentumBurst
from core.utils import TickData, TickMetrics, SignalType, OrderSide
from config.settings import Settings

import logging
logging.disable(logging.CRITICAL)


def make_settings(**overrides) -> Settings:
    s = Settings()
    s.hft.enabled = True
    s.signal.hft_min_displacement_pts = 1.0
    s.position.post_close_cooldown_s = 0.3
    s.signal.hft_cooldown_ms = 50
    s.signal.hft_max_spread_ticks = 10
    s.signal.hft_min_micro_range = 2.0
    s.signal.hft_acceleration_gate = False
    s.hft.idle_timeout_ms = 999999
    s.hft.adaptive_velocity_low = 0.0
    s.hft.adaptive_velocity_mid = 100.0
    s.hft.adaptive_threshold_low = 5.0
    s.hft.adaptive_threshold_mid = 7.0
    s.hft.adaptive_threshold_high = 10.0
    s.tick.velocity_window_ms = 1000
    s.tick.min_ticks_for_signal = 1
    s.risk.max_latency_ms = 9999.0
    for k, v in overrides.items():
        if hasattr(s.reentry, k):
            setattr(s.reentry, k, v)
        elif hasattr(s.position, k):
            setattr(s.position, k, v)
        elif hasattr(s.signal, k):
            setattr(s.signal, k, v)
        elif hasattr(s.hft, k):
            setattr(s.hft, k, v)
    return s


def make_tick(bid: float = 177000.0, ask: float = 177005.0) -> TickData:
    return TickData(bid=bid, ask=ask, last=bid, volume=100, time_ms=int(_time.time() * 1000), spread=ask - bid, mid=(bid + ask) / 2)


def make_metrics(
    velocity: float = 0.0,
    velocity_fast: float = 0.0,
    acceleration: float = 0.0,
    net_displacement: float = 0.0,
    micro_range: float = 10.0,
    avg_velocity: float = 10.0,
    trend_bars: int = 1,
    is_valid: bool = True,
) -> TickMetrics:
    return TickMetrics(
        velocity=velocity,
        velocity_fast=velocity_fast,
        velocity_very_fast=velocity_fast,
        acceleration=acceleration,
        delta=0.0,
        micro_range=micro_range,
        spread=0.0,
        tick_count=50,
        avg_velocity=avg_velocity,
        trend_bars=trend_bars,
        net_displacement=net_displacement,
        is_valid=is_valid,
    )


def feed_bearish_candles(mb: MomentumBurst, base_price: float, n: int = 3, ticks_per: int = 15) -> None:
    for ci in range(n):
        start = base_price - ci * 25
        for ti in range(ticks_per):
            price = start - ti * 2.5
            t = make_tick(bid=price - 2.5, ask=price + 2.5)
            mb.on_tick(t)


def feed_bullish_candles(mb: MomentumBurst, base_price: float, n: int = 3, ticks_per: int = 15) -> None:
    for ci in range(n):
        start = base_price + ci * 25
        for ti in range(ticks_per):
            price = start + ti * 2.5
            t = make_tick(bid=price - 2.5, ask=price + 2.5)
            mb.on_tick(t)


def _init_strategy(s):
    mb = MomentumBurst(s)
    mb.set_instrument_info(5.0, 0)
    mb.set_point(5.0)
    return mb


def test_echo_blocked_no_retrace_no_breakout():
    s = make_settings()
    mb = _init_strategy(s)

    close_price = 177002.5
    mb.set_position_side(OrderSide.BUY)
    mb.notify_close_pnl(-10.0)
    mb.set_position_side(None, close_price=close_price)
    _time.sleep(0.4)

    tick = make_tick(bid=close_price - 5.0, ask=close_price + 5.0)
    metrics = make_metrics(velocity_fast=4.0, net_displacement=2.0, acceleration=0.0, micro_range=10.0)
    signal = mb.evaluate(tick, metrics)

    assert signal.signal_type == SignalType.NONE, f"Expected NONE for echo (no retrace, no breakout), got {signal.signal_type}"


def test_pullback_allowed_after_loss():
    s = make_settings(threshold_base=0.35)
    mb = _init_strategy(s)

    close_price = 177002.5
    mb.set_position_side(OrderSide.BUY)
    mb.notify_close_pnl(-10.0)
    mb.set_position_side(None, close_price=close_price)
    _time.sleep(0.4)

    for ci in range(2):
        start = close_price - 50 + ci * 25
        for ti in range(15):
            price = start - ti * 2.5
            mb.on_tick(make_tick(bid=price - 2.5, ask=price + 2.5))
    start = close_price - 25
    for ti in range(15):
        price = start + ti * 2.5
        mb.on_tick(make_tick(bid=price - 2.5, ask=price + 2.5))

    tick = make_tick(bid=close_price - 40.0, ask=close_price - 30.0)
    metrics = make_metrics(velocity_fast=10.0, net_displacement=8.0, acceleration=3.0, micro_range=10.0)
    signal = mb.evaluate(tick, metrics)

    assert signal.signal_type == SignalType.BUY, f"Expected BUY for pullback reentry after loss, got {signal.signal_type}"


def test_reentry_allowed_after_win():
    s = make_settings()
    mb = _init_strategy(s)

    close_price = 177002.5
    mb.set_position_side(OrderSide.BUY)
    mb.notify_close_pnl(5.0)
    mb.set_position_side(None, close_price=close_price)
    _time.sleep(0.4)

    tick = make_tick()
    metrics = make_metrics(velocity_fast=8.0, net_displacement=5.0, acceleration=5.0, micro_range=10.0)
    signal = mb.evaluate(tick, metrics)

    assert signal.signal_type == SignalType.BUY, f"Expected BUY for same-side after WIN (no reentry gate), got {signal.signal_type}"


def test_flip_after_loss_no_gate():
    s = make_settings()
    mb = _init_strategy(s)

    close_price = 177002.5
    mb.set_position_side(OrderSide.BUY)
    mb.notify_close_pnl(-10.0)
    mb.set_position_side(None, close_price=close_price)
    _time.sleep(0.4)

    tick = make_tick()
    metrics = make_metrics(velocity_fast=-8.0, net_displacement=-5.0, acceleration=-5.0, micro_range=10.0)
    signal = mb.evaluate(tick, metrics)

    assert signal.signal_type == SignalType.SELL, f"Expected SELL for flip after loss (no reentry gate), got {signal.signal_type}"


def test_reentry_disabled_when_engine_disabled():
    s = make_settings(enabled=False)
    mb = _init_strategy(s)

    close_price = 177002.5
    mb.set_position_side(OrderSide.BUY)
    mb.notify_close_pnl(-10.0)
    mb.set_position_side(None, close_price=close_price)
    _time.sleep(0.4)

    tick = make_tick()
    metrics = make_metrics(velocity_fast=8.0, net_displacement=5.0, acceleration=5.0, micro_range=10.0)
    signal = mb.evaluate(tick, metrics)

    assert signal.signal_type == SignalType.BUY, f"Expected BUY when reentry engine disabled, got {signal.signal_type}"


def test_sell_side_echo_blocked():
    s = make_settings()
    mb = _init_strategy(s)

    close_price = 177002.5
    mb.set_position_side(OrderSide.SELL)
    mb.notify_close_pnl(-10.0)
    mb.set_position_side(None, close_price=close_price)
    _time.sleep(0.4)

    tick = make_tick(bid=close_price - 5.0, ask=close_price + 5.0)
    metrics = make_metrics(velocity_fast=-4.0, net_displacement=-2.0, acceleration=0.0, micro_range=10.0)
    signal = mb.evaluate(tick, metrics)

    assert signal.signal_type == SignalType.NONE, f"Expected NONE for SELL-side echo, got {signal.signal_type}"


def test_sell_side_pullback_allowed():
    s = make_settings(threshold_base=0.35)
    mb = _init_strategy(s)

    close_price = 177002.5
    mb.set_position_side(OrderSide.SELL)
    mb.notify_close_pnl(-10.0)
    mb.set_position_side(None, close_price=close_price)
    _time.sleep(0.4)

    for ci in range(2):
        start = close_price + 50 - ci * 25
        for ti in range(15):
            price = start + ti * 2.5
            mb.on_tick(make_tick(bid=price - 2.5, ask=price + 2.5))
    start = close_price + 25
    for ti in range(15):
        price = start - ti * 2.5
        mb.on_tick(make_tick(bid=price - 2.5, ask=price + 2.5))

    tick = make_tick(bid=close_price + 30.0, ask=close_price + 40.0)
    metrics = make_metrics(velocity_fast=-10.0, net_displacement=-8.0, acceleration=-3.0, micro_range=10.0)
    signal = mb.evaluate(tick, metrics)

    assert signal.signal_type == SignalType.SELL, f"Expected SELL for pullback SELL reentry, got {signal.signal_type}"


def test_no_close_history_no_gate():
    s = make_settings()
    mb = _init_strategy(s)

    tick = make_tick()
    metrics = make_metrics(velocity_fast=8.0, net_displacement=5.0, acceleration=5.0, micro_range=10.0)
    signal = mb.evaluate(tick, metrics)

    assert signal.signal_type == SignalType.BUY, f"Expected BUY for first trade (no close history), got {signal.signal_type}"


if __name__ == "__main__":
    tests = [
        test_echo_blocked_no_retrace_no_breakout,
        test_pullback_allowed_after_loss,
        test_reentry_allowed_after_win,
        test_flip_after_loss_no_gate,
        test_reentry_disabled_when_engine_disabled,
        test_sell_side_echo_blocked,
        test_sell_side_pullback_allowed,
        test_no_close_history_no_gate,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS: {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL: {t.__name__} -- {e}")
            failed += 1
        except Exception as e:
            print(f"ERROR: {t.__name__} -- {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed out of {len(tests)}")
