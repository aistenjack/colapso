import time
import MetaTrader5 as mt5
from typing import Optional

from core.logger import Log
from core.utils import Signal, SignalType, TradeResult, TradeStatus, OrderSide
from config.settings import Settings, PositionSettings


class PositionManager:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pos_cfg: PositionSettings = settings.position
        self._log = Log.get("position")
        self._symbol = settings.trading.symbol

        self._current_ticket: Optional[int] = None
        self._current_side: Optional[OrderSide] = None
        self._current_volume: float = 0.0
        self._current_pnl: float = 0.0
        self._current_position_type: int = 0
        self._entry_price: float = 0.0
        self._entry_time: float = 0.0
        self._stop_loss: float = 0.0
        self._take_profit: float = 0.0
        self._realized_pnl: float = 0.0
        self._trade_count: int = 0
        self._last_known_pnl: float = 0.0
        self._trailing_sl: float = 0.0
        self._trailing_activated: bool = False
        self._point: float = 0.0
        self._last_trailing_attempt_time: float = 0.0
        self._last_trailing_log_time: float = 0.0
        self._min_stop_distance: float = 0.0

        self._virtual_trailing_sl: float = 0.0
        self._virtual_trailing_activated: bool = False
        self._virtual_trailing_move_count: int = 0
        self._virtual_trailing_breakeven_set: bool = False

    def has_position(self) -> bool:
        return self._current_ticket is not None

    def set_point(self, point: float) -> None:
        self._point = point

    def set_min_stop_distance(self, distance: float) -> None:
        self._min_stop_distance = distance

    def sync_with_mt5(self) -> bool:
        positions = mt5.positions_get(symbol=self._symbol)
        if positions is None or len(positions) == 0:
            if self._current_ticket is not None:
                self._last_known_pnl = self._current_pnl
                self._log.info("Posição %d não mais encontrada - resetando estado | PnL preservado: %.2f", self._current_ticket, self._current_pnl)
                self._reset_state()
            return True

        pos = positions[0]
        self._current_ticket = pos.ticket
        self._current_volume = pos.volume
        self._entry_price = pos.price_open
        self._stop_loss = pos.sl
        self._take_profit = pos.tp
        self._current_pnl = pos.profit
        self._current_position_type = pos.type
        self._current_side = OrderSide.BUY if pos.type == mt5.POSITION_TYPE_BUY else OrderSide.SELL

        if self._trailing_sl <= 0 or (self._current_side == OrderSide.BUY and pos.sl > self._trailing_sl) or (self._current_side == OrderSide.SELL and pos.sl < self._trailing_sl and pos.sl > 0):
            self._trailing_sl = pos.sl

        if self._entry_time == 0.0:
            self._entry_time = time.time()

        return True

    def register_open(self, result: TradeResult, signal: Signal) -> None:
        if result.status != TradeStatus.SUCCESS:
            return

        self._current_ticket = result.ticket
        self._current_volume = result.volume
        self._entry_price = result.price
        self._stop_loss = signal.stop_loss
        self._take_profit = signal.take_profit
        self._current_side = result.side
        self._current_pnl = 0.0
        self._entry_time = time.time()
        self._trade_count += 1
        self._trailing_sl = signal.stop_loss
        self._trailing_activated = False
        self._virtual_trailing_sl = 0.0
        self._virtual_trailing_activated = False
        self._virtual_trailing_move_count = 0
        self._virtual_trailing_breakeven_set = False

        self._log.info(
            "Posição registrada | Ticket: %d | Side: %s | Entry: %.2f | SL: %.2f | TP: %.2f",
            result.ticket,
            result.side.name if result.side else "?",
            result.price,
            signal.stop_loss,
            signal.take_profit,
        )

    def register_close(self, result: TradeResult) -> None:
        if result.status == TradeStatus.SUCCESS:
            self._log.info(
                "Posição fechada | Ticket: %d | PnL realizado acumulado: %.2f",
                self._current_ticket or 0,
                self._realized_pnl,
            )
        self._reset_state()

    def _reset_state(self) -> None:
        self._current_ticket = None
        self._current_side = None
        self._current_volume = 0.0
        self._current_pnl = 0.0
        self._current_position_type = 0
        self._entry_price = 0.0
        self._entry_time = 0.0
        self._stop_loss = 0.0
        self._take_profit = 0.0
        self._trailing_sl = 0.0
        self._trailing_activated = False
        self._last_trailing_log_time = 0.0
        self._virtual_trailing_sl = 0.0
        self._virtual_trailing_activated = False
        self._virtual_trailing_move_count = 0
        self._virtual_trailing_breakeven_set = False

    def reset_daily(self) -> None:
        self._trade_count = 0

    def should_close_timeout(self) -> bool:
        if self._current_ticket is None:
            return False
        elapsed = (time.time() - self._entry_time) * 1000.0
        return elapsed > self._pos_cfg.trade_timeout_ms

    def should_close_pnl(self) -> Optional[Signal]:
        if self._current_ticket is None:
            return None

        if self._current_pnl >= 0:
            return None

        max_loss = self._settings.risk.max_daily_loss / 4.0
        if self._current_pnl <= -max_loss:
            self._log.warning("PnL negativo crítico: %.2f - sinalizando fechamento", self._current_pnl)
            return Signal(signal_type=SignalType.CLOSE, reason="pnl_stop")

        return None

    def get_current_pnl(self) -> float:
        return self._current_pnl

    def consume_last_known_pnl(self) -> float:
        pnl = self._last_known_pnl
        self._last_known_pnl = 0.0
        return pnl

    def check_trailing_stop(self, bid: float, ask: float) -> bool:
        if not self._pos_cfg.trailing_stop_enabled:
            return False
        if self._current_ticket is None or self._point <= 0:
            return False

        now = time.time()
        if now - self._last_trailing_attempt_time < self._pos_cfg.trailing_attempt_cooldown_s:
            return False

        activation_pts = self._pos_cfg.trailing_activation_pts
        offset_price = self._pos_cfg.trailing_offset_pts * self._point
        min_dist = self._min_stop_distance if self._min_stop_distance > 0 else 0.0

        if self._current_side == OrderSide.BUY:
            profit_pts = (bid - self._entry_price) / self._point
            if now - self._last_trailing_log_time > 10.0:
                self._log.info("[TRAILING DBG] BUY entry=%.2f bid=%.2f profit_pts=%.2f activated=%s point=%.5f activation=%.1f", self._entry_price, bid, profit_pts, self._trailing_activated, self._point, activation_pts)
                self._last_trailing_log_time = now
            if not self._trailing_activated:
                if profit_pts >= activation_pts:
                    self._trailing_activated = True
                    new_sl = bid - offset_price
                    if min_dist > 0 and bid - new_sl < min_dist:
                        new_sl = bid - min_dist
                    if new_sl > self._trailing_sl + self._point:
                        if self._modify_sl(new_sl):
                            self._trailing_sl = new_sl
                            self._log.info("[TRAILING] ACTIVATED side=BUY profit=%.1fpts sl=%.2f offset=%.1fpts", profit_pts, new_sl, self._pos_cfg.trailing_offset_pts)
                            return True
                    return False
            else:
                if profit_pts < activation_pts:
                    self._trailing_activated = False
                    return False
            new_sl = bid - offset_price
            if min_dist > 0 and bid - new_sl < min_dist:
                new_sl = bid - min_dist
            if new_sl > self._trailing_sl + self._point:
                if self._modify_sl(new_sl):
                    self._trailing_sl = new_sl
                    self._log.info("[TRAILING] MOVED side=BUY sl=%.2f offset=%.1fpts profit=%.1fpts", new_sl, self._pos_cfg.trailing_offset_pts, profit_pts)
                    return True

        elif self._current_side == OrderSide.SELL:
            profit_pts = (self._entry_price - ask) / self._point
            if now - self._last_trailing_log_time > 10.0:
                self._log.info("[TRAILING DBG] SELL entry=%.2f ask=%.2f profit_pts=%.2f activated=%s point=%.5f activation=%.1f", self._entry_price, ask, profit_pts, self._trailing_activated, self._point, activation_pts)
                self._last_trailing_log_time = now
            if not self._trailing_activated:
                if profit_pts >= activation_pts:
                    self._trailing_activated = True
                    new_sl = ask + offset_price
                    if min_dist > 0 and new_sl - ask < min_dist:
                        new_sl = ask + min_dist
                    if self._trailing_sl <= 0 or new_sl < self._trailing_sl - self._point:
                        if self._modify_sl(new_sl):
                            self._trailing_sl = new_sl
                            self._log.info("[TRAILING] ACTIVATED side=SELL profit=%.1fpts sl=%.2f offset=%.1fpts", profit_pts, new_sl, self._pos_cfg.trailing_offset_pts)
                            return True
                    return False
            else:
                if profit_pts < activation_pts:
                    self._trailing_activated = False
                    return False
            new_sl = ask + offset_price
            if min_dist > 0 and new_sl - ask < min_dist:
                new_sl = ask + min_dist
            if self._trailing_sl <= 0 or new_sl < self._trailing_sl - self._point:
                if self._modify_sl(new_sl):
                    self._trailing_sl = new_sl
                    self._log.info("[TRAILING] MOVED side=SELL sl=%.2f offset=%.1fpts profit=%.1fpts", new_sl, self._pos_cfg.trailing_offset_pts, profit_pts)
                    return True

        return False

    def check_virtual_trailing(self, bid: float, ask: float) -> Optional[Signal]:
        if not self._pos_cfg.trailing_stop_enabled:
            return None
        if self._current_ticket is None or self._point <= 0:
            return None
        if not getattr(self._pos_cfg, 'trailing_virtual_enabled', False):
            return None

        activation_pts = self._pos_cfg.trailing_activation_pts
        offset_pts = getattr(self._pos_cfg, 'trailing_virtual_offset_pts', 5.0)
        offset_price = offset_pts * self._point

        if self._current_side == OrderSide.BUY:
            profit_pts = (bid - self._entry_price) / self._point

            if not self._virtual_trailing_activated:
                if profit_pts >= activation_pts:
                    self._virtual_trailing_activated = True
                    if not self._virtual_trailing_breakeven_set:
                        self._virtual_trailing_sl = self._entry_price + offset_price
                        self._virtual_trailing_breakeven_set = True
                        self._virtual_trailing_move_count += 1
                        self._log.info(
                            "[VTRAIL] BREAKEVEN SET side=BUY profit=%.1fpts vsl=%.2f (entry+%.1fpts)",
                            profit_pts, self._virtual_trailing_sl, offset_pts,
                        )
                    else:
                        self._virtual_trailing_sl = bid - offset_price
                        self._virtual_trailing_move_count += 1
                        self._log.info(
                            "[VTRAIL] REACTIVATED side=BUY profit=%.1fpts vsl=%.2f offset=%.1fpts",
                            profit_pts, self._virtual_trailing_sl, offset_pts,
                        )
            else:
                if profit_pts < activation_pts:
                    self._virtual_trailing_activated = False
                    if self._virtual_trailing_breakeven_set:
                        self._virtual_trailing_sl = self._entry_price + offset_price
                        self._log.info("[VTRAIL] DEACTIVATED→BREAKEVEN side=BUY profit=%.1fpts < activation=%.1fpts vsl=%.2f", profit_pts, activation_pts, self._virtual_trailing_sl)
                    else:
                        self._virtual_trailing_sl = 0.0
                        self._log.info("[VTRAIL] DEACTIVATED side=BUY profit=%.1fpts < activation=%.1fpts", profit_pts, activation_pts)
                    return None

                if self._virtual_trailing_breakeven_set:
                    new_vsl = bid - offset_price
                    if new_vsl > self._virtual_trailing_sl + self._point:
                        self._virtual_trailing_sl = new_vsl
                        self._virtual_trailing_move_count += 1
                        if self._virtual_trailing_move_count % 5 == 0:
                            self._log.info(
                                "[VTRAIL] MOVED side=BUY vsl=%.2f offset=%.1fpts profit=%.1fpts moves=%d",
                                new_vsl, offset_pts, profit_pts, self._virtual_trailing_move_count,
                            )

            if self._virtual_trailing_activated or self._virtual_trailing_breakeven_set:
                if bid <= self._virtual_trailing_sl:
                    reason = "breakeven_stop" if self._virtual_trailing_breakeven_set and not self._virtual_trailing_activated else "virtual_trailing_stop"
                    self._log.info(
                        "[VTRAIL] TRIGGERED side=BUY bid=%.2f vsl=%.2f profit=%.1fpts moves=%d reason=%s",
                        bid, self._virtual_trailing_sl, profit_pts, self._virtual_trailing_move_count, reason,
                    )
                    return Signal(signal_type=SignalType.CLOSE, reason=reason, strength=1.0)

        elif self._current_side == OrderSide.SELL:
            profit_pts = (self._entry_price - ask) / self._point

            if not self._virtual_trailing_activated:
                if profit_pts >= activation_pts:
                    self._virtual_trailing_activated = True
                    if not self._virtual_trailing_breakeven_set:
                        self._virtual_trailing_sl = self._entry_price - offset_price
                        self._virtual_trailing_breakeven_set = True
                        self._virtual_trailing_move_count += 1
                        self._log.info(
                            "[VTRAIL] BREAKEVEN SET side=SELL profit=%.1fpts vsl=%.2f (entry-%.1fpts)",
                            profit_pts, self._virtual_trailing_sl, offset_pts,
                        )
                    else:
                        self._virtual_trailing_sl = ask + offset_price
                        self._virtual_trailing_move_count += 1
                        self._log.info(
                            "[VTRAIL] REACTIVATED side=SELL profit=%.1fpts vsl=%.2f offset=%.1fpts",
                            profit_pts, self._virtual_trailing_sl, offset_pts,
                        )
            else:
                if profit_pts < activation_pts:
                    self._virtual_trailing_activated = False
                    if self._virtual_trailing_breakeven_set:
                        self._virtual_trailing_sl = self._entry_price - offset_price
                        self._log.info("[VTRAIL] DEACTIVATED→BREAKEVEN side=SELL profit=%.1fpts < activation=%.1fpts vsl=%.2f", profit_pts, activation_pts, self._virtual_trailing_sl)
                    else:
                        self._virtual_trailing_sl = 0.0
                        self._log.info("[VTRAIL] DEACTIVATED side=SELL profit=%.1fpts < activation=%.1fpts", profit_pts, activation_pts)
                    return None

                if self._virtual_trailing_breakeven_set:
                    new_vsl = ask + offset_price
                    if self._virtual_trailing_sl <= 0 or new_vsl < self._virtual_trailing_sl - self._point:
                        self._virtual_trailing_sl = new_vsl
                        self._virtual_trailing_move_count += 1
                        if self._virtual_trailing_move_count % 5 == 0:
                            self._log.info(
                                "[VTRAIL] MOVED side=SELL vsl=%.2f offset=%.1fpts profit=%.1fpts moves=%d",
                                new_vsl, offset_pts, profit_pts, self._virtual_trailing_move_count,
                            )

            if self._virtual_trailing_activated or self._virtual_trailing_breakeven_set:
                if ask >= self._virtual_trailing_sl:
                    reason = "breakeven_stop" if self._virtual_trailing_breakeven_set and not self._virtual_trailing_activated else "virtual_trailing_stop"
                    self._log.info(
                        "[VTRAIL] TRIGGERED side=SELL ask=%.2f vsl=%.2f profit=%.1fpts moves=%d reason=%s",
                        ask, self._virtual_trailing_sl, profit_pts, self._virtual_trailing_move_count, reason,
                    )
                    return Signal(signal_type=SignalType.CLOSE, reason=reason, strength=1.0)

        return None

    def _modify_sl(self, new_sl: float) -> bool:
        if self._current_ticket is None:
            return False

        self._last_trailing_attempt_time = time.time()

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": self._symbol,
            "position": self._current_ticket,
            "sl": new_sl,
            "tp": self._take_profit,
        }

        result = mt5.order_send(request)
        if result is None:
            err = mt5.last_error()
            self._log.warning("Trailing SL modify falhou | None | Err: %s", err)
            return False

        if result.retcode == mt5.TRADE_RETCODE_DONE:
            self._stop_loss = new_sl
            self._log.info(
                "Trailing SL modificado | Side: %s | Novo SL: %.2f | Offset: %.1fpts",
                self._current_side.name if self._current_side else "?",
                new_sl,
                self._pos_cfg.trailing_offset_pts,
            )
            return True

        if result.retcode in (10013,):
            self._log.warning("Trailing SL: ticket inválido (%d) - forçando sync", self._current_ticket)
            self._current_ticket = None
            return False

        self._log.warning(
            "Trailing SL modify rejeitado | Retcode: %d | Comment: %s",
            result.retcode,
            result.comment,
        )
        return False

    def get_position_info(self) -> dict:
        if self._current_ticket is None:
            return {"has_position": False}

        return {
            "has_position": True,
            "ticket": self._current_ticket,
            "side": self._current_side.name if self._current_side else "N/A",
            "volume": self._current_volume,
            "entry_price": self._entry_price,
            "pnl": self._current_pnl,
            "duration_ms": (time.time() - self._entry_time) * 1000.0 if self._entry_time > 0 else 0.0,
        }

    def add_realized_pnl(self, pnl: float) -> None:
        self._realized_pnl += pnl
        self._log.info("PnL realizado atualizado: %.2f (trade) | %.2f (acumulado)", pnl, self._realized_pnl)

    @property
    def trade_count(self) -> int:
        return self._trade_count

    @property
    def realized_pnl(self) -> float:
        return self._realized_pnl

    @property
    def current_ticket(self) -> Optional[int]:
        return self._current_ticket

    @property
    def current_side(self) -> Optional[OrderSide]:
        return self._current_side

    @property
    def current_position_type(self) -> int:
        return self._current_position_type

    @property
    def entry_time(self) -> float:
        return self._entry_time
