import MetaTrader5 as mt5
import os
import time
from datetime import datetime
from typing import Dict, Optional

from core.logger import Log
from core.utils import now_ms
from config.settings import Settings, MT5Settings


class MT5Connector:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._mt5_settings: MT5Settings = settings.mt5
        self._log = Log.get("system")
        self._connected: bool = False
        self._symbol_info: Optional[mt5.SymbolInfo] = None
        self._last_heartbeat: float = 0.0
        self._account_info: Optional[mt5.AccountInfo] = None
        self._account_snapshot: Dict[str, float] = {}
        self._last_account_refresh: float = 0.0
        self._filling_mode: int = 0

    @property
    def is_connected(self) -> bool:
        return self._connected and mt5.terminal_info() is not None

    @property
    def filling_mode(self) -> int:
        return self._filling_mode

    def connect(self) -> bool:
        self._log.info("Conectando ao MetaTrader 5...")

        init_path = self._mt5_settings.terminal_path or self._mt5_settings.path
        if init_path:
            if not os.path.isfile(init_path):
                self._log.error("Terminal path inválido: %s — arquivo não encontrado", init_path)
                return self._handle_init_failure()
            self._log.info("Terminal path: %s", init_path)
            if not mt5.initialize(path=init_path):
                return self._handle_init_failure()
        else:
            if not mt5.initialize():
                return self._handle_init_failure()

        if self._mt5_settings.login:
            if not mt5.login(
                login=self._mt5_settings.login,
                password=self._mt5_settings.password,
                server=self._mt5_settings.server,
            ):
                self._log.error("Falha no login MT5: %s", mt5.last_error())
                mt5.shutdown()
                return False

        terminal = mt5.terminal_info()
        if terminal is None:
            self._log.error("Terminal info indisponível")
            mt5.shutdown()
            return False

        if not terminal.connected:
            self._log.error("Terminal não está conectado ao servidor")
            mt5.shutdown()
            return False

        account = mt5.account_info()
        if account is None:
            self._log.error("Não foi possível obter info da conta")
            mt5.shutdown()
            return False

        margin_mode = getattr(account, "margin_mode", None)
        if margin_mode is None:
            margin_mode = getattr(account, "account_type", None)

        is_netting = False
        if margin_mode is not None:
            try:
                is_netting = margin_mode == mt5.ACCOUNT_MARGIN_MODE_RETAIL_NETTING
            except AttributeError:
                try:
                    is_netting = margin_mode in (
                        mt5.ACCOUNT_MARGIN_MODE_RETAIL_NETTING,
                        mt5.ACCOUNT_MARGIN_MODE_EXCHANGE_NETTING,
                    )
                except AttributeError:
                    is_netting = margin_mode == 2

        if not is_netting:
            self._log.error(
                "Conta NÃO é NETTING! margin_mode=%s. Este bot requer conta NETTING.",
                margin_mode,
            )
            mt5.shutdown()
            return False

        self._account_info = account
        self._log.info(
            "Conectado: Conta %d | Servidor: %s | Saldo: %.2f | Modo: NETTING",
            account.login,
            account.server,
            account.balance,
        )

        if not self._validate_symbol():
            mt5.shutdown()
            return False

        self._connected = True
        self._last_heartbeat = time.time()
        self._log.info("MT5 Connector inicializado com sucesso")
        return True

    def reconnect(self) -> bool:
        self._log.info("Tentando reconexão MT5...")
        self._connected = False
        mt5.shutdown()
        time.sleep(1.0)

        attempts = self._settings.system.reconnect_attempts
        delay = self._settings.system.reconnect_delay_ms / 1000.0

        for i in range(attempts):
            self._log.info("Tentativa %d/%d...", i + 1, attempts)
            if self.connect():
                return True
            time.sleep(delay)

        self._log.critical("Falha em todas as tentativas de reconexão")
        return False

    def heartbeat(self) -> bool:
        now = time.time()
        interval = self._settings.system.heartbeat_interval_ms / 1000.0
        if now - self._last_heartbeat < interval:
            return True

        terminal = mt5.terminal_info()
        if terminal is None or not terminal.connected:
            self._log.warning("Heartbeat falhou - terminal desconectado")
            self._connected = False
            return False

        self._last_heartbeat = now
        return True

    def get_symbol_info(self) -> Optional[mt5.SymbolInfo]:
        symbol = self._settings.trading.symbol
        info = mt5.symbol_info(symbol)
        if info is None:
            self._log.error("Symbol info falhou para %s", symbol)
        return info

    def get_tick(self) -> Optional[mt5.Tick]:
        symbol = self._settings.trading.symbol
        tick = mt5.symbol_info_tick(symbol)
        return tick

    def get_account_info(self) -> Optional[mt5.AccountInfo]:
        info = mt5.account_info()
        if info is not None:
            self._account_info = info
            self._refresh_snapshot(info)
        return info

    def get_account_snapshot(self) -> Dict[str, float]:
        now = time.time()
        interval = self._settings.system.heartbeat_interval_ms / 1000.0
        if now - self._last_account_refresh >= interval or not self._account_snapshot:
            info = mt5.account_info()
            if info is not None:
                self._account_info = info
                self._refresh_snapshot(info)
            elif not self._account_snapshot:
                return {"balance": 0.0, "equity": 0.0, "margin_free": 0.0, "margin_used": 0.0, "floating_pnl": 0.0, "margin_level": 0.0}
        return self._account_snapshot

    def _refresh_snapshot(self, info: mt5.AccountInfo) -> None:
        margin = info.margin if info.margin > 0 else 0.0
        margin_level = (info.equity / info.margin * 100.0) if info.margin > 0 else 0.0
        self._account_snapshot = {
            "balance": info.balance,
            "equity": info.equity,
            "margin_free": info.margin_free,
            "margin_used": margin,
            "floating_pnl": getattr(info, "profit", 0.0) or 0.0,
            "margin_level": margin_level,
        }
        self._last_account_refresh = time.time()

    def is_market_open(self) -> bool:
        info = self.get_symbol_info()
        if info is None:
            return False
        return info.session_deals > 0 or info.spread > 0

    def is_session_allowed(self) -> tuple[bool, str]:
        if not self._settings.session.enabled:
            return True, "session_filter_disabled"

        now = datetime.now()
        current_time = now.hour * 60 + now.minute

        session = self._settings.session
        allowed_start = session.allowed_start_hour * 60 + session.allowed_start_minute
        allowed_end = session.allowed_end_hour * 60 + session.allowed_end_minute

        if current_time < allowed_start:
            return False, f"antes_abertura_{now.hour:02d}:{now.minute:02d}"
        if current_time >= allowed_end:
            return False, f"apos_fechamento_{now.hour:02d}:{now.minute:02d}"

        block_open_start = allowed_start
        block_open_end = allowed_start + session.block_open_minutes
        if block_open_start <= current_time < block_open_end:
            return False, f"bloqueado_abertura_{now.hour:02d}:{now.minute:02d}"

        block_close_start = allowed_end - session.block_close_minutes
        block_close_end = allowed_end
        if block_close_start <= current_time < block_close_end:
            return False, f"bloqueado_fechamento_{now.hour:02d}:{now.minute:02d}"

        rollover_start = session.block_rollover_start_hour * 60 + session.block_rollover_start_minute
        rollover_end = session.block_rollover_end_hour * 60 + session.block_rollover_end_minute
        if rollover_start <= current_time < rollover_end:
            return False, f"bloqueado_rollover_{now.hour:02d}:{now.minute:02d}"

        return True, "OK"

    def shutdown(self) -> None:
        self._log.info("Desligando MT5 Connector...")
        self._connected = False
        try:
            mt5.shutdown()
        except Exception:
            pass
        self._log.info("MT5 Connector desligado")

    def _validate_symbol(self) -> bool:
        symbol = self._settings.trading.symbol
        self._symbol_info = mt5.symbol_info(symbol)

        if self._symbol_info is None:
            self._log.error("Símbolo '%s' não encontrado", symbol)
            return False

        if not self._symbol_info.visible:
            self._log.info("Adicionando símbolo '%s' ao Market Watch...", symbol)
            if not mt5.symbol_select(symbol, True):
                self._log.error("Falha ao adicionar símbolo ao Market Watch")
                return False
            self._symbol_info = mt5.symbol_info(symbol)

        self._detect_filling_mode()

        self._log.info(
            "Símbolo validado: %s | Point: %.5f | Digits: %d | Trade mode: %d",
            symbol,
            self._symbol_info.point,
            self._symbol_info.digits,
            self._symbol_info.trade_mode,
        )
        return True

    def _handle_init_failure(self) -> bool:
        err = mt5.last_error()
        self._log.error("MT5 initialize falhou: código=%s, msg=%s", err[0], err[1])
        return False

    def _detect_filling_mode(self) -> None:
        if self._symbol_info is None:
            self._filling_mode = mt5.ORDER_FILLING_IOC
            self._log.info("Filling mode fallback: IOC (%d) — sem symbol_info", self._filling_mode)
            return

        raw_mode = getattr(self._symbol_info, "filling_mode", None)
        if raw_mode is not None and raw_mode > 0:
            resolved = self._resolve_filling_from_bitmask(raw_mode)
            self._filling_mode = resolved
            self._log.info(
                "Filling mode detectado: bitmask=%d → resolved=%s (%d)",
                raw_mode,
                self._filling_mode_name(resolved),
                resolved,
            )
            return

        self._filling_mode = mt5.ORDER_FILLING_IOC
        self._log.info("Filling mode fallback: IOC (%d) — broker não reportou filling_mode", self._filling_mode)

    def _resolve_filling_from_bitmask(self, bitmask: int) -> int:
        if bitmask & mt5.ORDER_FILLING_IOC:
            return mt5.ORDER_FILLING_IOC
        if bitmask & mt5.ORDER_FILLING_FOK:
            return mt5.ORDER_FILLING_FOK
        if bitmask & mt5.ORDER_FILLING_RETURN:
            return mt5.ORDER_FILLING_RETURN
        return mt5.ORDER_FILLING_IOC

    @staticmethod
    def _filling_mode_name(mode: int) -> str:
        names = {
            mt5.ORDER_FILLING_FOK: "FOK",
            mt5.ORDER_FILLING_IOC: "IOC",
            mt5.ORDER_FILLING_RETURN: "RETURN",
        }
        return names.get(mode, f"UNKNOWN({mode})")
