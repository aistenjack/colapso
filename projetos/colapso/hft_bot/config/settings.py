from dataclasses import dataclass, field


@dataclass
class MT5Settings:
    login: int = 0
    password: str = ""
    server: str = ""
    path: str = "F:\\mt5_b3-oseias\\terminal64.exe"
    terminal_path: str = "F:\\mt5_b3-oseias\\terminal64.exe"
    timeout: int = 10000


@dataclass
class TradingSettings:
    symbol: str = "WINM26"
    lot: float = 1.0
    take_profit_ticks: int = 1000
    stop_loss_ticks: int = 500
    magic_number: int = 123456
    deviation: int = 20
    filling_type: int = 1
    hft_take_profit_ticks: int = 0
    hft_stop_loss_ticks: int = 4000


@dataclass
class TickSettings:
    buffer_size: int = 200
    velocity_window_ms: int = 1000
    micro_range_window: int = 30
    min_ticks_for_signal: int = 20


@dataclass
class SignalSettings:
    min_velocity: float = 2.0
    min_acceleration: float = 0.5
    micro_breakout_factor: float = 0.3
    max_spread_ticks: int = 10
    momentum_reversal_factor: float = 0.7
    signal_cooldown_ms: int = 800
    min_strength: float = 0.3
    hft_min_velocity: float = 6.0
    hft_min_micro_range: float = 2.0
    hft_max_spread_ticks: int = 5
    hft_min_acceleration: float = -999.0
    hft_cooldown_ms: int = 200
    hft_reversal_factor: float = 0.5
    hft_min_displacement_pts: float = 4.0
    hft_acceleration_gate: bool = False


@dataclass
class RiskSettings:
    max_daily_loss: float = 500.0
    max_consecutive_losses: int = 8
    cooldown_after_loss_ms: int = 1500
    max_trades_per_minute: int = 30
    max_spread_ticks: int = 5
    max_latency_ms: float = 500.0
    auto_stop_trading: bool = True
    circuit_breaker_errors: int = 3
    circuit_breaker_cooldown_ms: int = 60000
    risk_per_trade_pct: float = 0.0
    sizing_mode: str = "fixed"


@dataclass
class PositionSettings:
    max_open_positions: int = 1
    trade_timeout_ms: int = 60000
    trailing_stop_enabled: bool = True
    trailing_activation_pts: float = 6.0
    trailing_offset_pts: float = 200.0
    trailing_virtual_enabled: bool = True
    trailing_virtual_offset_pts: float = 12.0
    trailing_attempt_cooldown_s: float = 0.3
    allow_reversal: bool = True
    min_hold_seconds: float = 5.0
    post_close_cooldown_s: float = 0.3
    loss_min_pts: float = 18.0
    loss_max_pts: float = 35.0
    reversal_min_disp: float = 9.0
    reversal_vel_mult: float = 1.2
    reentry_min_displacement_pts: float = 8.0


@dataclass
class SessionSettings:
    enabled: bool = True
    allowed_start_hour: int = 9
    allowed_start_minute: int = 5
    allowed_end_hour: int = 17
    allowed_end_minute: int = 50
    block_open_minutes: int = 5
    block_close_minutes: int = 5
    block_rollover_start_hour: int = 16
    block_rollover_start_minute: int = 55
    block_rollover_end_hour: int = 18
    block_rollover_end_minute: int = 5


@dataclass
class SystemSettings:
    tick_sleep_ms: int = 5
    reconnect_attempts: int = 10
    reconnect_delay_ms: int = 5000
    heartbeat_interval_ms: int = 30000
    watchdog_tick_timeout_ms: int = 10000
    status_report_interval_sec: int = 30


@dataclass
class SpeedFilterSettings:
    enabled: bool = True
    speed_period: int = 5  # legado (ticks); não usado no cálculo — ver speed_window_ms
    speed_window_ms: int = 500  # alinhado a TickEngine.velocity_fast (500ms)
    speed_threshold: float = 5.5
    strength_exhaustion: float = 0.30
    micro_range_window: int = 30
    ema_alpha: float = 0.4
    speed_clamp: float = 80.0
    chop_consistency_threshold: float = 0.45
    chop_speed_cap_factor: float = 0.8
    neutro_min_strength: float = 0.20


@dataclass
class HFTSettings:
    enabled: bool = True
    idle_timeout_ms: int = 3000
    fallback_min_velocity: float = 6.0
    metrics_log_interval_sec: int = 10
    adaptive_velocity_low: float = 4.0
    adaptive_velocity_mid: float = 12.0
    adaptive_threshold_low: float = 5.0
    adaptive_threshold_mid: float = 7.0
    adaptive_threshold_high: float = 10.0


@dataclass
class ReentrySettings:
    enabled: bool = True
    candle_ticks: int = 15
    retrace_weight: float = 0.30
    breakout_weight: float = 0.20
    structure_weight: float = 0.15
    consistency_weight: float = 0.15
    velocity_weight: float = 0.10
    chop_penalty_max: float = 0.10
    spread_penalty_max: float = 0.05
    threshold_base: float = 0.55
    echo_proximity_pts: float = 3.0
    freq_target: float = 3.0
    freq_window_s: float = 60.0


@dataclass
class Settings:
    mt5: MT5Settings = field(default_factory=MT5Settings)
    trading: TradingSettings = field(default_factory=TradingSettings)
    tick: TickSettings = field(default_factory=TickSettings)
    signal: SignalSettings = field(default_factory=SignalSettings)
    risk: RiskSettings = field(default_factory=RiskSettings)
    position: PositionSettings = field(default_factory=PositionSettings)
    session: SessionSettings = field(default_factory=SessionSettings)
    system: SystemSettings = field(default_factory=SystemSettings)
    hft: HFTSettings = field(default_factory=HFTSettings)
    speed_filter: SpeedFilterSettings = field(default_factory=SpeedFilterSettings)
    reentry: ReentrySettings = field(default_factory=ReentrySettings)
