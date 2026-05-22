# HFT BOT ROADMAP

## V1 — COMPLETED

All core modules implemented, all M1-M8 bugs fixed, DEMO-ready:

* utils.py
* logger.py
* settings.py
* mt5_connector.py
* tick_engine.py
* signal_engine.py
* execution_engine.py
* risk_engine.py
* position_manager.py
* momentum_burst.py
* watchdog.py
* main.py (orchestrator)

### V1 Features Implemented

* Trailing stop (position_manager.check_trailing_stop)
* Daily reset with _daily_reset_pending flag (main.py)
* Status reporting periodico (_report_status) — inclui balance/equity/margin_free via account_snapshot
* User config loader (config/config_loader.py + user_config.json)
* Account snapshot (mt5_connector.get_account_snapshot — cached+interval, cold path)
* NETTING-only validation + reversal
* Session filter + forced close on block
* Watchdog (dead tick + freeze detection, threading.Event)
* 7 pre-trade risk checks + circuit breaker
* Requote retry (3x) + slippage tracking
* Close cooldown (2s, urgent bypass)
* Broker PnL recovery (_last_known_pnl)
* V2 sizing placeholders (RiskSettings.risk_per_trade_pct=0.0, sizing_mode=fixed)

---

## CURRENT STATUS

**V4 complete** — reversal filter adicionado (vel_fast ×1.5 + disp ≥8.0), post-close cooldown 2s para evitar whipsaw re-entry. Slippage -10 ticks confirmado como spread cost (cosmético). Awaiting DEMO validation com 50+ trades.

### V4 Changes (this session)

1. Reversal filter: |vel_fast| ≥ adaptive_threshold × 1.5 AND |net_displacement| ≥ 8.0
2. Post-close cooldown: 2s após qualquer close antes de nova entrada
3. Slippage analysis: -10 ticks consistente = spread cost (não bug)

### V3 Changes (previous session)

1. `_validate_stops()` auto-detecção broker stops_level + fallback 200pts
2. `main.py` init min_stop_distance do symbol_info
3. Settings: hft_tp=300, hft_sl=200, trailing=200 (broker compatible)
4. trend_bars filter corrigido < 2 → < 3 (3 locais)
5. Trailing stop cooldown 2s
6. Exit thresholds: direction_reversal |disp|≥5.0, displacement_flip ≥3.0

---

## V2 — POST-DEMO CANDIDATES

Priority order (validate with DEMO data first):

1. P1: _calc_velocity sem lista temporaria (tick_engine.py)
2. P2: CircularBuffer.__getitem__ direto (utils.py)
3. P3: numpy → manual math em arrays pequenos (tick_engine.py)
4. Trailing min_step adjustment (if spam observed in DEMO)
5. I2 fix: _modify_sl under ExecutionEngine._lock (only if multi-thread)
6. Rounding new_sl to _digits (only if multi-instrument)
7. TP modify em posicao existente
8. RiskSettings.risk_per_trade_pct implementation (% risk sizing)
9. RiskSettings.sizing_mode implementation (fixed / pct_risk / equity_pct)

---

## DO NOT IMPLEMENT

* AI / machine learning
* Dashboards / GUI / web API
* Multi-strategy framework
* Databases
* Optimization engine
* Pandas / TensorFlow / async / heavy libs
* Candle-based or indicator-heavy logic

---

## PRODUCTION GOAL

Focus:

* stable execution
* low latency
* operational safety

NOT:

* prediction complexity
