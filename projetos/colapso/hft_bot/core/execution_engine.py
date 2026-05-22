import time
import threading
import MetaTrader5 as mt5
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Optional

from core.logger import Log
from core.utils import Signal, TradeResult, TradeStatus, SignalType, OrderSide, elapsed_ms
from config.settings import Settings, TradingSettings


class ExecutionEngine:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._trade_cfg: TradingSettings = settings.trading
        self._log = Log.get("execution")
        self._lock = threading.Lock()
        self._last_order_time: float = 0.0
        self._order_count: int = 0
        self._consecutive_errors: int = 0
        self._point: float = 1.0
        self._filling_mode: int = 0
        self._execution_busy: bool = False
        self._execution_busy_lock: threading.Lock = threading.Lock()
        self._min_stop_distance: float = 0.0
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hft_exec")
        self._pending_future: Optional[Future] = None

    def set_point(self, point: float) -> None:
        self._point = point

    def set_filling_mode(self, filling_mode: int) -> None:
        self._filling_mode = filling_mode

    def set_min_stop_distance(self, distance: float) -> None:
        self._min_stop_distance = distance
        self._log.info("[STOP CONFIG] min_stop_distance=%.5f (%d points)", distance, int(distance / self._point) if self._point > 0 else 0)

    @property
    def is_execution_busy(self) -> bool:
        with self._execution_busy_lock:
            return self._execution_busy

    def execute_signal(self, signal: Signal) -> TradeResult:
        if signal.signal_type == SignalType.NONE:
            return TradeResult(status=TradeStatus.REJECTED, message="Sinal vazio")

        with self._lock:
            if signal.signal_type == SignalType.CLOSE:
                return self._close_position(signal)

            start_time = time.time()
            side = OrderSide.BUY if signal.signal_type == SignalType.BUY else OrderSide.SELL

            self._log.info(
                "[EXEC] Executando %s | Entry: %.2f | SL: %.2f | TP: %.2f | Strength: %.2f | Reason: %s",
                side.name,
                signal.entry_price,
                signal.stop_loss,
                signal.take_profit,
                signal.strength,
                signal.reason,
            )

            request = self._build_request(signal, side)

            result = self._send_order_with_fallback(request, side)
            result.latency_ms = elapsed_ms(start_time)

            self._last_order_time = time.time()
            self._order_count += 1

            if result.status == TradeStatus.SUCCESS:
                self._consecutive_errors = 0
                slip_ticks = self._calc_slippage_ticks(result, request, side)
                result.slippage = slip_ticks
                self._log.info(
                    "[EXEC] ORDEM EXECUTADA | Ticket: %d | Preço: %.2f | Latência: %.1fms | Slip: %d ticks",
                    result.ticket,
                    result.price,
                    result.latency_ms,
                    int(slip_ticks),
                )
            else:
                self._consecutive_errors += 1
                self._log.error(
                    "[EXEC] ORDEM REJEITADA | Status: %s | Msg: %s | Latência: %.1fms | Erros consec: %d",
                    result.status.name,
                    result.message,
                    result.latency_ms,
                    self._consecutive_errors,
                )

            return result

    def execute_signal_async(self, signal: Signal, callback=None) -> None:
        with self._execution_busy_lock:
            if self._execution_busy:
                self._log.info("[EXECUTION ASYNC] worker_busy=yes — descartando signal (já executando)")
                return
            self._execution_busy = True

        def _worker():
            try:
                result = self.execute_signal(signal)
                if callback is not None:
                    callback(result, signal)
            except Exception as e:
                self._log.error("[EXECUTION ASYNC] erro no worker: %s", e)
            finally:
                with self._execution_busy_lock:
                    self._execution_busy = False

        self._worker.submit(_worker)
        self._log.info("[EXECUTION ASYNC] queue_size=1 worker_busy=yes signal=%s", signal.signal_type.name)

    def close_position(self, symbol: str, ticket: int, volume: float, position_type: int) -> TradeResult:
        with self._lock:
            start_time = time.time()

            if position_type == mt5.POSITION_TYPE_BUY:
                close_order_type = mt5.ORDER_TYPE_SELL
                close_price = mt5.symbol_info_tick(symbol).bid
                close_side = OrderSide.SELL
            else:
                close_order_type = mt5.ORDER_TYPE_BUY
                close_price = mt5.symbol_info_tick(symbol).ask
                close_side = OrderSide.BUY

            self._log.info(
                "Fechando posição | Ticket: %d | Volume: %.2f | Tipo: %s",
                ticket,
                volume,
                "BUY->SELL" if position_type == mt5.POSITION_TYPE_BUY else "SELL->BUY",
            )

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": close_order_type,
                "position": ticket,
                "price": close_price,
                "deviation": self._trade_cfg.deviation,
                "magic": self._trade_cfg.magic_number,
                "comment": "HFT_CLOSE",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": self._filling_mode,
            }

            result = self._send_order_with_fallback(request, close_side)
            result.latency_ms = elapsed_ms(start_time)

            if result.status == TradeStatus.SUCCESS:
                self._consecutive_errors = 0
                self._log.info(
                    "POSIÇÃO FECHADA | Ticket: %d | Preço: %.2f | Latência: %.1fms",
                    ticket,
                    result.price,
                    result.latency_ms,
                )
            else:
                self._consecutive_errors += 1
                self._log.error(
                    "FALHA AO FECHAR | Ticket: %d | Msg: %s | Erros consec: %d",
                    ticket,
                    result.message,
                    self._consecutive_errors,
                )

            return result

    def _build_request(self, signal: Signal, side: OrderSide) -> dict:
        order_type = mt5.ORDER_TYPE_BUY if side == OrderSide.BUY else mt5.ORDER_TYPE_SELL
        tick = mt5.symbol_info_tick(self._trade_cfg.symbol)
        price = tick.ask if side == OrderSide.BUY else tick.bid

        sl = signal.stop_loss
        tp = signal.take_profit

        sl, tp, adjusted = self._validate_stops(price, sl, tp, side)

        if adjusted:
            self._log.info(
                "[STOP VALIDATION] entry=%.2f requested_sl=%.2f requested_tp=%.2f min_distance=%.5f adjusted=yes final_sl=%.2f final_tp=%.2f",
                price, signal.stop_loss, signal.take_profit, self._min_stop_distance, sl, tp,
            )
        else:
            self._log.info(
                "[STOP VALIDATION] entry=%.2f sl=%.2f tp=%.2f min_distance=%.5f adjusted=no",
                price, sl, tp, self._min_stop_distance,
            )

        return {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self._trade_cfg.symbol,
            "volume": self._trade_cfg.lot,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": self._trade_cfg.deviation,
            "magic": self._trade_cfg.magic_number,
            "comment": "HFT_MOMENTUM",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling_mode,
        }

    def _validate_stops(self, entry: float, sl: float, tp: float, side: OrderSide) -> tuple[float, float, bool]:
        adjusted = False
        min_dist = self._min_stop_distance

        if min_dist <= 0:
            info = mt5.symbol_info(self._trade_cfg.symbol)
            if info is not None:
                stops_level = getattr(info, "trade_stops_level", 0) or 0
                freeze_level = getattr(info, "trade_freeze_level", 0) or 0
                min_points = max(stops_level, freeze_level)
                min_dist = min_points * self._point
                if min_dist > 0:
                    self._min_stop_distance = min_dist
                    self._log.info(
                        "[STOP CONFIG] Auto-detectado stops_level=%d freeze_level=%d min_distance=%.5f (%d points)",
                        stops_level, freeze_level, min_dist, min_points,
                    )

        if min_dist <= 0:
            min_dist = 200 * self._point
            self._min_stop_distance = min_dist
            self._log.warning(
                "[STOP CONFIG] Fallback min_distance=%.5f (200 points) — broker não reportou stops_level",
                min_dist,
            )

        if side == OrderSide.BUY:
            min_sl = entry - min_dist
            if sl > min_sl:
                sl = min_sl
                adjusted = True
            if tp > 0:
                min_tp = entry + min_dist
                if tp < min_tp:
                    tp = min_tp
                    adjusted = True
        else:
            max_sl = entry + min_dist
            if sl < max_sl and sl > 0:
                sl = max_sl
                adjusted = True
            if tp > 0:
                max_tp = entry - min_dist
                if tp > max_tp:
                    tp = max_tp
                    adjusted = True

        return sl, tp, adjusted

    def _send_order_with_fallback(self, request: dict, side: OrderSide) -> TradeResult:
        result = self._send_order(request, side)
        if result.status in (TradeStatus.SUCCESS,):
            return result

        retcode_str = result.message or ""

        if "10030" in retcode_str:
            self._log.warning(
                "Filling mode rejeitado (10030) — tentando fallback IOC → FOK → RETURN"
            )
            filling_modes = [
                mt5.ORDER_FILLING_IOC,
                mt5.ORDER_FILLING_FOK,
                mt5.ORDER_FILLING_RETURN,
            ]
            for fill_mode in filling_modes:
                if fill_mode == request.get("type_filling"):
                    continue

                request["type_filling"] = fill_mode
                self._log.info(
                    "[FILLING FALLBACK] Tentando type_filling=%d", fill_mode
                )
                result = self._send_order(request, side)
                if result.status == TradeStatus.SUCCESS:
                    self._log.info(
                        "[FILLING FALLBACK] Sucesso com type_filling=%d", fill_mode
                    )
                    return result

        if "10016" in retcode_str:
            self._log.warning(
                "[STOPS FALLBACK] Invalid stops (10016) — reenviando SEM SL/TP"
            )
            no_stops_request = dict(request)
            no_stops_request["sl"] = 0.0
            no_stops_request["tp"] = 0.0
            result_no_stops = self._send_order(no_stops_request, side)
            if result_no_stops.status == TradeStatus.SUCCESS:
                self._log.info(
                    "[STOPS FALLBACK] Ordem aceita sem SL/TP | Ticket: %d — modificando stops via SLTP",
                    result_no_stops.ticket,
                )
                self._modify_stops_after_fill(result_no_stops.ticket, request, side)
                return result_no_stops
            self._log.error("[STOPS FALLBACK] Ordem sem SL/TP também rejeitada: %s", result_no_stops.message)

        return result

    def _modify_stops_after_fill(self, ticket: int, original_request: dict, side: OrderSide) -> None:
        sl = original_request.get("sl", 0.0)
        tp = original_request.get("tp", 0.0)
        if sl == 0.0 and tp == 0.0:
            return

        modify_request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": self._trade_cfg.symbol,
            "position": ticket,
            "sl": sl,
            "tp": tp,
        }

        for attempt in range(3):
            result = mt5.order_send(modify_request)
            if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
                self._log.info(
                    "[STOPS FALLBACK] SLTP modificado com sucesso | Ticket: %d | SL: %.2f | TP: %.2f",
                    ticket, sl, tp,
                )
                return
            self._log.warning(
                "[STOPS FALLBACK] SLTP modify tentativa %d falhou | retcode=%s",
                attempt + 1,
                result.retcode if result else "None",
            )
            time.sleep(0.1)

        self._log.error("[STOPS FALLBACK] Falhou todas tentativas de modificar SLTP | Ticket: %d", ticket)

    def _send_order(self, request: dict, side: OrderSide) -> TradeResult:
        self._log.info(
            "[ORDER DEBUG] type=%s volume=%.2f price=%.2f sl=%.2f tp=%.2f filling=%d symbol=%s",
            "BUY" if request.get("type") == mt5.ORDER_TYPE_BUY else "SELL",
            request.get("volume", 0.0),
            request.get("price", 0.0),
            request.get("sl", 0.0),
            request.get("tp", 0.0),
            request.get("type_filling", -1),
            request.get("symbol", ""),
        )
        max_retries = 3
        for attempt in range(max_retries):
            result = mt5.order_send(request)

            if result is None:
                err = mt5.last_error()
                self._log.error("order_send retornou None | Err: %s | Attempt: %d", err, attempt + 1)
                if attempt < max_retries - 1:
                    time.sleep(0.05)
                    continue
                return TradeResult(
                    status=TradeStatus.FAILED,
                    side=side,
                    message=f"order_send None: {err}",
                )

            retcode = result.retcode
            self._log.info(
                "[ORDER RESULT] retcode=%d comment=%s ticket=%d price=%.2f volume=%.2f",
                retcode,
                result.comment,
                result.order,
                result.price,
                result.volume,
            )

            if retcode == mt5.TRADE_RETCODE_DONE:
                return TradeResult(
                    status=TradeStatus.SUCCESS,
                    ticket=result.order,
                    price=result.price,
                    volume=result.volume,
                    side=side,
                    slippage=0.0,
                    message="OK",
                )

            if retcode == mt5.TRADE_RETCODE_DONE_PARTIAL:
                self._log.warning("Execução parcial: %d", retcode)
                return TradeResult(
                    status=TradeStatus.SUCCESS,
                    ticket=result.order,
                    price=result.price,
                    volume=result.volume,
                    side=side,
                    message=f"Parcial: {retcode}",
                )

            if retcode in (mt5.TRADE_RETCODE_REQUOTE, mt5.TRADE_RETCODE_PRICE_OFF):
                self._log.warning("Requote/Price off: %d - refresh preço", retcode)
                tick = mt5.symbol_info_tick(request["symbol"])
                if tick is not None:
                    if request["type"] == mt5.ORDER_TYPE_BUY:
                        request["price"] = tick.ask
                    else:
                        request["price"] = tick.bid
                continue

            if retcode == mt5.TRADE_RETCODE_FROZEN:
                self._log.error("Mercado congelado / fora de horário: %d", retcode)
                return TradeResult(
                    status=TradeStatus.REJECTED,
                    side=side,
                    message=f"Mercado fechado/frozen: {retcode}",
                )

            self._log.error(
                "Order rejeitada | Retcode: %d | Comment: %s",
                retcode,
                result.comment,
            )
            return TradeResult(
                status=TradeStatus.REJECTED,
                side=side,
                message=f"Retcode {retcode}: {result.comment}",
            )

        return TradeResult(
            status=TradeStatus.FAILED,
            side=side,
            message="Max retries excedido",
        )

    def _close_position(self, signal: Signal) -> TradeResult:
        positions = mt5.positions_get(symbol=self._trade_cfg.symbol)
        if not positions:
            return TradeResult(status=TradeStatus.REJECTED, message="Sem posição para fechar")

        pos = positions[0]
        return self.close_position(pos.symbol, pos.ticket, pos.volume, pos.type)

    def _calc_slippage_ticks(self, result: TradeResult, request: dict, side: OrderSide) -> float:
        requested = request.get("price", 0.0)
        filled = result.price
        if requested <= 0:
            return 0.0

        if side == OrderSide.BUY:
            raw_slip = filled - requested
        else:
            raw_slip = requested - filled

        if self._point > 0:
            return raw_slip / self._point
        return raw_slip

    @property
    def last_order_time(self) -> float:
        return self._last_order_time

    @property
    def order_count(self) -> int:
        return self._order_count

    @property
    def consecutive_errors(self) -> int:
        return self._consecutive_errors

    def reset_errors(self) -> None:
        self._consecutive_errors = 0

    def shutdown(self) -> None:
        self._worker.shutdown(wait=False)
