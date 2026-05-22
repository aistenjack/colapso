import time
import threading
import MetaTrader5 as mt5
from typing import Optional, Callable

from core.logger import Log
from config.settings import Settings, SystemSettings


class Watchdog:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._sys_cfg: SystemSettings = settings.system
        self._log = Log.get("system")
        self._last_tick_time: float = time.time()
        self._last_cycle_time: float = time.time()
        self._freeze_threshold_ms: float = 3000.0
        self._running: bool = False
        self._shutdown_event: threading.Event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._disconnect_count: int = 0
        self._freeze_count: int = 0
        self._execution_busy_fn: Optional[Callable[[], bool]] = None
        self._max_execution_dead_tick_s: float = 20.0

    def set_execution_busy_fn(self, fn: Callable[[], bool]) -> None:
        self._execution_busy_fn = fn

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._shutdown_event.clear()
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        self._log.info("Watchdog iniciado | Tick timeout: %dms", self._sys_cfg.watchdog_tick_timeout_ms)

    def stop(self) -> None:
        self._running = False
        self._shutdown_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._log.info("Watchdog parado")

    def notify_tick(self) -> None:
        self._last_tick_time = time.time()

    def notify_cycle(self) -> None:
        self._last_cycle_time = time.time()

    @property
    def is_shutdown_requested(self) -> bool:
        return self._shutdown_event.is_set()

    @property
    def disconnect_count(self) -> int:
        return self._disconnect_count

    @property
    def freeze_count(self) -> int:
        return self._freeze_count

    def check_tick_timeout(self) -> bool:
        elapsed_ms = (time.time() - self._last_tick_time) * 1000.0
        return elapsed_ms > self._sys_cfg.watchdog_tick_timeout_ms

    def check_cycle_freeze(self) -> bool:
        elapsed_ms = (time.time() - self._last_cycle_time) * 1000.0
        return elapsed_ms > self._freeze_threshold_ms

    def request_shutdown(self, reason: str) -> None:
        if self._shutdown_event.is_set():
            return
        self._shutdown_event.set()
        self._log.critical("WATCHDOG SHUTDOWN | Motivo: %s", reason)

    def reset_daily(self) -> None:
        self._disconnect_count = 0
        self._freeze_count = 0

    def _is_execution_busy(self) -> bool:
        if self._execution_busy_fn is not None:
            return self._execution_busy_fn()
        return False

    def _is_terminal_alive(self) -> bool:
        try:
            terminal = mt5.terminal_info()
            if terminal is not None and terminal.connected:
                account = mt5.account_info()
                return account is not None
        except Exception:
            pass
        return False

    def _monitor_loop(self) -> None:
        check_interval = max(1.0, self._sys_cfg.watchdog_tick_timeout_ms / 1000.0 / 2.0)

        while self._running:
            time.sleep(check_interval)
            if not self._running:
                break

            if self.check_tick_timeout():
                tick_age_s = time.time() - self._last_tick_time
                exec_busy = self._is_execution_busy()
                terminal_alive = self._is_terminal_alive()

                self._log.critical(
                    "[WATCHDOG] tick_age=%.1fs execution_busy=%s terminal_alive=%s disconnect_count=%d",
                    tick_age_s,
                    "yes" if exec_busy else "no",
                    "yes" if terminal_alive else "no",
                    self._disconnect_count,
                )

                if exec_busy and tick_age_s < self._max_execution_dead_tick_s:
                    self._log.info(
                        "[WATCHDOG] Dead tick ignorado — ordem em execução (age=%.1fs < max=%.1fs)",
                        tick_age_s, self._max_execution_dead_tick_s,
                    )
                    continue

                if terminal_alive:
                    if tick_age_s < 120.0:
                        self._log.info(
                            "[WATCHDOG] Dead tick tolerado — terminal vivo, aguardando mercado (age=%.1fs)",
                            tick_age_s,
                        )
                        continue
                    else:
                        self._log.critical(
                            "[WATCHDOG] Sem tick há %.1fs — terminal vivo mas mercado pode estar fechado. Continuando.",
                            tick_age_s,
                        )
                        self._last_tick_time = time.time()
                        continue

                self._disconnect_count += 1
                self._log.critical(
                    "DEAD TICK | Sem tick há %.1fs (limite: %dms) | Contagem: %d | terminal_alive=%s",
                    tick_age_s,
                    self._sys_cfg.watchdog_tick_timeout_ms,
                    self._disconnect_count,
                    "yes" if terminal_alive else "no",
                )
                if self._disconnect_count >= 3:
                    self.request_shutdown("dead_tick_persistent")
                    break

            if self.check_cycle_freeze():
                self._freeze_count += 1
                self._log.warning(
                    "FREEZE DETECTADO | Ciclo parado há %.1fms | Contagem: %d/%d",
                    (time.time() - self._last_cycle_time) * 1000.0,
                    self._freeze_count,
                    5,
                )
                if self._freeze_count >= 10:
                    self.request_shutdown("excessive_freeze")
                    break
