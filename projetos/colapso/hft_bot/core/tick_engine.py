import time
import numpy as np
from typing import Optional
from collections import deque

from core.logger import Log
from core.utils import TickData, TickMetrics, CircularBuffer, now_ms
from config.settings import Settings, TickSettings


class TickEngine:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._tick_cfg: TickSettings = settings.tick
        self._log = Log.get("tick")
        self._symbol = settings.trading.symbol

        self._ticks: deque[TickData] = deque(maxlen=self._tick_cfg.buffer_size)
        self._mid_prices: CircularBuffer = CircularBuffer(self._tick_cfg.buffer_size)
        self._velocities: CircularBuffer = CircularBuffer(self._tick_cfg.buffer_size)
        self._displacements: CircularBuffer = CircularBuffer(self._tick_cfg.buffer_size)
        self._last_tick: Optional[TickData] = None
        self._last_metrics: Optional[TickMetrics] = None
        self._tick_count: int = 0
        self._point: float = 1.0

    def set_point(self, point: float) -> None:
        self._point = point
        self._log.debug("Point configurado: %.5f", point)

    def process_tick(self, raw_tick) -> Optional[TickData]:
        if raw_tick is None:
            return None

        tick = self._raw_to_tick(raw_tick)
        if not tick.is_valid:
            return None

        if self._last_tick is not None:
            tick.delta = tick.mid - self._last_tick.mid

        self._ticks.append(tick)
        self._mid_prices.push(tick.mid)
        self._tick_count += 1
        self._last_tick = tick

        return tick

    def compute_metrics(self) -> TickMetrics:
        metrics = TickMetrics()

        if self._tick_count < 2:
            metrics.is_valid = False
            self._last_metrics = metrics
            return metrics

        metrics.spread = self._last_tick.spread if self._last_tick else 0.0
        metrics.tick_count = self._tick_count

        velocity = self._calc_velocity()
        metrics.velocity = velocity

        metrics.velocity_fast = self._calc_velocity_window(500)
        metrics.velocity_very_fast = self._calc_velocity_window(200)

        self._velocities.push(velocity)
        metrics.avg_velocity = self._calc_avg_velocity()

        metrics.acceleration = metrics.velocity_very_fast - metrics.velocity_fast
        metrics.delta = self._last_tick.delta if self._last_tick else 0.0
        metrics.micro_range = self._calc_micro_range()
        metrics.trend_bars = self._calc_trend_bars()

        disp = self._calc_net_displacement()
        metrics.net_displacement = disp
        self._displacements.push(disp)

        metrics.is_valid = self._tick_count >= self._tick_cfg.min_ticks_for_signal

        self._last_metrics = metrics
        return metrics

    def _calc_velocity(self) -> float:
        return self._calc_velocity_window(self._tick_cfg.velocity_window_ms)

    def _calc_velocity_window(self, window_ms: int) -> float:
        if len(self._ticks) < 2:
            return 0.0

        cutoff = (self._ticks[-1].time_ms) - window_ms
        prices = []
        for t in reversed(self._ticks):
            if t.time_ms < cutoff:
                break
            prices.append(t.mid)

        if len(prices) < 2:
            return 0.0

        prices.reverse()
        deltas = np.diff(prices)
        time_span_s = window_ms / 1000.0

        if time_span_s <= 0:
            return 0.0

        speed = float(np.sum(deltas)) / self._point / time_span_s
        return speed

    def _calc_micro_range(self) -> float:
        window = self._tick_cfg.micro_range_window
        if len(self._ticks) < window:
            return 0.0

        recent = list(self._ticks)[-window:]
        highs = [t.ask for t in recent]
        lows = [t.bid for t in recent]

        range_val = (max(highs) - min(lows)) / self._point
        return range_val

    def _calc_avg_velocity(self) -> float:
        if self._velocities.size == 0:
            return 0.0
        vels = self._velocities.to_array()
        return float(np.mean(vels[-20:])) if len(vels) >= 20 else float(np.mean(vels))

    def _calc_net_displacement(self) -> float:
        window_ms = self._tick_cfg.velocity_window_ms
        if len(self._ticks) < 2:
            return 0.0
        cutoff = self._ticks[-1].time_ms - window_ms
        total = 0.0
        for t in reversed(self._ticks):
            if t.time_ms < cutoff:
                break
            total += t.delta
        return total / self._point if self._point > 0 else 0.0

    def _calc_trend_bars(self) -> int:
        if len(self._ticks) < 2:
            return 0
        count = 0
        direction = 0
        zeros_skipped = 0
        for i in range(len(self._ticks) - 1, 0, -1):
            delta = self._ticks[i].mid - self._ticks[i - 1].mid
            if delta == 0:
                zeros_skipped += 1
                if zeros_skipped > 2:
                    break
                continue
            zeros_skipped = 0
            tick_dir = 1 if delta > 0 else -1
            if direction == 0:
                direction = tick_dir
                count = 1
            elif tick_dir == direction:
                count += 1
            else:
                break
        return count

    @staticmethod
    def _raw_to_tick(raw_tick) -> TickData:
        mid = (raw_tick.bid + raw_tick.ask) / 2.0
        spread = raw_tick.ask - raw_tick.bid
        # MT5: time_msc = epoch ms completo. Não usar time*1000 + time_msc%1000 (quebra monotonicidade).
        time_msc = int(getattr(raw_tick, "time_msc", 0) or 0)
        if time_msc > 1_000_000_000_000:
            time_ms = time_msc
        elif time_msc > 0:
            time_ms = int(raw_tick.time * 1000) + (time_msc % 1000)
        else:
            time_ms = int(raw_tick.time * 1000)

        return TickData(
            bid=raw_tick.bid,
            ask=raw_tick.ask,
            last=raw_tick.last if hasattr(raw_tick, "last") else 0.0,
            volume=raw_tick.volume if hasattr(raw_tick, "volume") else 0,
            time_ms=time_ms,
            spread=spread,
            mid=mid,
            delta=0.0,
            timestamp=time.time(),
        )

    def get_recent_ticks(self, count: int = 0) -> list:
        if count <= 0:
            return list(self._ticks)
        return list(self._ticks)[-count:] if len(self._ticks) > 0 else []

    def get_ticks_in_window(self, window_ms: int) -> list:
        """Ticks com time_ms em [now-window_ms, now] (ordem cronológica do deque)."""
        if not self._ticks or window_ms <= 0:
            return list(self._ticks)
        cutoff = self._ticks[-1].time_ms - window_ms
        return [t for t in self._ticks if t.time_ms >= cutoff]

    @property
    def point(self) -> float:
        return self._point

    @property
    def last_tick(self) -> Optional[TickData]:
        return self._last_tick

    @property
    def last_metrics(self) -> Optional[TickMetrics]:
        return self._last_metrics

    @property
    def tick_count(self) -> int:
        return self._tick_count

    def reset(self) -> None:
        self._ticks.clear()
        self._mid_prices.clear()
        self._velocities.clear()
        self._displacements.clear()
        self._last_tick = None
        self._last_metrics = None
        self._tick_count = 0
        self._log.info("TickEngine resetado")
