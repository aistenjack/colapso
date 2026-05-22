import time
import statistics
from typing import Optional
from collections import deque

from core.logger import Log
from core.utils import TickData, Signal, SignalType, OrderSide
from config.settings import Settings, RiskSettings

RISK_BLOCK_COOLDOWN_MS = 500.0


class RiskEngine:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._risk_cfg: RiskSettings = settings.risk
        self._log = Log.get("risk")

        self._daily_pnl: float = 0.0
        self._consecutive_losses: int = 0
        self._last_loss_time: float = 0.0
        self._trade_timestamps: deque = deque(maxlen=200)
        self._trading_enabled: bool = True
        self._stop_reason: str = ""
        self._session_start: float = time.time()
        self._consecutive_errors: int = 0
        self._circuit_breaker_time: float = 0.0
        self._latency_samples: deque = deque(maxlen=50)
        self._last_risk_block_time: float = 0.0
        self._rate_limit_log_time: float = 0.0
        self._loss_cooldown_log_time: float = 0.0

    def check_pre_trade(self, tick: TickData, point: float = 1.0, latency_ms: float = 0.0) -> tuple[bool, str]:
        if not self._trading_enabled:
            return False, f"Trading desabilitado: {self._stop_reason}"

        if not self._check_circuit_breaker():
            return False, f"Circuit breaker ativo: {self._stop_reason}"

        if not self._check_daily_loss():
            return False, "Daily loss máximo atingido"

        if not self._check_consecutive_losses():
            return False, f"Consecutive losses: {self._consecutive_losses}"

        if not self._check_trade_rate():
            return False, "Rate limit atingido"

        if not self._check_spread(tick, point):
            return False, f"Spread muito alto: {tick.spread / point:.1f} ticks"

        if not self._check_latency(latency_ms):
            return False, f"Latência alta: {latency_ms:.1f}ms"

        return True, "OK"

    def is_in_risk_cooldown(self) -> bool:
        if self._last_risk_block_time <= 0:
            return False
        remaining_ms = RISK_BLOCK_COOLDOWN_MS - (time.time() - self._last_risk_block_time) * 1000.0
        if remaining_ms > 0:
            return True
        return False

    def mark_risk_blocked(self) -> None:
        self._last_risk_block_time = time.time()

    def check_post_trade(self, pnl: float) -> None:
        self._daily_pnl += pnl

        if pnl < 0:
            self._consecutive_losses += 1
            self._last_loss_time = time.time()
            self._log.warning(
                "Loss registrado | PnL: %.2f | Consecutivos: %d | Daily: %.2f",
                pnl,
                self._consecutive_losses,
                self._daily_pnl,
            )
        elif pnl > 0:
            self._consecutive_losses = 0
            self._log.info(
                "Win registrado | PnL: %.2f | Daily: %.2f", pnl, self._daily_pnl
            )

        self._auto_stop_check()

    def register_execution_error(self) -> None:
        self._consecutive_errors += 1
        self._log.warning("Erro de execução registrado | Consecutivos: %d", self._consecutive_errors)

        if self._consecutive_errors >= self._risk_cfg.circuit_breaker_errors:
            self._activate_circuit_breaker("execution_errors")

    def register_execution_success(self) -> None:
        self._consecutive_errors = 0

    def record_latency(self, latency_ms: float) -> None:
        if latency_ms > 0:
            if latency_ms > 5000.0:
                self._log.warning(
                    "Latência extrema ignorada (outlier): %.1fms", latency_ms
                )
                return
            self._latency_samples.append(latency_ms)

    def check_close_signal(self, position_pnl: float) -> Optional[Signal]:
        if self._risk_cfg.max_daily_loss <= 0:
            return None

        projected = self._daily_pnl + position_pnl
        if projected <= -self._risk_cfg.max_daily_loss:
            self._log.critical(
                "DAILY LOSS CRÍTICO | Daily: %.2f + Posição: %.2f = %.2f | Max: -%.2f",
                self._daily_pnl,
                position_pnl,
                projected,
                self._risk_cfg.max_daily_loss,
            )
            return Signal(
                signal_type=SignalType.CLOSE,
                reason="daily_loss_limit",
                strength=1.0,
            )

        return None

    def _check_daily_loss(self) -> bool:
        if self._daily_pnl <= -self._risk_cfg.max_daily_loss:
            self._log.critical("Daily loss máximo atingido: %.2f", self._daily_pnl)
            if self._risk_cfg.auto_stop_trading:
                self._stop_trading("daily_loss")
            return False
        return True

    def _check_consecutive_losses(self) -> bool:
        if self._consecutive_losses >= self._risk_cfg.max_consecutive_losses:
            cooldown_s = self._risk_cfg.cooldown_after_loss_ms / 1000.0
            remaining = cooldown_s - (time.time() - self._last_loss_time)
            if remaining > 0:
                now = time.time()
                if now - self._loss_cooldown_log_time >= 5.0:
                    self._log.warning(
                        "[RISK COOLDOWN] Consec losses: %d | remaining=%.1fs",
                        self._consecutive_losses, remaining,
                    )
                    self._loss_cooldown_log_time = now
                return False
        return True

    def _check_cooldown(self) -> bool:
        if self._last_loss_time <= 0:
            return True
        cooldown_s = self._risk_cfg.cooldown_after_loss_ms / 1000.0
        if time.time() - self._last_loss_time < cooldown_s:
            return False
        return True

    def _check_trade_rate(self) -> bool:
        now = time.time()
        while self._trade_timestamps and now - self._trade_timestamps[0] > 60.0:
            self._trade_timestamps.popleft()

        count = len(self._trade_timestamps)
        if count >= self._risk_cfg.max_trades_per_minute:
            if now - self._rate_limit_log_time >= 5.0:
                oldest_age = now - self._trade_timestamps[0] if self._trade_timestamps else 0.0
                self._log.info(
                    "[RISK RATE LIMIT] count=%d limit=%d oldest_trade_age=%.1fs",
                    count, self._risk_cfg.max_trades_per_minute, oldest_age,
                )
                self._rate_limit_log_time = now
            return False
        return True

    def _check_spread(self, tick: TickData, point: float = 1.0) -> bool:
        if point <= 0:
            return True
        spread_ticks = tick.spread / point
        if spread_ticks > self._risk_cfg.max_spread_ticks:
            self._log.debug(
                "Spread bloqueado: %.1f ticks (max: %d)", spread_ticks, self._risk_cfg.max_spread_ticks
            )
            return False
        return True

    def _check_latency(self, latency_ms: float) -> bool:
        if latency_ms <= 0:
            return True
        if latency_ms > self._risk_cfg.max_latency_ms:
            self._log.warning(
                "Latência bloqueada: %.1fms (max: %.1fms)", latency_ms, self._risk_cfg.max_latency_ms
            )
            return False
        return True

    def _check_circuit_breaker(self) -> bool:
        if self._circuit_breaker_time <= 0:
            return True
        cooldown_s = self._risk_cfg.circuit_breaker_cooldown_ms / 1000.0
        remaining = cooldown_s - (time.time() - self._circuit_breaker_time)
        if remaining > 0:
            now = time.time()
            if now - self._loss_cooldown_log_time >= 5.0:
                self._log.warning(
                    "Circuit breaker ativo | Restam: %.1fs | Motivo: %s",
                    remaining, self._stop_reason,
                )
                self._loss_cooldown_log_time = now
            return False
        self._log.info("Circuit breaker expirado - retomando trading")
        self._trading_enabled = True
        self._stop_reason = ""
        self._circuit_breaker_time = 0.0
        self._consecutive_errors = 0
        return True

    def _activate_circuit_breaker(self, reason: str) -> None:
        self._circuit_breaker_time = time.time()
        self._trading_enabled = False
        self._stop_reason = f"circuit_breaker_{reason}"
        self._log.critical(
            "CIRCUIT BREAKER ATIVADO | Motivo: %s | Erros consecutivos: %d | Cooldown: %dms",
            reason, self._consecutive_errors, self._risk_cfg.circuit_breaker_cooldown_ms,
        )

    def _auto_stop_check(self) -> None:
        if not self._risk_cfg.auto_stop_trading:
            return

        if self._daily_pnl <= -self._risk_cfg.max_daily_loss:
            self._stop_trading("daily_loss_exceeded")

    def _stop_trading(self, reason: str) -> None:
        if not self._trading_enabled:
            return
        self._trading_enabled = False
        self._stop_reason = reason
        self._log.critical("TRADING PARADO AUTOMATICAMENTE | Motivo: %s", reason)

    def register_trade_attempt(self) -> None:
        self._trade_timestamps.append(time.time())

    def reset_daily(self) -> None:
        self._log.info(
            "Risk engine daily reset | DailyPnL: %.2f → 0 | ConsecLosses: %d → 0 | TradingEnabled: %s → True",
            self._daily_pnl, self._consecutive_losses, self._trading_enabled,
        )
        self._daily_pnl = 0.0
        self._consecutive_losses = 0
        self._last_loss_time = 0.0
        self._trading_enabled = True
        self._stop_reason = ""
        self._session_start = time.time()
        self._consecutive_errors = 0
        self._circuit_breaker_time = 0.0
        self._trade_timestamps.clear()
        self._latency_samples.clear()
        self._last_risk_block_time = 0.0

    @property
    def last_risk_block_time(self) -> float:
        return self._last_risk_block_time

    @property
    def is_trading_enabled(self) -> bool:
        return self._trading_enabled

    @property
    def daily_pnl(self) -> float:
        return self._daily_pnl

    @property
    def consecutive_losses(self) -> int:
        return self._consecutive_losses

    @property
    def consecutive_errors(self) -> int:
        return self._consecutive_errors

    def get_status(self) -> dict:
        return {
            "trading_enabled": self._trading_enabled,
            "stop_reason": self._stop_reason,
            "daily_pnl": self._daily_pnl,
            "consecutive_losses": self._consecutive_losses,
            "consecutive_errors": self._consecutive_errors,
            "circuit_breaker_active": self._circuit_breaker_time > 0,
            "trades_last_minute": len(self._trade_timestamps),
            "avg_latency_ms": self._avg_latency(),
        }

    def _avg_latency(self) -> float:
        if not self._latency_samples:
            return 0.0
        samples = sorted(self._latency_samples)
        n = len(samples)
        if n < 5:
            return statistics.median(samples)
        trim = max(1, n // 10)
        trimmed = samples[trim:n - trim]
        if not trimmed:
            return statistics.median(samples)
        return sum(trimmed) / len(trimmed)
