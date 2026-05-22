import os
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from core.logger import Log
from core.utils import TickData, TickMetrics
from core.tick_engine import TickEngine


class SpeedState(Enum):
    LENTO = auto()
    NEUTRO = auto()
    ACELERANDO = auto()
    FORTE = auto()
    EXAUSTAO = auto()


@dataclass(slots=True)
class SpeedResult:
    state: SpeedState = SpeedState.NEUTRO
    speed: float = 0.0
    strength: float = 0.0
    directional_consistency: float = 0.0
    accel: float = 0.0
    adaptive_threshold: float = 0.0
    allowed: bool = True
    blocked_reason: str = ""
    reject_class: str = ""


@dataclass
class SpeedFilterStats:
    total_evaluations: int = 0
    signals_before_filter: int = 0
    signals_after_filter: int = 0
    blocked_lento: int = 0
    blocked_exhaustao: int = 0
    blocked_chop: int = 0
    allowed_neutro: int = 0
    allowed_acelerando: int = 0
    allowed_forte: int = 0

    @property
    def filter_rejection_rate(self) -> float:
        if self.total_evaluations == 0:
            return 0.0
        blocked = self.blocked_lento + self.blocked_exhaustao + self.blocked_chop
        return blocked / self.total_evaluations


class SpeedFilter:
    def __init__(self, speed_period: int = 5, speed_threshold: float = 8.0,
                 strength_exhaustion: float = 0.30, micro_range_window: int = 30,
                 ema_alpha: float = 0.4, speed_clamp: float = 80.0,
                 chop_consistency_threshold: float = 0.45,
                 chop_speed_cap_factor: float = 0.8,
                 neutro_min_strength: float = 0.20,
                 speed_window_ms: int = 500) -> None:
        self._speed_period = speed_period
        self._speed_window_ms = max(50, speed_window_ms)
        self._speed_threshold = speed_threshold
        self._strength_exhaustion = strength_exhaustion
        self._micro_range_window = micro_range_window
        self._ema_alpha = ema_alpha
        self._speed_clamp = speed_clamp
        self._chop_consistency_threshold = chop_consistency_threshold
        self._chop_speed_cap_factor = chop_speed_cap_factor
        self._neutro_min_strength = neutro_min_strength
        self._log = Log.get("speed_filter")
        self._last_result: Optional[SpeedResult] = None
        self._stats = SpeedFilterStats()
        self._last_log_time: float = 0.0
        self._log_interval: float = 10.0
        self._smoothed_speed: float = 0.0
        self._has_previous_speed: bool = False
        self._prev_adaptive_threshold: float = speed_threshold
        self._debug_enabled: bool = os.environ.get("HFT_SPEED_DEBUG", "").strip() in (
            "1", "true", "yes",
        )
        self._debug_count: int = 0
        self._debug_max: int = int(os.environ.get("HFT_SPEED_DEBUG_MAX", "500"))
        self._debug_path: str = os.environ.get(
            "HFT_SPEED_DEBUG_PATH",
            os.path.join("logs", "speed_debug.log"),
        )

    def _write_speed_debug(
        self,
        *,
        price_start: float,
        price_end: float,
        price_span: float,
        point: float,
        elapsed_ms: int,
        elapsed_s: float,
        raw_speed: float,
        ema_speed: float,
        adaptive_threshold: float,
        adaptive_raw: float,
        spread: float,
        spread_mult: float,
        micro_range: float,
        range_mult: float,
        avg_velocity: float,
        vel_mult: float,
        directional_consistency: float,
        accel: float,
        strength: float,
        state: str,
        allowed: bool,
        block_reason: str,
        n_ticks: int,
        reject_class: str = "",
        path_pts: float = 0.0,
        velocity_fast: float = 0.0,
        speed_window_ms: int = 0,
    ) -> None:
        if not self._debug_enabled or self._debug_count >= self._debug_max:
            return
        self._debug_count += 1
        os.makedirs(os.path.dirname(self._debug_path) or ".", exist_ok=True)
        lines = [
            "[SPEED DEBUG]",
            f"price_start={price_start}",
            f"price_end={price_end}",
            f"price_span={price_span}",
            f"price_span_pts={price_span / point if point > 0 else 0.0}",
            f"elapsed_ms={elapsed_ms}",
            f"elapsed_s={elapsed_s:.6f}",
            f"raw_speed={raw_speed:.6f}",
            f"ema_speed={ema_speed:.6f}",
            f"adaptive_threshold={adaptive_threshold:.6f}",
            f"adaptive_threshold_raw={adaptive_raw:.6f}",
            f"speed_threshold_base={self._speed_threshold}",
            f"speed_window_ms={speed_window_ms}",
            f"path_pts={path_pts}",
            f"velocity_fast={velocity_fast}",
            f"reject_class={reject_class}",
            f"spread={spread}",
            f"spread_mult={spread_mult}",
            f"micro_range={micro_range}",
            f"range_mult={range_mult}",
            f"avg_velocity={avg_velocity}",
            f"vel_mult={vel_mult}",
            f"directional_consistency={directional_consistency:.6f}",
            f"accel={accel:.6f}",
            f"strength={strength:.6f}",
            f"state={state}",
            f"allowed={allowed}",
            f"block_reason={block_reason}",
            f"n_ticks_window={n_ticks}",
            f"lento_gate_speed_lt={adaptive_threshold * 0.5:.6f}",
            "",
        ]
        with open(self._debug_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def _compute_speed_metrics(
        self, tick_engine: TickEngine, metrics: TickMetrics, point: float,
    ) -> dict:
        """
        Velocidade por caminho na janela temporal (pts/s), alinhada ao TickEngine.
        Usa path sum(|Δmid|), não só |mid_end-mid_start| (evita zero em zigzag).
        """
        window_ticks = tick_engine.get_ticks_in_window(self._speed_window_ms)
        n = len(window_ticks)
        empty = {
            "raw_speed": 0.0,
            "price_span_pts": 0.0,
            "path_pts": 0.0,
            "elapsed_ms": 0,
            "elapsed_s": 0.001,
            "price_start": 0.0,
            "price_end": 0.0,
            "n_ticks": n,
            "past_tick_ms": 0,
            "current_tick_ms": 0,
            "elapsed_source": "none",
        }
        if n < 2:
            return empty

        current = window_ticks[-1]
        past = window_ticks[0]

        elapsed_ms = current.time_ms - past.time_ms
        elapsed_source = "tick_time_ms"

        if elapsed_ms <= 0:
            recv_ms = int((current.timestamp - past.timestamp) * 1000.0)
            if recv_ms > 0:
                elapsed_ms = recv_ms
                elapsed_source = "recv_timestamp"
            else:
                elapsed_ms = 1
                elapsed_source = "min_1ms_fallback"

        elapsed_s = max(elapsed_ms, 1) / 1000.0

        path_pts = 0.0
        prev_mid = past.mid
        started = False
        for t in window_ticks:
            if t.time_ms < past.time_ms:
                continue
            if t.time_ms > current.time_ms:
                break
            if not started:
                started = True
                prev_mid = t.mid
                continue
            path_pts += abs(t.mid - prev_mid)
            prev_mid = t.mid

        price_span_pts = abs(current.mid - past.mid) / point if point > 0 else 0.0
        path_pts_norm = path_pts / point if point > 0 else 0.0
        raw_speed = path_pts_norm / elapsed_s

        return {
            "raw_speed": raw_speed,
            "price_span_pts": price_span_pts,
            "path_pts": path_pts_norm,
            "elapsed_ms": elapsed_ms,
            "elapsed_s": elapsed_s,
            "price_start": past.mid,
            "price_end": current.mid,
            "n_ticks": n,
            "past_tick_ms": past.time_ms,
            "current_tick_ms": current.time_ms,
            "elapsed_source": elapsed_source,
        }

    def _classify_block(
        self, state: SpeedState, allowed: bool, blocked_reason: str,
        speed: float, adaptive_threshold: float, strength: float,
        directional_consistency: float, accel: float,
        speed_metrics: dict,
    ) -> str:
        if allowed:
            return "allowed"
        if state == SpeedState.EXAUSTAO:
            return "exhaustion"
        if "chop:" in blocked_reason:
            return "chop"
        path_pts = speed_metrics.get("path_pts", 0.0)
        span_pts = speed_metrics.get("price_span_pts", 0.0)
        if path_pts >= 4.0 and span_pts < path_pts * 0.35:
            return "chop"
        if speed_metrics.get("price_span_pts", 0.0) == 0.0 and speed_metrics.get("path_pts", 0.0) == 0.0:
            return "lento_price_span_zero"
        if speed_metrics.get("elapsed_ms", 0) <= 0 or speed_metrics.get("elapsed_source") == "min_1ms_fallback":
            return "lento_elapsed"
        if speed < adaptive_threshold * 0.5:
            return "lento_speed"
        if "weak:" in blocked_reason:
            return "threshold_fail"
        if "slow+chop" in blocked_reason:
            return "consistency_fail"
        return "lento_speed"

    def evaluate(self, tick_engine: TickEngine, tick: TickData,
                 metrics: TickMetrics) -> SpeedResult:
        self._stats.total_evaluations += 1
        self._stats.signals_before_filter += 1

        point = tick_engine.point if tick_engine.point > 0 else 1.0
        window_ticks = tick_engine.get_ticks_in_window(self._speed_window_ms)
        n = len(window_ticks)
        min_ticks_required = max(self._speed_period + 1, 2)

        if tick_engine.tick_count < min_ticks_required or n < 2:
            result = SpeedResult(
                state=SpeedState.NEUTRO,
                speed=0.0,
                strength=0.0,
                directional_consistency=0.0,
                accel=0.0,
                adaptive_threshold=self._speed_threshold,
                allowed=True,
                blocked_reason="",
                reject_class="warmup",
            )
            self._last_result = result
            self._stats.signals_after_filter += 1
            self._stats.allowed_neutro += 1
            return result

        speed_metrics = self._compute_speed_metrics(tick_engine, metrics, point)
        raw_speed = speed_metrics["raw_speed"]
        price_span = abs(speed_metrics["price_end"] - speed_metrics["price_start"])
        time_elapsed_s = speed_metrics["elapsed_s"]
        current = window_ticks[-1]
        past_ms = speed_metrics["past_tick_ms"]
        past_mid = speed_metrics["price_start"]

        if not self._has_previous_speed:
            self._smoothed_speed = raw_speed
            self._has_previous_speed = True
        else:
            self._smoothed_speed = (self._ema_alpha * raw_speed +
                                    (1.0 - self._ema_alpha) * self._smoothed_speed)

        speed = min(self._smoothed_speed, self._speed_clamp)

        recent_window = tick_engine.get_recent_ticks(self._micro_range_window)
        if len(recent_window) >= 2:
            highs = [t.ask for t in recent_window]
            lows = [t.bid for t in recent_window]
            true_range = max(highs) - min(lows)
            true_range_pts = true_range / point if point > 0 else 0.0
        else:
            true_range_pts = metrics.micro_range if metrics.micro_range > 0 else 1.0

        if len(recent_window) >= 2:
            mid_prices = [t.mid for t in recent_window]
        else:
            mid_prices = [past_mid, current.mid]

        same_dir = 0
        total_dir = 0
        for i in range(1, len(mid_prices)):
            d = mid_prices[i] - mid_prices[i - 1]
            if d != 0.0:
                total_dir += 1
                if (d > 0 and current.mid >= past_mid) or (d < 0 and current.mid < past_mid):
                    same_dir += 1
        directional_consistency = same_dir / total_dir if total_dir > 0 else 0.0

        direction = current.mid - past_mid
        if true_range_pts > 0:
            if direction >= 0:
                directional_range = max(1.0, (max(highs) - past_mid) / point) if len(recent_window) >= 2 else true_range_pts
            else:
                directional_range = max(1.0, (past_mid - min(lows)) / point) if len(recent_window) >= 2 else true_range_pts
            range_strength = abs(price_span / point) / directional_range if point > 0 else 0.0
        else:
            range_strength = 0.0

        range_strength = min(range_strength, 2.0)

        accel = metrics.acceleration
        normalized_accel = min(max(accel / 10.0, 0.0), 1.0)
        strength = (range_strength * 0.4 +
                    directional_consistency * 0.35 +
                    normalized_accel * 0.25)
        strength = min(strength, 1.5)

        adaptive_raw = self._calc_adaptive_threshold(metrics, tick)
        adaptive_threshold = (self._prev_adaptive_threshold * 0.7 +
                              adaptive_raw * 0.3)
        self._prev_adaptive_threshold = adaptive_threshold

        path_pts = speed_metrics.get("path_pts", 0.0)
        price_span_pts = speed_metrics.get("price_span_pts", 0.0)
        path_efficiency = (
            price_span_pts / path_pts if path_pts > 1e-9 else 1.0
        )
        path_chop = path_pts >= 4.0 and path_efficiency < 0.35

        state = SpeedState.NEUTRO
        allowed = True
        blocked_reason = ""

        if speed < adaptive_threshold * 0.5:
            state = SpeedState.LENTO
            allowed = False
            blocked_reason = f"speed={speed:.1f}<{adaptive_threshold * 0.5:.1f}"
            self._stats.blocked_lento += 1
        elif (speed >= adaptive_threshold and
              strength > 0.45 and
              directional_consistency > 0.5 and
              accel > 0 and
              not path_chop):
            state = SpeedState.FORTE
            self._stats.allowed_forte += 1
        elif (speed >= adaptive_threshold * 0.65 and
              directional_consistency > 0.55):
            if (path_chop or
                    (directional_consistency < self._chop_consistency_threshold and
                     speed < adaptive_threshold * self._chop_speed_cap_factor)):
                state = SpeedState.LENTO
                allowed = False
                if path_chop:
                    blocked_reason = (f"chop:path_eff={path_efficiency:.2f}"
                                      f" path={path_pts:.1f} span={price_span_pts:.1f}")
                else:
                    blocked_reason = (f"chop: consistency={directional_consistency:.2f}"
                                      f"<{self._chop_consistency_threshold:.2f}"
                                      f" speed={speed:.1f}<{adaptive_threshold * self._chop_speed_cap_factor:.1f}")
                self._stats.blocked_chop += 1
            else:
                state = SpeedState.ACELERANDO
                self._stats.allowed_acelerando += 1
        elif (speed >= adaptive_threshold * 0.5 and
              accel > 0 and
              directional_consistency >= self._chop_consistency_threshold and
              strength >= self._neutro_min_strength):
            state = SpeedState.NEUTRO
            self._stats.allowed_neutro += 1
        else:
            state = SpeedState.LENTO
            allowed = False
            if strength < self._neutro_min_strength:
                blocked_reason = (f"weak: strength={strength:.3f}"
                                  f"<{self._neutro_min_strength:.2f}"
                                  f" speed={speed:.1f}")
            else:
                blocked_reason = (f"slow+chop: speed={speed:.1f}"
                                  f" consistency={directional_consistency:.2f}"
                                  f" strength={strength:.3f}")
            self._stats.blocked_lento += 1

        if state in (SpeedState.FORTE, SpeedState.ACELERANDO, SpeedState.NEUTRO):
            if (strength < self._strength_exhaustion and
                    speed > adaptive_threshold * 1.3):
                state = SpeedState.EXAUSTAO
                allowed = False
                blocked_reason = (f"exhaustion: speed={speed:.1f}>{adaptive_threshold * 1.3:.1f}"
                                  f" strength={strength:.3f}<{self._strength_exhaustion}"
                                  f" consistency={directional_consistency:.2f}")
                if state == SpeedState.FORTE:
                    self._stats.allowed_forte -= 1
                elif state == SpeedState.ACELERANDO:
                    self._stats.allowed_acelerando -= 1
                else:
                    self._stats.allowed_neutro -= 1
                self._stats.blocked_exhaustao += 1

        if allowed:
            self._stats.signals_after_filter += 1

        reject_class = self._classify_block(
            state, allowed, blocked_reason, speed, adaptive_threshold,
            strength, directional_consistency, accel, speed_metrics,
        )

        result = SpeedResult(
            state=state,
            speed=speed,
            strength=strength,
            directional_consistency=directional_consistency,
            accel=accel,
            adaptive_threshold=adaptive_threshold,
            allowed=allowed,
            blocked_reason=blocked_reason,
            reject_class=reject_class,
        )
        self._last_result = result

        self._write_speed_debug(
            price_start=past_mid,
            price_end=current.mid,
            price_span=price_span,
            point=point,
            elapsed_ms=int(speed_metrics["elapsed_ms"]),
            elapsed_s=time_elapsed_s,
            raw_speed=raw_speed,
            ema_speed=speed,
            adaptive_threshold=adaptive_threshold,
            adaptive_raw=adaptive_raw,
            spread=tick.spread,
            spread_mult=(
                1.25 if tick.spread > 8.0 else 1.10 if tick.spread > 5.0 else 1.0
            ),
            micro_range=metrics.micro_range,
            range_mult=(
                1.30 if metrics.micro_range < 3.0 else
                1.10 if metrics.micro_range < 6.0 else
                0.80 if metrics.micro_range > 20.0 else
                0.90 if metrics.micro_range > 12.0 else 1.0
            ),
            avg_velocity=metrics.avg_velocity,
            vel_mult=(
                1.15 if abs(metrics.avg_velocity) < 3.0 else
                0.85 if abs(metrics.avg_velocity) > 15.0 else 1.0
            ),
            directional_consistency=directional_consistency,
            accel=accel,
            strength=strength,
            state=state.name,
            allowed=allowed,
            block_reason=blocked_reason,
            n_ticks=n,
            reject_class=reject_class,
            path_pts=speed_metrics.get("path_pts", 0.0),
            velocity_fast=metrics.velocity_fast,
            speed_window_ms=self._speed_window_ms,
        )

        now = time.time()
        if now - self._last_log_time >= self._log_interval:
            self._last_log_time = now
            self._log.info(
                "[SPEED FILTER] estado=%s speed=%.1f strength=%.3f "
                "dir_consistency=%.2f accel=%.1f allowed=%s reason=%s | "
                "stats: eval=%d reject=%.1f%% lento=%d exhaust=%d chop=%d "
                "neutro=%d acel=%d forte=%d",
                state.name, speed, strength, directional_consistency,
                accel, allowed, blocked_reason,
                self._stats.total_evaluations,
                self._stats.filter_rejection_rate * 100.0,
                self._stats.blocked_lento,
                self._stats.blocked_exhaustao,
                self._stats.blocked_chop,
                self._stats.allowed_neutro,
                self._stats.allowed_acelerando,
                self._stats.allowed_forte,
            )

        return result

    def _calc_adaptive_threshold(self, metrics: TickMetrics,
                                 tick: TickData) -> float:
        base = self._speed_threshold

        spread = tick.spread
        if spread > 8.0:
            spread_mult = 1.25
        elif spread > 5.0:
            spread_mult = 1.10
        else:
            spread_mult = 1.0

        micro_range = metrics.micro_range
        if micro_range < 3.0:
            range_mult = 1.30
        elif micro_range < 6.0:
            range_mult = 1.10
        elif micro_range > 20.0:
            range_mult = 0.80
        elif micro_range > 12.0:
            range_mult = 0.90
        else:
            range_mult = 1.0

        avg_vel = abs(metrics.avg_velocity) if hasattr(metrics, 'avg_velocity') else 0.0
        if avg_vel < 3.0:
            vel_mult = 1.15
        elif avg_vel > 15.0:
            vel_mult = 0.85
        else:
            vel_mult = 1.0

        return base * spread_mult * range_mult * vel_mult

    @property
    def last_result(self) -> Optional[SpeedResult]:
        return self._last_result

    @property
    def stats(self) -> SpeedFilterStats:
        return self._stats

    def get_metrics_summary(self) -> dict:
        s = self._stats
        return {
            "total_evaluations": s.total_evaluations,
            "signals_before_filter": s.signals_before_filter,
            "signals_after_filter": s.signals_after_filter,
            "filter_rejection_rate": f"{s.filter_rejection_rate * 100.0:.1f}%",
            "blocked_lento": s.blocked_lento,
            "blocked_exhaustao": s.blocked_exhaustao,
            "blocked_chop": s.blocked_chop,
            "allowed_neutro": s.allowed_neutro,
            "allowed_acelerando": s.allowed_acelerando,
            "allowed_forte": s.allowed_forte,
        }
