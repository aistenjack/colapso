import time
from dataclasses import dataclass
from typing import Optional

from core.logger import Log
from core.utils import TickData, TickMetrics, OrderSide


@dataclass(slots=True)
class MicroCandle:
    open_price: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    tick_count: int = 0
    start_time_ms: int = 0
    end_time_ms: int = 0
    direction: int = 0
    body_ratio: float = 0.0
    wick_upper_ratio: float = 0.0
    wick_lower_ratio: float = 0.0
    strength: float = 0.0

    def finalize(self) -> None:
        if self.tick_count == 0 or self.high == self.low:
            self.direction = 0
            self.body_ratio = 0.0
            self.wick_upper_ratio = 0.0
            self.wick_lower_ratio = 0.0
            self.strength = 0.0
            return
        rng = self.high - self.low
        if self.close >= self.open_price:
            self.direction = 1
            body = self.close - self.open_price
        else:
            self.direction = -1
            body = self.open_price - self.close
        self.body_ratio = body / rng if rng > 0 else 0.0
        upper_wick = self.high - max(self.open_price, self.close)
        lower_wick = min(self.open_price, self.close) - self.low
        self.wick_upper_ratio = upper_wick / rng if rng > 0 else 0.0
        self.wick_lower_ratio = lower_wick / rng if rng > 0 else 0.0
        self.strength = self.body_ratio * self.direction


@dataclass(slots=True)
class ReentryResult:
    allowed: bool = True
    final_score: float = 0.0
    retrace_score: float = 0.0
    breakout_score: float = 0.0
    structure_score: float = 0.0
    consistency_score: float = 0.0
    velocity_score: float = 0.0
    chop_penalty: float = 0.0
    spread_penalty: float = 0.0
    echo_blocked: bool = False
    threshold: float = 0.0
    mode: str = ""


_SPEED_STATE_LENTO = 1
_SPEED_STATE_EXAUSTAO = 2
_SPEED_STATE_NEUTRO = 3
_SPEED_STATE_ACELERANDO = 4
_SPEED_STATE_FORTE = 5

_SPEED_STATE_MAP = {
    "LENTO": _SPEED_STATE_LENTO,
    "EXAUSTAO": _SPEED_STATE_EXAUSTAO,
    "NEUTRO": _SPEED_STATE_NEUTRO,
    "ACELERANDO": _SPEED_STATE_ACELERANDO,
    "FORTE": _SPEED_STATE_FORTE,
}


class MicroStructureEngine:
    __slots__ = (
        "_candle_ticks", "_point", "_log",
        "_candles", "_candle_idx",
        "_current_candle",
        "_cached_c0", "_cached_c1", "_cached_c2", "_candles_cache_valid",
        "_retrace_w", "_breakout_w", "_structure_w",
        "_consistency_w", "_velocity_w", "_chop_penalty_max", "_spread_penalty_max",
        "_threshold_base", "_threshold_current",
        "_echo_proximity_pts", "_freq_target", "_freq_window_s",
        "_trade_times", "_trade_times_head", "_trade_times_count", "_trade_times_cap",
        "_eval_times", "_eval_times_head", "_eval_times_count", "_eval_times_cap",
        "_wins", "_losses", "_pnl_sum", "_outcomes_head", "_outcomes_count", "_outcomes_cap",
        "_speed_state",
        "_log_counter",
    )

    def __init__(
        self,
        candle_ticks: int = 15,
        point: float = 1.0,
        retrace_score: float = 0.30,
        breakout_score: float = 0.20,
        structure_score: float = 0.15,
        consistency_score: float = 0.15,
        velocity_score: float = 0.10,
        chop_penalty: float = 0.10,
        spread_penalty: float = 0.05,
        threshold_base: float = 0.55,
        echo_proximity_pts: float = 3.0,
        freq_target: float = 3.0,
        freq_window_s: float = 60.0,
    ) -> None:
        self._candle_ticks = candle_ticks
        self._point = point
        self._log = Log.get("reentry")

        self._candles: list[MicroCandle] = [MicroCandle() for _ in range(3)]
        self._candle_idx: int = 0
        self._current_candle: MicroCandle = MicroCandle()
        self._cached_c0: MicroCandle = self._candles[0]
        self._cached_c1: MicroCandle = self._candles[1]
        self._cached_c2: MicroCandle = self._candles[2]
        self._candles_cache_valid: bool = True

        self._retrace_w = retrace_score
        self._breakout_w = breakout_score
        self._structure_w = structure_score
        self._consistency_w = consistency_score
        self._velocity_w = velocity_score
        self._chop_penalty_max = chop_penalty
        self._spread_penalty_max = spread_penalty
        self._threshold_base = threshold_base
        self._threshold_current = threshold_base
        self._echo_proximity_pts = echo_proximity_pts
        self._freq_target = freq_target
        self._freq_window_s = freq_window_s

        self._trade_times_cap = 64
        self._trade_times: list[float] = [0.0] * self._trade_times_cap
        self._trade_times_head: int = 0
        self._trade_times_count: int = 0

        self._eval_times_cap = 128
        self._eval_times: list[float] = [0.0] * self._eval_times_cap
        self._eval_times_head: int = 0
        self._eval_times_count: int = 0

        self._outcomes_cap = 50
        self._wins: int = 0
        self._losses: int = 0
        self._pnl_sum: float = 0.0
        self._outcomes_head: int = 0
        self._outcomes_count: int = 0

        self._speed_state: int = _SPEED_STATE_NEUTRO
        self._log_counter: int = 0

    @property
    def candles(self) -> tuple[MicroCandle, MicroCandle, MicroCandle]:
        if not self._candles_cache_valid:
            idx = self._candle_idx
            self._cached_c0 = self._candles[idx % 3]
            self._cached_c1 = self._candles[(idx + 1) % 3]
            self._cached_c2 = self._candles[(idx + 2) % 3]
            self._candles_cache_valid = True
        return self._cached_c0, self._cached_c1, self._cached_c2

    @property
    def current_candle(self) -> MicroCandle:
        return self._current_candle

    def set_point(self, point: float) -> None:
        self._point = point

    def set_speed_state(self, state_name: str) -> None:
        self._speed_state = _SPEED_STATE_MAP.get(state_name, _SPEED_STATE_NEUTRO)

    def on_tick(self, tick: TickData) -> None:
        c = self._current_candle
        if c.tick_count == 0:
            c.open_price = tick.mid
            c.high = tick.mid
            c.low = tick.mid
            c.start_time_ms = tick.time_ms
        else:
            if tick.mid > c.high:
                c.high = tick.mid
            elif tick.mid < c.low:
                c.low = tick.mid
        c.close = tick.mid
        c.end_time_ms = tick.time_ms
        c.tick_count += 1

        if c.tick_count >= self._candle_ticks:
            c.finalize()
            self._candles[self._candle_idx] = c
            self._candle_idx = (self._candle_idx + 1) % 3
            self._candles_cache_valid = False
            self._current_candle = MicroCandle()

    def notify_trade(self) -> None:
        now = time.time()
        self._ring_push_time(self._trade_times, now)
        self._trade_times_count += 1

    def notify_outcome(self, pnl: float) -> None:
        if pnl > 0:
            self._wins += 1
        elif pnl < 0:
            self._losses += 1
        self._pnl_sum += pnl

    def evaluate_reentry(
        self,
        tick: TickData,
        metrics: TickMetrics,
        last_close_price: float,
        last_close_side: Optional[OrderSide],
        last_close_pnl: float,
    ) -> ReentryResult:
        self._ring_push_time(self._eval_times, time.time())
        self._eval_times_count += 1

        if last_close_side is None or last_close_price <= 0.0:
            return ReentryResult(allowed=True, final_score=1.0, threshold=0.0, mode="first_trade")

        self._adapt_threshold()

        result = ReentryResult()
        result.threshold = self._threshold_current

        same_dir = self._detect_same_direction(metrics, last_close_side)
        if not same_dir:
            result.allowed = True
            result.final_score = 1.0
            result.mode = "flip"
            return result

        spread_pts = tick.spread / self._point if self._point > 0 else 0.0

        rs = self._calc_retrace_score(tick, last_close_price, last_close_side, metrics)
        bs = self._calc_breakout_score(tick, last_close_price, last_close_side, metrics)
        ss = self._calc_structure_score(last_close_side)
        cs = self._calc_consistency_score(metrics, last_close_side)
        vs = self._calc_velocity_score(metrics, last_close_side)
        cp = self._calc_chop_penalty()
        sp = self._calc_spread_penalty(spread_pts)

        result.retrace_score = rs
        result.breakout_score = bs
        result.structure_score = ss
        result.consistency_score = cs
        result.velocity_score = vs
        result.chop_penalty = cp
        result.spread_penalty = sp

        raw = (
            rs * self._retrace_w
            + bs * self._breakout_w
            + ss * self._structure_w
            + cs * self._consistency_w
            + vs * self._velocity_w
            - cp
            - sp
        )

        price_dist = abs(tick.mid - last_close_price) / self._point if self._point > 0 else 0.0
        has_retrace = rs > 0.3
        has_breakout = bs > 0.5
        has_consistency = cs > 0.4

        is_echo = (
            price_dist < self._echo_proximity_pts
            and not has_retrace
            and not has_breakout
            and not has_consistency
        )

        if is_echo:
            final = raw * 0.1
        else:
            final = max(0.0, min(1.0, raw))

        result.final_score = final
        result.echo_blocked = is_echo

        if rs >= bs and rs > 0.0:
            result.mode = "pullback" if has_retrace else ""
        else:
            result.mode = "breakout" if has_breakout else ""

        if not is_echo:
            if result.mode == "pullback" and rs < 0.15:
                final *= 0.3
                result.final_score = final
            elif result.mode == "breakout" and bs < 0.20:
                final *= 0.3
                result.final_score = final

        result.allowed = final >= self._threshold_current

        self._log_counter += 1
        if not result.allowed or self._log_counter % 25 == 0:
            self._log.info(
                "[REENTRY SCORE] retrace=%.2f breakout=%.2f structure=%.2f "
                "consistency=%.2f velocity=%.2f chop_pen=%.2f spread_pen=%.2f "
                "final=%.3f threshold=%.3f echo=%s mode=%s decision=%s "
                "price_dist=%.1f close_pnl=%.1f",
                rs, bs, ss, cs, vs, cp, sp,
                final, self._threshold_current,
                "YES" if is_echo else "no",
                result.mode,
                "ALLOW" if result.allowed else "BLOCK",
                price_dist, last_close_pnl,
            )

        return result

    def _detect_same_direction(self, metrics: TickMetrics, last_close_side: OrderSide) -> bool:
        if last_close_side == OrderSide.BUY and metrics.velocity_fast > 0 and metrics.net_displacement > 0:
            return True
        if last_close_side == OrderSide.SELL and metrics.velocity_fast < 0 and metrics.net_displacement < 0:
            return True
        return False

    def _calc_retrace_score(self, tick: TickData, close_price: float, close_side: OrderSide, metrics: TickMetrics) -> float:
        if self._point <= 0:
            return 0.0

        c0, c1, c2 = self.candles

        if close_side == OrderSide.BUY:
            retrace = (close_price - tick.mid) / self._point
        else:
            retrace = (tick.mid - close_price) / self._point

        if retrace < 0:
            return 0.0

        if retrace < 1.0:
            return 0.05

        if retrace <= 8.0:
            base = retrace / 8.0
        else:
            base = 1.0 - min((retrace - 8.0) / 12.0, 0.8)

        against = 0
        total = 0
        for c in (c0, c1, c2):
            if c.tick_count < 3:
                continue
            total += 1
            if close_side == OrderSide.BUY and c.direction < 0:
                against += 1
            elif close_side == OrderSide.SELL and c.direction > 0:
                against += 1

        retrace_struct = 0.5
        if total > 0:
            retrace_struct = against / total

        if retrace_struct < 0.5:
            struct_mult = 1.0
        elif retrace_struct < 1.0:
            struct_mult = 0.6
        else:
            struct_mult = 0.3

        acc = metrics.acceleration
        if close_side == OrderSide.BUY:
            reacel = acc > 0
        else:
            reacel = acc < 0

        accel_mult = 1.3 if reacel else 0.7

        return min(1.0, base * struct_mult * accel_mult)

    def _calc_breakout_score(self, tick: TickData, close_price: float, close_side: OrderSide, metrics: TickMetrics) -> float:
        if self._point <= 0:
            return 0.0

        c0, c1, c2 = self.candles

        if close_side == OrderSide.BUY:
            swing = close_price
            for c in (c0, c1, c2):
                if c.tick_count >= 3 and c.high > swing:
                    swing = c.high
            exceeded = tick.mid > swing
            impulse = (tick.mid - swing) / self._point if exceeded else 0.0
        else:
            swing = close_price
            for c in (c0, c1, c2):
                if c.tick_count >= 3 and c.low < swing:
                    swing = c.low
            exceeded = tick.mid < swing
            impulse = (swing - tick.mid) / self._point if exceeded else 0.0

        if not exceeded:
            return 0.0

        imp_score = min(1.0, impulse / 10.0)

        if close_side == OrderSide.BUY:
            vel_conf = min(1.0, metrics.velocity_fast / 15.0) if metrics.velocity_fast > 0 else 0.0
        else:
            vel_conf = min(1.0, abs(metrics.velocity_fast) / 15.0) if metrics.velocity_fast < 0 else 0.0

        if close_side == OrderSide.BUY:
            acc_conf = metrics.acceleration > 0
        else:
            acc_conf = metrics.acceleration < 0

        acc_mult = 1.4 if acc_conf else 0.5

        return min(1.0, imp_score * vel_conf * acc_mult)

    def _calc_structure_score(self, close_side: OrderSide) -> float:
        c0, c1, c2 = self.candles

        n_valid = 0
        i_valid_0 = -1
        i_valid_1 = -1
        i_valid_2 = -1
        for c in (c0, c1, c2):
            if c.tick_count >= 3:
                if i_valid_0 == -1:
                    i_valid_0 = n_valid
                elif i_valid_1 == -1:
                    i_valid_1 = n_valid
                elif i_valid_2 == -1:
                    i_valid_2 = n_valid
            n_valid += 1

        valid = []
        for c in (c0, c1, c2):
            if c.tick_count >= 3:
                valid.append(c)

        if len(valid) == 0:
            return 0.3

        if len(valid) == 1:
            c = valid[0]
            if close_side == OrderSide.BUY:
                return 0.7 if c.direction > 0 else 0.3
            else:
                return 0.7 if c.direction < 0 else 0.3

        seq_score = 0.0
        for c in valid:
            if close_side == OrderSide.BUY and c.direction > 0:
                seq_score += 1.0
            elif close_side == OrderSide.SELL and c.direction < 0:
                seq_score += 1.0
            elif c.direction == 0:
                seq_score += 0.3

        seq_score /= len(valid)

        hh_hl = True
        lh_ll = True
        if len(valid) >= 2:
            for i in range(1, len(valid)):
                if not (valid[i].high >= valid[i - 1].high):
                    hh_hl = False
                if not (valid[i].low >= valid[i - 1].low):
                    hh_hl = False
                if not (valid[i].high <= valid[i - 1].high):
                    lh_ll = False
                if not (valid[i].low <= valid[i - 1].low):
                    lh_ll = False
        else:
            hh_hl = False
            lh_ll = False

        if close_side == OrderSide.BUY and hh_hl:
            seq_score = min(1.0, seq_score + 0.25)
        elif close_side == OrderSide.SELL and lh_ll:
            seq_score = min(1.0, seq_score + 0.25)
        elif close_side == OrderSide.BUY and lh_ll:
            seq_score *= 0.4
        elif close_side == OrderSide.SELL and hh_hl:
            seq_score *= 0.4

        avg_body = sum(c.body_ratio for c in valid) / len(valid)
        body_mult = 0.5 + 0.5 * min(avg_body, 1.0)

        if close_side == OrderSide.BUY:
            avg_wick_upper = sum(c.wick_upper_ratio for c in valid) / len(valid)
            if avg_wick_upper > 0.5:
                body_mult *= 0.6
        else:
            avg_wick_lower = sum(c.wick_lower_ratio for c in valid) / len(valid)
            if avg_wick_lower > 0.5:
                body_mult *= 0.6

        return min(1.0, seq_score * body_mult)

    def _calc_consistency_score(self, metrics: TickMetrics, close_side: OrderSide) -> float:
        disp = metrics.net_displacement
        vel = metrics.velocity_fast

        if close_side == OrderSide.BUY:
            dir_align = 1.0 if disp > 0 and vel > 0 else (0.3 if disp > 0 or vel > 0 else 0.0)
            vel_ratio = min(1.0, vel / 10.0) if vel > 0 else 0.0
        else:
            dir_align = 1.0 if disp < 0 and vel < 0 else (0.3 if disp < 0 or vel < 0 else 0.0)
            vel_ratio = min(1.0, abs(vel) / 10.0) if vel < 0 else 0.0

        disp_abs = abs(disp)
        if disp_abs >= 8.0:
            disp_score = 1.0
        elif disp_abs >= 4.0:
            disp_score = 0.6
        elif disp_abs >= 2.0:
            disp_score = 0.3
        else:
            disp_score = 0.05

        return dir_align * 0.6 + vel_ratio * 0.2 + disp_score * 0.2

    def _calc_velocity_score(self, metrics: TickMetrics, close_side: OrderSide) -> float:
        if close_side == OrderSide.BUY:
            v = metrics.velocity_fast
            if v <= 0:
                return 0.0
            if v >= 15.0:
                base = 1.0
            elif v >= 8.0:
                base = 0.7
            elif v >= 4.0:
                base = 0.4
            else:
                base = 0.15
        else:
            v = metrics.velocity_fast
            if v >= 0:
                return 0.0
            av = abs(v)
            if av >= 15.0:
                base = 1.0
            elif av >= 8.0:
                base = 0.7
            elif av >= 4.0:
                base = 0.4
            else:
                base = 0.15

        acc = metrics.acceleration
        if close_side == OrderSide.BUY and acc > 0:
            base = min(1.0, base * 1.3)
        elif close_side == OrderSide.SELL and acc < 0:
            base = min(1.0, base * 1.3)
        elif close_side == OrderSide.BUY and acc < -3.0:
            base *= 0.5
        elif close_side == OrderSide.SELL and acc > 3.0:
            base *= 0.5

        return base

    def _calc_chop_penalty(self) -> float:
        c0, c1, c2 = self.candles
        valid = []
        for c in (c0, c1, c2):
            if c.tick_count >= 3:
                valid.append(c)
        if len(valid) < 2:
            return 0.0

        mixed = 0
        for c in valid:
            if c.direction == 0:
                mixed += 1
            elif c.body_ratio < 0.25:
                mixed += 0.7

        directions = []
        for c in valid:
            if c.direction != 0:
                directions.append(c.direction)
        if len(directions) >= 2:
            sign_changes = 0
            for i in range(1, len(directions)):
                if directions[i] != directions[i - 1]:
                    sign_changes += 1
            mixed += sign_changes * 0.5

        candle_chop = min(self._chop_penalty_max, mixed / len(valid) * self._chop_penalty_max)

        speed_chop = 0.0
        if self._speed_state == _SPEED_STATE_LENTO:
            speed_chop = 0.08
        elif self._speed_state == _SPEED_STATE_EXAUSTAO:
            speed_chop = 0.15

        return min(self._chop_penalty_max, candle_chop + speed_chop)

    def _calc_spread_penalty(self, spread_pts: float) -> float:
        if spread_pts <= 3.0:
            return 0.0
        elif spread_pts <= 5.0:
            return self._spread_penalty_max * 0.5
        else:
            return self._spread_penalty_max

    def _adapt_threshold(self) -> None:
        now = time.time()
        cutoff = now - self._freq_window_s

        start = self._trade_times_head - self._trade_times_count
        if start < 0:
            start += self._trade_times_cap
        count = 0
        for i in range(self._trade_times_count):
            idx = (start + i) % self._trade_times_cap
            if self._trade_times[idx] >= cutoff:
                if idx != self._trade_times_head:
                    pass
                count += 1

        new_head = self._trade_times_head
        new_count = 0
        for i in range(self._trade_times_count):
            pos = (self._trade_times_head - self._trade_times_count + i) % self._trade_times_cap
            if self._trade_times[pos] >= cutoff:
                if new_count == 0:
                    new_head = (pos + 1) % self._trade_times_cap
                new_count += 1

        if new_count == 0 and self._trade_times_count > 0:
            self._trade_times_head = self._trade_times_head
            self._trade_times_count = 0

        trades_per_min = count * (60.0 / self._freq_window_s) if self._freq_window_s > 0 else 0.0

        eval_cutoff = now - 120.0
        eval_count = 0
        for i in range(self._eval_times_count):
            pos = (self._eval_times_head - self._eval_times_count + i) % self._eval_times_cap
            if self._eval_times[pos] >= eval_cutoff:
                eval_count += 1

        if eval_count < 10:
            self._threshold_current = self._threshold_base
            return

        total = self._wins + self._losses
        recent_wr = self._wins / total if total >= 5 else 0.5
        recent_pnl = self._pnl_sum

        adjustment = 0.0
        reason = "balanced"

        if trades_per_min < self._freq_target * 0.5:
            adjustment = -0.15
            reason = "freq_low"
        elif trades_per_min < self._freq_target:
            adjustment = -0.08
            reason = "freq_below_target"
        elif trades_per_min > self._freq_target * 2.5:
            adjustment = 0.15
            reason = "freq_high"
        elif trades_per_min > self._freq_target * 1.5:
            adjustment = 0.08
            reason = "freq_above_target"

        if total >= 5:
            if recent_wr < 0.40:
                adjustment += 0.10
                reason = "wr_bad" if adjustment <= 0 else "freq_high+wr_bad"
            elif recent_wr < 0.50:
                adjustment += 0.05
                reason = "wr_below_avg" if adjustment <= 0 else "freq_high+wr_low"
            elif recent_wr >= 0.65 and adjustment <= 0:
                adjustment -= 0.03
                reason = "wr_good+freq_low" if trades_per_min < self._freq_target else "wr_good"

        if total >= 10 and recent_pnl < -20.0:
            adjustment += 0.05
            if "pnl" not in reason:
                reason = reason + "+pnl_negative" if reason != "balanced" else "pnl_negative"

        adjustment = max(-0.15, min(0.15, adjustment))

        self._threshold_current = max(0.30, min(0.80, self._threshold_base + adjustment))

        self._log.info(
            "[ADAPTIVE THRESHOLD] freq=%.1f target_freq=%.1f recent_wr=%.1f%% "
            "recent_pnl=%.1f base=%.3f adjusted=%.3f reason=%s",
            trades_per_min, self._freq_target,
            recent_wr * 100.0, recent_pnl,
            self._threshold_base, self._threshold_current,
            reason,
        )

    def _ring_push_time(self, buf: list[float], t: float) -> None:
        if buf is self._trade_times:
            cap = self._trade_times_cap
            head = self._trade_times_head
            count = self._trade_times_count
            buf[head] = t
            head = (head + 1) % cap
            if count < cap:
                count += 1
            self._trade_times_head = head
            self._trade_times_count = count
        else:
            cap = self._eval_times_cap
            head = self._eval_times_head
            count = self._eval_times_count
            buf[head] = t
            head = (head + 1) % cap
            if count < cap:
                count += 1
            self._eval_times_head = head
            self._eval_times_count = count

    def get_diagnostics(self) -> dict:
        c0, c1, c2 = self.candles
        now = time.time()
        cutoff = now - self._freq_window_s
        count = 0
        for i in range(self._trade_times_count):
            pos = (self._trade_times_head - self._trade_times_count + i) % self._trade_times_cap
            if self._trade_times[pos] >= cutoff:
                count += 1
        tpm = count * (60.0 / self._freq_window_s) if self._freq_window_s > 0 else 0.0
        total = self._wins + self._losses
        wr = self._wins / total * 100.0 if total > 0 else 0.0
        return {
            "threshold_current": f"{self._threshold_current:.3f}",
            "threshold_base": f"{self._threshold_base:.3f}",
            "trades_per_min": f"{tpm:.1f}",
            "recent_wr": f"{wr:.0f}%",
            "recent_pnl": f"{self._pnl_sum:.0f}",
            "speed_state": {1: "LENTO", 2: "EXAUSTAO", 3: "NEUTRO", 4: "ACELERANDO", 5: "FORTE"}.get(self._speed_state, "?"),
            "candle_0": f"dir={c0.direction} body={c0.body_ratio:.2f} wick_u={c0.wick_upper_ratio:.2f} wick_l={c0.wick_lower_ratio:.2f} ticks={c0.tick_count}",
            "candle_1": f"dir={c1.direction} body={c1.body_ratio:.2f} wick_u={c1.wick_upper_ratio:.2f} wick_l={c1.wick_lower_ratio:.2f} ticks={c1.tick_count}",
            "candle_2": f"dir={c2.direction} body={c2.body_ratio:.2f} wick_u={c2.wick_upper_ratio:.2f} wick_l={c2.wick_lower_ratio:.2f} ticks={c2.tick_count}",
            "current_candle_ticks": self._current_candle.tick_count,
        }
