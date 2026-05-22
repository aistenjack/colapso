import os
import sys
import time
import threading
import signal as signal_mod
from datetime import date
from typing import Optional

from config.settings import Settings
from config.config_loader import load_user_config
from core.logger import Log
from core.mt5_connector import MT5Connector
from core.tick_engine import TickEngine
from core.signal_engine import SignalEngine
from core.execution_engine import ExecutionEngine
from core.risk_engine import RiskEngine
from core.position_manager import PositionManager
from core.watchdog import Watchdog
from core.utils import TickData, Signal, SignalType, TradeStatus, OrderSide, TradeResult
from core.speed_filter import SpeedFilter, SpeedState
from core.micro_structure import MicroStructureEngine
from strategies.momentum_burst import MomentumBurst


class HFTBot:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._log = Log.get("system")
        self._running = False
        self._cycle_count = 0
        self._point: float = 1.0
        self._digits: int = 0
        self._last_close_attempt_time: float = 0.0
        self._current_date: date = date.today()
        self._last_status_time: float = 0.0
        self._daily_reset_pending: bool = False

        self._trade_timestamps: list = []
        self._trade_durations: list = []
        self._slippage_samples: list = []
        self._wins: int = 0
        self._losses: int = 0
        self._last_hft_metrics_time: float = 0.0

        self._last_signal_direction: str = ""
        self._last_signal_price_zone: float = 0.0
        self._last_signal_time_dedup: float = 0.0
        self._signal_dedup_ms: float = 200.0
        self._async_results_lock = threading.Lock()
        self._pending_async_results: list = []

        self._connector = MT5Connector(settings)
        self._tick_engine = TickEngine(settings)
        self._signal_engine = SignalEngine(settings)
        self._execution_engine = ExecutionEngine(settings)
        self._risk_engine = RiskEngine(settings)
        self._position_manager = PositionManager(settings)
        self._watchdog = Watchdog(settings)

        self._strategy = MomentumBurst(settings)
        self._signal_engine.set_strategy(self._strategy)

        self._speed_filter: Optional[SpeedFilter] = None
        if settings.speed_filter.enabled:
            self._speed_filter = SpeedFilter(
                speed_period=settings.speed_filter.speed_period,
                speed_threshold=settings.speed_filter.speed_threshold,
                strength_exhaustion=settings.speed_filter.strength_exhaustion,
                micro_range_window=settings.speed_filter.micro_range_window,
                ema_alpha=settings.speed_filter.ema_alpha,
                speed_clamp=settings.speed_filter.speed_clamp,
                chop_consistency_threshold=settings.speed_filter.chop_consistency_threshold,
                chop_speed_cap_factor=settings.speed_filter.chop_speed_cap_factor,
                neutro_min_strength=settings.speed_filter.neutro_min_strength,
                speed_window_ms=settings.speed_filter.speed_window_ms,
            )

        self._watchdog.set_execution_busy_fn(lambda: self._execution_engine.is_execution_busy)

    def start(self) -> bool:
        self._log.info("=" * 60)
        self._log.info("HFT Bot iniciando...")
        self._log.info("=" * 60)

        if not self._connector.connect():
            self._log.critical("Falha na conexao MT5 - abortando")
            return False

        if not self._init_instrument():
            self._log.critical("Falha ao inicializar instrumento - abortando")
            return False

        self._position_manager.sync_with_mt5()
        self._log.info(
            "Posicao inicial: %s",
            "Nenhuma" if not self._position_manager.has_position() else f"Ticket {self._position_manager.current_ticket}",
        )

        self._watchdog.start()
        self._running = True
        self._log.info("HFT Bot rodando | Symbol: %s | Lot: %.2f | HFT_MODE: %s", self._settings.trading.symbol, self._settings.trading.lot, "ON" if self._settings.hft.enabled else "OFF")
        self._log.info("-" * 60)

        self._main_loop()

        return True

    def stop(self) -> None:
        self._log.info("Parando HFT Bot...")
        self._running = False

    def _init_instrument(self) -> bool:
        info = self._connector.get_symbol_info()
        if info is None:
            return False

        self._point = info.point
        self._digits = info.digits

        self._tick_engine.set_point(self._point)
        self._execution_engine.set_point(self._point)
        self._execution_engine.set_filling_mode(self._connector.filling_mode)

        stops_level = getattr(info, "trade_stops_level", 0) or 0
        freeze_level = getattr(info, "trade_freeze_level", 0) or 0
        min_points = max(stops_level, freeze_level)
        min_stop_dist = min_points * self._point if min_points > 0 else 200 * self._point
        self._execution_engine.set_min_stop_distance(min_stop_dist)
        self._position_manager.set_min_stop_distance(min_stop_dist)

        self._position_manager.set_point(self._point)
        self._strategy.set_instrument_info(self._point, self._digits)
        self._strategy.set_point(self._point)

        self._log.info("Instrumento: %s | Point: %.5f | Digits: %d | Filling: %d", info.name, self._point, self._digits, self._connector.filling_mode)
        return True

    def _main_loop(self) -> None:
        sleep_s = self._settings.system.tick_sleep_ms / 1000.0

        while self._running:
            try:
                self._watchdog.notify_cycle()
                self._cycle_count += 1
                self._drain_async_results()

                if self._watchdog.is_shutdown_requested:
                    self._log.critical("Watchdog solicitou shutdown")
                    break

                today = date.today()
                if today != self._current_date or self._daily_reset_pending:
                    if self._position_manager.has_position():
                        if not self._daily_reset_pending:
                            self._log.warning("Daily reset adiado - posicao aberta | Aguardando fechamento")
                            self._daily_reset_pending = True
                    else:
                        self._risk_engine.reset_daily()
                        self._position_manager.reset_daily()
                        self._watchdog.reset_daily()
                        self._log.info("Daily reset executado | Nova data: %s", today)
                        self._current_date = today
                        self._daily_reset_pending = False

                if self._settings.system.status_report_interval_sec > 0:
                    now = time.time()
                    if now - self._last_status_time >= self._settings.system.status_report_interval_sec:
                        self._report_status()
                        self._last_status_time = now

                if self._settings.hft.enabled and self._settings.hft.metrics_log_interval_sec > 0:
                    now = time.time()
                    if now - self._last_hft_metrics_time >= self._settings.hft.metrics_log_interval_sec:
                        self._report_hft_metrics()
                        self._last_hft_metrics_time = now

                if not self._connector.heartbeat():
                    self._log.warning("Heartbeat falhou - tentando reconexao")
                    if not self._connector.reconnect():
                        self._log.critical("Reconexao falhou - encerrando")
                        break
                    if not self._init_instrument():
                        self._log.critical("Re-init instrumento falhou - encerrando")
                        break
                    continue

                session_ok, session_reason = self._connector.is_session_allowed()
                if not session_ok:
                    if self._position_manager.has_position():
                        self._handle_session_block_with_position()
                    self._log.debug("Sessao bloqueada: %s - aguardando...", session_reason)
                    time.sleep(1.0)
                    continue

                raw_tick = self._connector.get_tick()
                if raw_tick is None:
                    time.sleep(sleep_s)
                    continue

                tick = self._tick_engine.process_tick(raw_tick)
                if tick is None:
                    self._log.debug("[DIAG] Tick processado = None | raw_tick bid=%s ask=%s", getattr(raw_tick, 'bid', '?'), getattr(raw_tick, 'ask', '?'))
                    time.sleep(sleep_s)
                    continue

                self._watchdog.notify_tick()

                if self._settings.reentry.enabled:
                    self._strategy.on_tick(tick)

                if self._cycle_count % 50 == 0:
                    self._log.info("[DIAG] Tick OK | bid=%.0f ask=%.0f spread=%.0f | Buffer: %d ticks | Cycle: %d", tick.bid, tick.ask, tick.spread, self._tick_engine.tick_count, self._cycle_count)
                    self._position_manager.sync_with_mt5()

                self._update_position_side()

                if self._position_manager.has_position():
                    self._check_position_management(tick)

                metrics = self._tick_engine.compute_metrics()
                if not metrics.is_valid:
                    if self._cycle_count % 100 == 0:
                        self._log.info("[DIAG] Metrics invalidos | tick_count=%d / min=%d", self._tick_engine.tick_count, self._settings.tick.min_ticks_for_signal)
                    time.sleep(sleep_s)
                    continue

                if self._cycle_count % 100 == 0:
                    self._log.info(
                        "[DIAG] Metrics | vel=%.2f acc=%.2f micro_range=%.1f spread=%.0f delta=%.0f avg_vel=%.2f",
                        metrics.velocity, metrics.acceleration, metrics.micro_range,
                        metrics.spread, metrics.delta, metrics.avg_velocity)

                if self._speed_filter is not None:
                    sf = self._speed_filter.evaluate(
                        self._tick_engine, tick, metrics)
                    if self._settings.reentry.enabled:
                        self._strategy.set_speed_state(sf.state.name)
                    if not sf.allowed:
                        if self._cycle_count % 100 == 0:
                            self._log.info(
                                "[SPEED FILTER] estado=%s speed=%.1f"
                                " strength=%.3f dir_consistency=%.2f"
                                " accel=%.1f blocked=%s",
                                sf.state.name, sf.speed, sf.strength,
                                sf.directional_consistency, sf.accel,
                                sf.blocked_reason)
                        time.sleep(sleep_s)
                        continue

                sig = self._signal_engine.evaluate(tick, metrics)
                if sig.signal_type == SignalType.NONE:
                    time.sleep(sleep_s)
                    continue

                self._position_manager.sync_with_mt5()
                self._update_position_side()
                self._handle_signal(sig, tick)

            except KeyboardInterrupt:
                self._log.info("KeyboardInterrupt recebido")
                break
            except Exception as e:
                self._log.error("Erro no loop principal: %s", e, exc_info=True)
                self._risk_engine.register_execution_error()
                time.sleep(1.0)

        self._shutdown()

    def _handle_signal(self, signal: Signal, tick: TickData) -> None:
        latency_ms = self._risk_engine.get_status()["avg_latency_ms"]

        if signal.signal_type == SignalType.CLOSE:
            if self._position_manager.has_position():
                self._execute_close(signal)
            return

        if signal.signal_type not in (SignalType.BUY, SignalType.SELL):
            return

        if self._execution_engine.is_execution_busy:
            self._log.info("[SIGNAL BLOCKED] reason=execution_in_progress")
            return

        if self._risk_engine.is_in_risk_cooldown():
            remaining = 2.0 - (time.time() - self._risk_engine.last_risk_block_time) if self._risk_engine.last_risk_block_time > 0 else 0.0
            self._log.info("[SIGNAL BLOCKED] reason=risk_cooldown remaining=%.1fs", remaining)
            return

        if self._is_duplicate_signal(signal, tick):
            return

        if self._position_manager.has_position():
            current_side = self._position_manager.current_side
            signal_side = OrderSide.BUY if signal.signal_type == SignalType.BUY else OrderSide.SELL

            if current_side == signal_side:
                return

            if not self._settings.position.allow_reversal:
                self._execute_close(Signal(signal_type=SignalType.CLOSE, reason="reversal_blocked", strength=1.0))
                time.sleep(0.1)
                if self._position_manager.has_position():
                    return

        risk_ok, risk_reason = self._risk_engine.check_pre_trade(tick, self._point, latency_ms)
        if not risk_ok:
            self._log.info("[SIGNAL BLOCKED] reason=risk_block detail=%s latency=%.1fms", risk_reason, latency_ms)
            self._risk_engine.mark_risk_blocked()
            self._strategy.notify_risk_blocked()
            return

        close_signal = self._risk_engine.check_close_signal(self._position_manager.get_current_pnl())
        if close_signal is not None:
            self._execute_close(close_signal)
            return

        self._risk_engine.register_trade_attempt()
        self._record_signal_dedup(signal, tick)

        def _on_execution_complete(result: TradeResult, sig: Signal) -> None:
            payload = {
                "type": "open",
                "result": result,
                "signal": sig,
                "timestamp": time.time(),
            }
            with self._async_results_lock:
                self._pending_async_results.append(payload)

        self._execution_engine.execute_signal_async(signal, callback=_on_execution_complete)

    def _is_duplicate_signal(self, signal: Signal, tick: TickData) -> bool:
        if self._last_signal_time_dedup <= 0:
            return False
        elapsed_ms = (time.time() - self._last_signal_time_dedup) * 1000.0
        if elapsed_ms > self._signal_dedup_ms:
            return False
        direction = signal.signal_type.name
        if direction != self._last_signal_direction:
            return False
        price_zone = round(tick.mid / (self._point * 10.0)) if self._point > 0 else 0.0
        if price_zone != self._last_signal_price_zone:
            return False
        return True

    def _record_signal_dedup(self, signal: Signal, tick: TickData) -> None:
        self._last_signal_time_dedup = time.time()
        self._last_signal_direction = signal.signal_type.name
        self._last_signal_price_zone = round(tick.mid / (self._point * 10.0)) if self._point > 0 else 0.0

    def _drain_async_results(self) -> None:
        with self._async_results_lock:
            items = list(self._pending_async_results)
            self._pending_async_results.clear()

        for item in items:
            try:
                if item["type"] == "open":
                    self._process_async_open(item["result"], item["signal"])
            except Exception as e:
                self._log.error("[ASYNC DRAIN] erro processando resultado: %s", e)

    def _process_async_open(self, result: TradeResult, sig: Signal) -> None:
        self._risk_engine.record_latency(result.latency_ms)
        if result.status == TradeStatus.SUCCESS:
            self._position_manager.register_open(result, sig)
            self._risk_engine.register_execution_success()
            self._strategy.notify_trade_time()
            self._trade_timestamps.append(time.time())
            if result.slippage != 0.0:
                self._slippage_samples.append(result.slippage)
            self._log.info(
                "TRADE ABERTO | Ticket: %d | Side: %s | PnL acumulado: %.2f | Latencia: %.1fms",
                result.ticket,
                result.side.name if result.side else "?",
                self._risk_engine.daily_pnl,
                result.latency_ms,
            )
        else:
            self._risk_engine.register_execution_error()

    def _execute_close(self, signal: Signal) -> None:
        if not self._position_manager.has_position():
            return

        is_urgent = signal.reason in ("session_block", "shutdown", "daily_loss_limit", "loss_exit", "loss_max")

        if not is_urgent:
            cooldown_ms = 500.0
            elapsed = (time.time() - self._last_close_attempt_time) * 1000.0
            if elapsed < cooldown_ms:
                return

        self._position_manager.sync_with_mt5()
        if not self._position_manager.has_position():
            pnl = self._position_manager.consume_last_known_pnl()
            if pnl != 0.0:
                self._position_manager.add_realized_pnl(pnl)
                self._risk_engine.check_post_trade(pnl)
                self._strategy.notify_close_pnl(pnl)
                self._log.info(
                    "POSICAO FECHADA PELO BROKER | PnL: %.2f | Daily: %.2f | Consec losses: %d",
                    pnl,
                    self._risk_engine.daily_pnl,
                    self._risk_engine.consecutive_losses,
                )
            return

        ticket = self._position_manager.current_ticket
        volume = self._position_manager.get_position_info().get("volume", self._settings.trading.lot)
        position_type = self._position_manager.current_position_type

        self._last_close_attempt_time = time.time()
        result = self._execution_engine.close_position(
            self._settings.trading.symbol,
            ticket or 0,
            volume,
            position_type,
        )

        self._risk_engine.record_latency(result.latency_ms)

        if result.status == TradeStatus.SUCCESS:
            pnl = self._position_manager.get_current_pnl()
            pos_info = self._position_manager.get_position_info()
            duration_s = pos_info.get("duration_ms", 0.0) / 1000.0
            self._trade_durations.append(duration_s)
            if pnl >= 0:
                self._wins += 1
            else:
                self._losses += 1
            self._position_manager.add_realized_pnl(pnl)
            self._risk_engine.check_post_trade(pnl)
            self._position_manager.register_close(result)
            self._risk_engine.register_execution_success()
            self._strategy.notify_close_pnl(pnl)
            self._log.info(
                "POSICAO FECHADA | PnL trade: %.2f | Daily PnL: %.2f | Consec losses: %d | Hold: %.1fs",
                pnl,
                self._risk_engine.daily_pnl,
                self._risk_engine.consecutive_losses,
                duration_s,
            )
        else:
            self._risk_engine.register_execution_error()

    def _check_position_management(self, tick: TickData) -> None:
        if not self._position_manager.has_position():
            return

        if self._position_manager.should_close_timeout():
            self._log.warning("Trade timeout atingido - fechando posicao")
            self._execute_close(Signal(signal_type=SignalType.CLOSE, reason="trade_timeout", strength=1.0))
            return

        pnl_signal = self._position_manager.should_close_pnl()
        if pnl_signal is not None:
            self._execute_close(pnl_signal)
            return

        virtual_signal = self._position_manager.check_virtual_trailing(tick.bid, tick.ask)
        if virtual_signal is not None:
            self._execute_close(virtual_signal)
            return

        self._position_manager.check_trailing_stop(tick.bid, tick.ask)

    def _update_position_side(self) -> None:
        if self._position_manager.has_position():
            self._strategy.set_position_side(self._position_manager.current_side)
        else:
            last_tick = self._tick_engine.last_tick
            close_px = last_tick.mid if last_tick else 0.0
            self._strategy.set_position_side(None, close_price=close_px)

    def _report_status(self) -> None:
        try:
            risk = self._risk_engine.get_status()
            pos = self._position_manager.current_side.name if self._position_manager.current_side else "NONE"
            ticket = self._position_manager.current_ticket or 0
            float_pnl = self._position_manager.get_current_pnl()
            snap = self._connector.get_account_snapshot()
            self._log.info(
                "STATUS | %s | Tkt: %d | Pos: %s | FloatPnL: %.2f | DailyPnL: %.2f | Bal: %.2f | Eq: %.2f | MrgFree: %.2f | MrgUsed: %.2f | AccPnL: %.2f | MLvl: %.1f%% | Lat: %.1fms | Errs: %d | ConsecLoss: %d | Trading: %s | CB: %s | Disconn: %d",
                self._settings.trading.symbol, ticket, pos, float_pnl,
                risk["daily_pnl"], snap["balance"], snap["equity"],
                snap["margin_free"], snap["margin_used"], snap["floating_pnl"],
                snap["margin_level"], risk["avg_latency_ms"],
                risk["consecutive_errors"], risk["consecutive_losses"],
                "ON" if risk["trading_enabled"] else "OFF",
                "YES" if risk["circuit_breaker_active"] else "no",
                self._watchdog.disconnect_count,
            )
        except Exception as e:
            self._log.error("Status report falhou: %s", e)

    def _report_hft_metrics(self) -> None:
        try:
            now = time.time()
            trades_last_min = sum(1 for t in self._trade_timestamps if now - t < 60.0)
            total_trades = self._wins + self._losses
            winrate = (self._wins / total_trades * 100.0) if total_trades > 0 else 0.0
            avg_hold = (sum(self._trade_durations[-50:]) / len(self._trade_durations[-50:])) if self._trade_durations else 0.0
            avg_lat = self._risk_engine.get_status()["avg_latency_ms"]
            avg_slip = (sum(self._slippage_samples[-50:]) / len(self._slippage_samples[-50:])) if self._slippage_samples else 0.0
            sf_stats = ""
            if self._speed_filter is not None:
                m = self._speed_filter.get_metrics_summary()
                sf_stats = (
                    " | sf_reject=" + m['filter_rejection_rate'] +
                    " sf_eval=" + str(m['total_evaluations']) +
                    " sf_lento=" + str(m['blocked_lento']) +
                    " sf_exhaust=" + str(m['blocked_exhaustao']) +
                    " sf_chop=" + str(m['blocked_chop']))
            reentry_stats = ""
            if self._settings.reentry.enabled:
                d = self._strategy._reentry_engine.get_diagnostics()
                reentry_stats = (
                    " | reentry_thresh=" + d['threshold_current'] +
                    " reentry_tpm=" + d['trades_per_min'])
            self._log.info(
                "[HFT METRICS] trades_last_minute=%d"
                " avg_latency_ms=%.1f winrate_session=%.0f%%"
                " avg_hold_seconds=%.1f avg_slippage_ticks=%.1f"
                " total_wins=%d total_losses=%d%s%s",
                trades_last_min, avg_lat, winrate, avg_hold,
                avg_slip, self._wins, self._losses, sf_stats, reentry_stats,
            )
        except Exception as e:
            self._log.error("HFT metrics report falhou: %s", e)

    def _handle_session_block_with_position(self) -> None:
        self._log.warning("Sessao bloqueada com posicao aberta - forcando fechamento")
        self._execute_close(Signal(signal_type=SignalType.CLOSE, reason="session_block", strength=1.0))
        time.sleep(0.5)

    def _shutdown(self) -> None:
        self._log.info("=" * 60)
        self._log.info("HFT Bot desligando...")
        self._log.info("=" * 60)

        self._running = False
        self._watchdog.stop()
        self._execution_engine.shutdown()

        if self._position_manager.has_position():
            self._log.warning("Posicao ainda aberta no shutdown - fechando...")
            self._execute_close(Signal(signal_type=SignalType.CLOSE, reason="shutdown", strength=1.0))
            time.sleep(0.5)

        self._connector.shutdown()

        status = self._get_final_status()
        self._log.info("-" * 60)
        for key, value in status.items():
            self._log.info(" %s: %s", key, value)
        self._log.info("-" * 60)
        self._log.info("HFT Bot finalizado")

        Log.shutdown()

    def _get_final_status(self) -> dict:
        risk_status = self._risk_engine.get_status()
        snap = self._connector.get_account_snapshot()
        sf_info = ""
        if self._speed_filter is not None:
            m = self._speed_filter.get_metrics_summary()
            sf_info = "sf_reject=" + m['filter_rejection_rate']
        return {
            "cycles": self._cycle_count,
            "trades": self._position_manager.trade_count,
            "realized_pnl": f"{self._position_manager.realized_pnl:.2f}",
            "daily_pnl": f"{risk_status['daily_pnl']:.2f}",
            "consecutive_losses": risk_status["consecutive_losses"],
            "trading_enabled": risk_status["trading_enabled"],
            "balance": f"{snap['balance']:.2f}",
            "equity": f"{snap['equity']:.2f}",
            "margin_free": f"{snap['margin_free']:.2f}",
            "margin_level": f"{snap['margin_level']:.1f}%",
            "disconnects": self._watchdog.disconnect_count,
            "freeze_count": self._watchdog.freeze_count,
            "speed_filter": sf_info,
        }


def main() -> None:
    settings = Settings()
    Log.setup(log_dir="logs")

    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "user_config.json")
    settings = load_user_config(config_path, settings)

    bot = HFTBot(settings)

    def _signal_handler(signum, frame) -> None:
        bot.stop()

    signal_mod.signal(signal_mod.SIGINT, _signal_handler)
    signal_mod.signal(signal_mod.SIGTERM, _signal_handler)

    if not bot.start():
        sys.exit(1)


if __name__ == "__main__":
    main()
