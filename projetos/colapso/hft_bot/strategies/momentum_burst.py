import time
from typing import Optional

from core.logger import Log
from core.utils import TickData, TickMetrics, Signal, SignalType, OrderSide, CircularBuffer
from core.signal_engine import StrategyBase
from core.micro_structure import MicroStructureEngine, ReentryResult
from config.settings import Settings, SignalSettings, TickSettings, HFTSettings


class MomentumBurst(StrategyBase):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._tick_cfg: TickSettings = settings.tick
        self._hft_cfg: HFTSettings = settings.hft
        self._log = Log.get("signal")
        self._position_side: Optional[OrderSide] = None

        self._recent_highs: CircularBuffer = CircularBuffer(50)
        self._recent_lows: CircularBuffer = CircularBuffer(50)

        self._last_trade_time: float = 0.0
        self._signal_log_counter: int = 0
        self._adaptive_velocity_threshold: float = self._signal_cfg.hft_min_velocity
        self._last_signal_direction: Optional[SignalType] = None
        self._last_signal_price_zone: float = 0.0
        self._last_signal_velocity_regime: str = ""
        self._last_entry_signal_time: float = 0.0
        self._last_risk_block_time: float = 0.0
        self._risk_block_cooldown_s: float = 0.5
        self._signal_dedup_ms: float = 100.0
        self._position_entry_time: float = 0.0
        self._entry_displacement: float = 0.0
        self._last_close_time: float = 0.0
        self._last_close_side: Optional[OrderSide] = None
        self._last_close_pnl: float = 0.0
        self._last_close_price: float = 0.0

        reentry_cfg = settings.reentry
        self._reentry_engine = MicroStructureEngine(
            candle_ticks=reentry_cfg.candle_ticks,
            retrace_score=reentry_cfg.retrace_weight,
            breakout_score=reentry_cfg.breakout_weight,
            structure_score=reentry_cfg.structure_weight,
            consistency_score=reentry_cfg.consistency_weight,
            velocity_score=reentry_cfg.velocity_weight,
            chop_penalty=reentry_cfg.chop_penalty_max,
            spread_penalty=reentry_cfg.spread_penalty_max,
            threshold_base=reentry_cfg.threshold_base,
            echo_proximity_pts=reentry_cfg.echo_proximity_pts,
            freq_target=reentry_cfg.freq_target,
            freq_window_s=reentry_cfg.freq_window_s,
        )
        self._reentry_enabled: bool = reentry_cfg.enabled

    def set_position_side(self, side: Optional[OrderSide], close_price: float = 0.0) -> None:
        if side is not None and self._position_side is None:
            self._position_entry_time = time.time()
            self._position_side = side
            self._last_close_pnl = 0.0
        elif side is None and self._position_side is not None:
            self._position_entry_time = 0.0
            self._entry_displacement = 0.0
            self._last_close_time = time.time()
            self._last_close_side = self._position_side
            self._last_close_price = close_price
            self._position_side = side

    def on_tick(self, tick: TickData) -> None:
        if self._reentry_enabled:
            self._reentry_engine.on_tick(tick)

    def set_point(self, point: float) -> None:
        self._point = point
        self._reentry_engine.set_point(point)

    def notify_close_pnl(self, pnl: float) -> None:
        self._last_close_pnl = pnl
        if self._reentry_enabled:
            self._reentry_engine.notify_outcome(pnl)

    def set_speed_state(self, state_name: str) -> None:
        if self._reentry_enabled:
            self._reentry_engine.set_speed_state(state_name)

    def evaluate(self, tick: TickData, metrics: TickMetrics) -> Signal:
        self._update_range(tick)

        self._update_adaptive_threshold(metrics.avg_velocity)

        self._signal_log_counter += 1
        if self._signal_log_counter % 25 == 0:
            self._log_signal_check(tick, metrics)

        if not self._check_cooldown():
            return Signal(signal_type=SignalType.NONE)

        if self._position_side is not None:
            return self._evaluate_with_position(tick, metrics)

        if self._hft_cfg.enabled:
            signal = self._check_hft_entry(tick, metrics)
            if signal.signal_type != SignalType.NONE:
                return signal

            signal = self._check_idle_fallback(tick, metrics)
            if signal.signal_type != SignalType.NONE:
                return signal

        return self._check_entry(tick, metrics)

    def _update_range(self, tick: TickData) -> None:
        self._recent_highs.push(tick.ask)
        self._recent_lows.push(tick.bid)

    def _update_adaptive_threshold(self, avg_velocity: float) -> None:
        hft_cfg = self._hft_cfg
        if avg_velocity < hft_cfg.adaptive_velocity_low:
            self._adaptive_velocity_threshold = hft_cfg.adaptive_threshold_low
        elif avg_velocity < hft_cfg.adaptive_velocity_mid:
            self._adaptive_velocity_threshold = hft_cfg.adaptive_threshold_mid
        else:
            self._adaptive_velocity_threshold = hft_cfg.adaptive_threshold_high

    def _log_signal_check(self, tick: TickData, metrics: TickMetrics) -> None:
        spread_ticks = tick.spread / self._point if self._point > 0 else 0.0
        self._log.info(
            "[SIGNAL CHECK] vel=%.1f vel_fast=%.1f disp=%.1f acc=%.1f micro_range=%.1f "
            "spread=%.1f trend_bars=%d adaptive_thresh=%.1f decision=%s",
            metrics.velocity,
            metrics.velocity_fast,
            metrics.net_displacement,
            metrics.acceleration,
            metrics.micro_range,
            spread_ticks,
            metrics.trend_bars,
            self._adaptive_velocity_threshold,
            self._position_side.name if self._position_side else "FLAT",
        )



    def _evaluate_with_position(self, tick: TickData, metrics: TickMetrics) -> Signal:
        pos_cfg = self._settings.position
        exit_signal = self._check_exit(tick, metrics)
        if exit_signal is not None:
            return exit_signal

        entry_signal = self._check_hft_entry(tick, metrics)
        if entry_signal.signal_type == SignalType.NONE:
            return entry_signal

        if self._position_entry_time > 0 and (time.time() - self._position_entry_time) < pos_cfg.min_hold_seconds:
            return Signal(signal_type=SignalType.NONE)

        if self._position_side == OrderSide.BUY and entry_signal.signal_type == SignalType.SELL:
            rev_vel_threshold = self._adaptive_velocity_threshold * pos_cfg.reversal_vel_mult
            if abs(metrics.velocity_fast) < rev_vel_threshold:
                self._log.info("[REVERSAL BLOCKED] reason=weak_velocity side=BUY entry=SELL vel_fast=%.1f required=%.1f", metrics.velocity_fast, rev_vel_threshold)
                return Signal(signal_type=SignalType.NONE)
            if abs(metrics.net_displacement) < pos_cfg.loss_min_pts:
                self._log.info("[REVERSAL BLOCKED] reason=below_loss_min side=BUY entry=SELL disp=%.1f required=%.1f", metrics.net_displacement, pos_cfg.loss_min_pts)
                return Signal(signal_type=SignalType.NONE)
            self._mark_signal_time()
            self._log.info(
                "[SIGNAL ENTRY] type=SELL reason=reversal_buy_to_sell velocity=%.1f vel_fast=%.1f displacement=%.1f",
                metrics.velocity, metrics.velocity_fast, metrics.net_displacement,
            )
            return entry_signal

        if self._position_side == OrderSide.SELL and entry_signal.signal_type == SignalType.BUY:
            rev_vel_threshold = self._adaptive_velocity_threshold * pos_cfg.reversal_vel_mult
            if abs(metrics.velocity_fast) < rev_vel_threshold:
                self._log.info("[REVERSAL BLOCKED] reason=weak_velocity side=SELL entry=BUY vel_fast=%.1f required=%.1f", metrics.velocity_fast, rev_vel_threshold)
                return Signal(signal_type=SignalType.NONE)
            if abs(metrics.net_displacement) < pos_cfg.loss_min_pts:
                self._log.info("[REVERSAL BLOCKED] reason=below_loss_min side=SELL entry=BUY disp=%.1f required=%.1f", metrics.net_displacement, pos_cfg.loss_min_pts)
                return Signal(signal_type=SignalType.NONE)
            self._mark_signal_time()
            self._log.info(
                "[SIGNAL ENTRY] type=BUY reason=reversal_sell_to_buy velocity=%.1f vel_fast=%.1f displacement=%.1f",
                metrics.velocity, metrics.velocity_fast, metrics.net_displacement,
            )
            return entry_signal

        self._log.info("[SIGNAL BLOCKED] reason=position_exists side=%s entry=%s", self._position_side.name if self._position_side else "?", entry_signal.signal_type.name)
        return Signal(signal_type=SignalType.NONE)

    def _check_exit(self, tick: TickData, metrics: TickMetrics) -> Optional[Signal]:
        pos_cfg = self._settings.position
        if self._position_entry_time > 0 and (time.time() - self._position_entry_time) < pos_cfg.min_hold_seconds:
            return None

        disp = metrics.net_displacement
        adverse = 0.0

        if self._position_side == OrderSide.BUY:
            adverse = -disp
        elif self._position_side == OrderSide.SELL:
            adverse = disp

        if adverse >= pos_cfg.loss_min_pts:
            if adverse > pos_cfg.loss_max_pts:
                self._log.info("[EXIT] reason=loss_max side=%s adverse=%.1f loss_max=%.1f", self._position_side.name if self._position_side else "?", adverse, pos_cfg.loss_max_pts)
            else:
                self._log.info("[EXIT] reason=loss_range side=%s adverse=%.1f loss_min=%.1f loss_max=%.1f hold=%.1fs", self._position_side.name if self._position_side else "?", adverse, pos_cfg.loss_min_pts, pos_cfg.loss_max_pts, time.time() - self._position_entry_time)
            self._mark_signal_time()
            return Signal(signal_type=SignalType.CLOSE, reason="loss_exit", strength=1.0)

        return None

    def _check_hft_entry(self, tick: TickData, metrics: TickMetrics) -> Signal:
        if not metrics.is_valid:
            return Signal(signal_type=SignalType.NONE)

        if self._is_in_risk_cooldown():
            return Signal(signal_type=SignalType.NONE)

        spread_ticks = tick.spread / self._point if self._point > 0 else 0.0
        if spread_ticks > self._signal_cfg.hft_max_spread_ticks:
            return Signal(signal_type=SignalType.NONE)

        if metrics.micro_range < self._signal_cfg.hft_min_micro_range:
            return Signal(signal_type=SignalType.NONE)

        vel_threshold = self._adaptive_velocity_threshold
        disp = metrics.net_displacement
        trend_boost = 1.0 + min(metrics.trend_bars, 5) * 0.1
        acc_boost = 1.0 + max(0.0, metrics.acceleration / vel_threshold) * 0.3

        if self._last_close_time > 0 and self._last_close_side is not None and (time.time() - self._last_close_time) < self._settings.position.post_close_cooldown_s:
            if metrics.velocity_fast > vel_threshold and self._last_close_side == OrderSide.BUY:
                return Signal(signal_type=SignalType.NONE)
            if metrics.velocity_fast < -vel_threshold and self._last_close_side == OrderSide.SELL:
                return Signal(signal_type=SignalType.NONE)

        if self._reentry_enabled and self._last_close_pnl < 0 and self._last_close_side is not None:
            same_dir = False
            if self._last_close_side == OrderSide.BUY and metrics.velocity_fast > 0 and disp > 0:
                same_dir = True
            elif self._last_close_side == OrderSide.SELL and metrics.velocity_fast < 0 and disp < 0:
                same_dir = True
            if same_dir:
                reentry = self._reentry_engine.evaluate_reentry(
                    tick=tick,
                    metrics=metrics,
                    last_close_price=self._last_close_price,
                    last_close_side=self._last_close_side,
                    last_close_pnl=self._last_close_pnl,
                )
                if not reentry.allowed:
                    return Signal(signal_type=SignalType.NONE)

        if metrics.velocity_fast > vel_threshold and disp > 0:
            if self._signal_cfg.hft_min_displacement_pts > 0 and disp < self._signal_cfg.hft_min_displacement_pts:
                return Signal(signal_type=SignalType.NONE)
            if self._signal_cfg.hft_acceleration_gate and metrics.acceleration < 0:
                return Signal(signal_type=SignalType.NONE)
            if self._is_duplicate_signal(SignalType.BUY, tick, metrics):
                return Signal(signal_type=SignalType.NONE)
            base_strength = min(1.0, metrics.velocity_fast / (vel_threshold * 2.0))
            strength = min(1.0, base_strength * acc_boost * trend_boost)
            self._mark_signal_time()
            self._record_entry_signal(SignalType.BUY, tick, metrics)
            self._entry_displacement = disp
            self._log.info(
                "[SIGNAL ENTRY] type=BUY reason=hft_continuation velocity=%.1f vel_fast=%.1f "
                "displacement=%.1f acc=%.1f trend_bars=%d micro_range=%.1f strength=%.2f",
                metrics.velocity, metrics.velocity_fast,
                disp, metrics.acceleration, metrics.trend_bars, metrics.micro_range, strength,
            )
            return self._create_hft_signal(SignalType.BUY, tick, strength, "hft_continuation_up")

        if metrics.velocity_fast < -vel_threshold and disp < 0:
            if self._signal_cfg.hft_min_displacement_pts > 0 and abs(disp) < self._signal_cfg.hft_min_displacement_pts:
                return Signal(signal_type=SignalType.NONE)
            if self._signal_cfg.hft_acceleration_gate and metrics.acceleration > 0:
                return Signal(signal_type=SignalType.NONE)
            if self._is_duplicate_signal(SignalType.SELL, tick, metrics):
                return Signal(signal_type=SignalType.NONE)
            base_strength = min(1.0, abs(metrics.velocity_fast) / (vel_threshold * 2.0))
            strength = min(1.0, base_strength * acc_boost * trend_boost)
            self._mark_signal_time()
            self._record_entry_signal(SignalType.SELL, tick, metrics)
            self._entry_displacement = disp
            self._log.info(
                "[SIGNAL ENTRY] type=SELL reason=hft_continuation velocity=%.1f vel_fast=%.1f "
                "displacement=%.1f acc=%.1f trend_bars=%d micro_range=%.1f strength=%.2f",
                metrics.velocity, metrics.velocity_fast,
                disp, metrics.acceleration, metrics.trend_bars, metrics.micro_range, strength,
            )
            return self._create_hft_signal(SignalType.SELL, tick, strength, "hft_continuation_down")

        return Signal(signal_type=SignalType.NONE)

    def _check_idle_fallback(self, tick: TickData, metrics: TickMetrics) -> Signal:
        elapsed_ms = (time.time() - self._last_trade_time) * 1000.0
        if elapsed_ms < self._hft_cfg.idle_timeout_ms:
            return Signal(signal_type=SignalType.NONE)

        if self._is_in_risk_cooldown():
            return Signal(signal_type=SignalType.NONE)

        spread_ticks = tick.spread / self._point if self._point > 0 else 0.0
        if spread_ticks > self._signal_cfg.hft_max_spread_ticks:
            return Signal(signal_type=SignalType.NONE)

        if metrics.micro_range < self._signal_cfg.hft_min_micro_range:
            return Signal(signal_type=SignalType.NONE)

        if self._position_side is not None:
            return Signal(signal_type=SignalType.NONE)

        fallback_vel = self._hft_cfg.fallback_min_velocity

        if metrics.velocity_fast > fallback_vel and metrics.net_displacement > 0:
            if self._reentry_enabled and self._last_close_pnl < 0 and self._last_close_side == OrderSide.BUY and self._last_close_price > 0:
                reentry = self._reentry_engine.evaluate_reentry(
                    tick=tick,
                    metrics=metrics,
                    last_close_price=self._last_close_price,
                    last_close_side=self._last_close_side,
                    last_close_pnl=self._last_close_pnl,
                )
                if not reentry.allowed:
                    return Signal(signal_type=SignalType.NONE)
            if self._signal_cfg.hft_min_displacement_pts > 0 and metrics.net_displacement < self._signal_cfg.hft_min_displacement_pts:
                return Signal(signal_type=SignalType.NONE)
            if self._signal_cfg.hft_acceleration_gate and metrics.acceleration < 0:
                return Signal(signal_type=SignalType.NONE)
            if self._is_duplicate_signal(SignalType.BUY, tick, metrics):
                return Signal(signal_type=SignalType.NONE)
            self._mark_signal_time()
            self._record_entry_signal(SignalType.BUY, tick, metrics)
            self._entry_displacement = metrics.net_displacement
            self._log.info(
                "[HFT FALLBACK] idle_ms=%.0f velocity_fast=%.1f disp=%.1f acc=%.1f decision=BUY",
                elapsed_ms, metrics.velocity_fast, metrics.net_displacement, metrics.acceleration,
            )
            return self._create_hft_signal(SignalType.BUY, tick, 0.5, "hft_idle_fallback_up")

        if metrics.velocity_fast < -fallback_vel and metrics.net_displacement < 0:
            if self._reentry_enabled and self._last_close_pnl < 0 and self._last_close_side == OrderSide.SELL and self._last_close_price > 0:
                reentry = self._reentry_engine.evaluate_reentry(
                    tick=tick,
                    metrics=metrics,
                    last_close_price=self._last_close_price,
                    last_close_side=self._last_close_side,
                    last_close_pnl=self._last_close_pnl,
                )
                if not reentry.allowed:
                    return Signal(signal_type=SignalType.NONE)
            if self._signal_cfg.hft_min_displacement_pts > 0 and abs(metrics.net_displacement) < self._signal_cfg.hft_min_displacement_pts:
                return Signal(signal_type=SignalType.NONE)
            if self._signal_cfg.hft_acceleration_gate and metrics.acceleration > 0:
                return Signal(signal_type=SignalType.NONE)
            if self._is_duplicate_signal(SignalType.SELL, tick, metrics):
                return Signal(signal_type=SignalType.NONE)
            self._mark_signal_time()
            self._record_entry_signal(SignalType.SELL, tick, metrics)
            self._entry_displacement = metrics.net_displacement
            self._log.info(
                "[HFT FALLBACK] idle_ms=%.0f velocity_fast=%.1f disp=%.1f acc=%.1f decision=SELL",
                elapsed_ms, metrics.velocity_fast, metrics.net_displacement, metrics.acceleration,
            )
            return self._create_hft_signal(SignalType.SELL, tick, 0.5, "hft_idle_fallback_down")

        return Signal(signal_type=SignalType.NONE)

    def _check_entry(self, tick: TickData, metrics: TickMetrics) -> Signal:
        if not metrics.is_valid:
            return Signal(signal_type=SignalType.NONE)

        if metrics.velocity_fast < self._signal_cfg.min_velocity:
            return Signal(signal_type=SignalType.NONE)

        if abs(metrics.acceleration) < self._signal_cfg.min_acceleration:
            return Signal(signal_type=SignalType.NONE)

        spread_ticks = tick.spread / self._point if self._point > 0 else 0
        if spread_ticks > self._signal_cfg.max_spread_ticks:
            return Signal(signal_type=SignalType.NONE)

        is_breakout_up = False
        is_breakout_down = False

        if self._recent_highs.size >= 10 and self._recent_lows.size >= 10:
            highs = self._recent_highs.to_array()[-10:]
            lows = self._recent_lows.to_array()[-10:]
            range_high = max(highs)
            range_low = min(lows)
            range_size = range_high - range_low

            if range_size > 0 and self._point > 0:
                breakout_threshold = range_size * self._signal_cfg.micro_breakout_factor

                if tick.ask > range_high + breakout_threshold * 0.5:
                    is_breakout_up = True
                elif tick.bid < range_low - breakout_threshold * 0.5:
                    is_breakout_down = True

        if is_breakout_up and metrics.acceleration > 0 and metrics.net_displacement > 0:
            strength = min(1.0, metrics.velocity_fast / (self._signal_cfg.min_velocity * 2.0))
            if strength >= self._signal_cfg.min_strength:
                self._mark_signal_time()
                self._log.info(
                    "BUY SIGNAL | VelFast: %.1f | Acc: %.1f | Disp: %.1f | Str: %.2f",
                    metrics.velocity_fast, metrics.acceleration, metrics.net_displacement, strength,
                )
                return self._create_signal(
                    SignalType.BUY, tick, strength, "momentum_burst_up"
                )

        elif is_breakout_down and metrics.acceleration < 0 and metrics.net_displacement < 0:
            strength = min(1.0, abs(metrics.velocity_fast) / (self._signal_cfg.min_velocity * 2.0))
            if strength >= self._signal_cfg.min_strength:
                self._mark_signal_time()
                self._log.info(
                    "SELL SIGNAL | VelFast: %.1f | Acc: %.1f | Disp: %.1f | Str: %.2f",
                    metrics.velocity_fast, metrics.acceleration, metrics.net_displacement, strength,
                )
                return self._create_signal(
                    SignalType.SELL, tick, strength, "momentum_burst_down"
                )

        return Signal(signal_type=SignalType.NONE)

    def _create_hft_signal(
        self,
        signal_type: SignalType,
        tick: TickData,
        strength: float,
        reason: str,
    ) -> Signal:
        sl_ticks = self._settings.trading.hft_stop_loss_ticks
        tp_ticks = self._settings.trading.hft_take_profit_ticks

        if signal_type == SignalType.BUY:
            entry = tick.ask
            sl = entry - sl_ticks * self._point
            tp = entry + tp_ticks * self._point if tp_ticks > 0 else 0.0
        elif signal_type == SignalType.SELL:
            entry = tick.bid
            sl = entry + sl_ticks * self._point
            tp = entry - tp_ticks * self._point if tp_ticks > 0 else 0.0
        else:
            return Signal(signal_type=SignalType.NONE)

        return Signal(
            signal_type=signal_type,
            strength=strength,
            reason=reason,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            timestamp=time.time(),
        )

    def notify_trade_time(self) -> None:
        self._last_trade_time = time.time()
        if self._reentry_enabled:
            self._reentry_engine.notify_trade()

    def notify_risk_blocked(self) -> None:
        self._last_risk_block_time = time.time()

    def _is_in_risk_cooldown(self) -> bool:
        if self._last_risk_block_time <= 0:
            return False
        remaining = self._risk_block_cooldown_s - (time.time() - self._last_risk_block_time)
        if remaining > 0:
            return True
        return False

    def _is_duplicate_signal(self, signal_type: SignalType, tick: TickData, metrics: TickMetrics) -> bool:
        if self._last_entry_signal_time <= 0:
            return False
        elapsed_ms = (time.time() - self._last_entry_signal_time) * 1000.0
        if elapsed_ms > self._signal_dedup_ms:
            return False
        if signal_type != self._last_signal_direction:
            return False
        price_zone = round(tick.mid / (self._point * 10.0)) if self._point > 0 else 0.0
        if price_zone != self._last_signal_price_zone:
            return False
        vel_regime = "high" if abs(metrics.velocity) > 10.0 else "mid" if abs(metrics.velocity) > 5.0 else "low"
        if vel_regime != self._last_signal_velocity_regime:
            return False
        return True

    def _record_entry_signal(self, signal_type: SignalType, tick: TickData, metrics: TickMetrics) -> None:
        self._last_entry_signal_time = time.time()
        self._last_signal_direction = signal_type
        self._last_signal_price_zone = round(tick.mid / (self._point * 10.0)) if self._point > 0 else 0.0
        self._last_signal_velocity_regime = "high" if abs(metrics.velocity) > 10.0 else "mid" if abs(metrics.velocity) > 5.0 else "low"
