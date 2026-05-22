from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional
import time


class SignalType(Enum):
    BUY = auto()
    SELL = auto()
    CLOSE = auto()
    NONE = auto()


class OrderSide(Enum):
    BUY = auto()
    SELL = auto()


class TradeStatus(Enum):
    SUCCESS = auto()
    REJECTED = auto()
    FAILED = auto()
    TIMEOUT = auto()


@dataclass(slots=True)
class TickData:
    bid: float = 0.0
    ask: float = 0.0
    last: float = 0.0
    volume: int = 0
    time_ms: int = 0
    spread: float = 0.0
    mid: float = 0.0
    delta: float = 0.0
    timestamp: float = field(default_factory=time.time)

    @property
    def is_valid(self) -> bool:
        return self.bid > 0.0 and self.ask > 0.0 and self.ask >= self.bid


@dataclass(slots=True)
class Signal:
    signal_type: SignalType = SignalType.NONE
    strength: float = 0.0
    reason: str = ""
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass(slots=True)
class TradeResult:
    status: TradeStatus = TradeStatus.FAILED
    ticket: int = 0
    price: float = 0.0
    volume: float = 0.0
    side: Optional[OrderSide] = None
    slippage: float = 0.0
    latency_ms: float = 0.0
    message: str = ""


@dataclass(slots=True)
class TickMetrics:
    velocity: float = 0.0
    velocity_fast: float = 0.0
    velocity_very_fast: float = 0.0
    acceleration: float = 0.0
    delta: float = 0.0
    micro_range: float = 0.0
    spread: float = 0.0
    tick_count: int = 0
    avg_velocity: float = 0.0
    trend_bars: int = 0
    net_displacement: float = 0.0
    is_valid: bool = False


class CircularBuffer:
    __slots__ = ("_buffer", "_head", "_count", "_capacity")

    def __init__(self, capacity: int) -> None:
        self._capacity = capacity
        self._buffer: list[Optional[float]] = [None] * capacity
        self._head: int = 0
        self._count: int = 0

    def push(self, value: float) -> None:
        self._buffer[self._head] = value
        self._head = (self._head + 1) % self._capacity
        if self._count < self._capacity:
            self._count += 1

    @property
    def is_full(self) -> bool:
        return self._count == self._capacity

    @property
    def size(self) -> int:
        return self._count

    def to_array(self) -> list[float]:
        if self._count == 0:
            return []
        if self._count < self._capacity:
            return [v for v in self._buffer[: self._count] if v is not None]
        result: list[float] = []
        for i in range(self._capacity):
            idx = (self._head + i) % self._capacity
            val = self._buffer[idx]
            if val is not None:
                result.append(val)
        return result

    def last(self) -> Optional[float]:
        if self._count == 0:
            return None
        idx = (self._head - 1) % self._capacity
        return self._buffer[idx]

    def clear(self) -> None:
        self._head = 0
        self._count = 0


def now_ms() -> int:
    return int(time.time() * 1000)


def elapsed_ms(start: float) -> float:
    return (time.time() - start) * 1000.0
