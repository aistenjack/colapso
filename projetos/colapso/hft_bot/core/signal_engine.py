import time
from abc import ABC, abstractmethod
from typing import Optional

from core.logger import Log
from core.utils import TickData, TickMetrics, Signal, SignalType
from config.settings import Settings, SignalSettings, HFTSettings


class StrategyBase(ABC):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._signal_cfg: SignalSettings = settings.signal
        self._hft_cfg: HFTSettings = settings.hft
        self._log = Log.get("signal")
        self._last_signal_time: float = 0.0
        self._point: float = 1.0
        self._digits: int = 0

    def set_instrument_info(self, point: float, digits: int) -> None:
        self._point = point
        self._digits = digits

    @abstractmethod
    def evaluate(self, tick: TickData, metrics: TickMetrics) -> Signal:
        ...

    def _create_signal(
        self,
        signal_type: SignalType,
        tick: TickData,
        strength: float,
        reason: str,
    ) -> Signal:
        tp_ticks = self._settings.trading.take_profit_ticks
        sl_ticks = self._settings.trading.stop_loss_ticks

        if signal_type == SignalType.BUY:
            entry = tick.ask
            sl = entry - sl_ticks * self._point
            tp = entry + tp_ticks * self._point
        elif signal_type == SignalType.SELL:
            entry = tick.bid
            sl = entry + sl_ticks * self._point
            tp = entry - tp_ticks * self._point
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

    def _check_cooldown(self) -> bool:
        if self._hft_cfg.enabled:
            cooldown_ms = self._signal_cfg.hft_cooldown_ms
        else:
            cooldown_ms = self._signal_cfg.signal_cooldown_ms
        cooldown_s = cooldown_ms / 1000.0
        if time.time() - self._last_signal_time < cooldown_s:
            return False
        return True

    def _mark_signal_time(self) -> None:
        self._last_signal_time = time.time()


class SignalEngine:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._log = Log.get("signal")
        self._strategy: Optional[StrategyBase] = None

    def set_strategy(self, strategy: StrategyBase) -> None:
        self._strategy = strategy
        self._log.info("Estratégia configurada: %s", strategy.__class__.__name__)

    def evaluate(self, tick: TickData, metrics: TickMetrics) -> Signal:
        if self._strategy is None:
            return Signal(signal_type=SignalType.NONE)
        if not metrics.is_valid:
            return Signal(signal_type=SignalType.NONE)
        return self._strategy.evaluate(tick, metrics)

    @property
    def strategy_name(self) -> str:
        if self._strategy is None:
            return "Nenhuma"
        return self._strategy.__class__.__name__
