# TEST MATRIX — HFT Micro-Scalper

## Template

| ID | Component | Scenario | Input | Expected | Version Added |
|----|-----------|----------|-------|----------|---------------|
| T01 | ... | ... | ... | ... | ... |

---

## Test Suites

### Suite 1: SpeedFilter (`tests/test_speed_filter.py`) — 49 tests

| ID | Component | Scenario | Input | Expected | Version |
|----|-----------|----------|-------|----------|---------|
| T01 | SpeedFilter | Slow market (1pt/200ms) | 295 ticks, speed<2.75 | 0% allowed, 100% LENTO | V12.10 |
| T02 | SpeedFilter | Normal market (3pt/100ms) | 295 ticks, speed 3-7 | 100% allowed, FORTE+ACELERANDO | V12.10 |
| T03 | SpeedFilter | Active market (5pt/50ms) | 295 ticks, speed 5-10 | 100% allowed, FORTE+ACELERANDO | V12.10 |
| T04 | SpeedFilter | Chop market (±5pt/100ms) | 295 ticks, zigzag | ~50% blocked, mixed states | V12.10 |
| T05 | SpeedFilter | Burst market (8-22pt/30ms) | 295 ticks, spike | 100% allowed, ACELERANDO+FORTE | V12.10 |
| T06 | SpeedFilter | EMA speed smoothing | alpha=0.4, clamp=80 | Smoothed speed ≤ raw, clamped | V12.10 |
| T07 | SpeedFilter | Composite strength | range 40% + consist 35% + accel 25% | Strength 0-1.5 | V12.10 |
| T08 | SpeedFilter | LENTO gate | speed < threshold×0.5 | BLOCKED | V12.10 |
| T09 | SpeedFilter | NEUTRO gate | speed ≥ 0.5×thresh, strength≥0.20, accel>0, consist≥0.45 | ALLOWED | V12.10 |
| T10 | SpeedFilter | ACELERANDO gate | speed ≥ 0.65×thresh, consist>0.55 | ALLOWED | V12.10 |
| T11 | SpeedFilter | FORTE gate | speed ≥ thresh, strength>0.45, consist>0.50, accel>0 | ALLOWED | V12.10 |
| T12 | SpeedFilter | EXAUSTAO gate | speed > 1.3×thresh, strength<0.30 | BLOCKED | V12.10 |
| T13 | SpeedFilter | Chop sub-check | consist<0.45 AND speed<0.8×thresh | LENTO (BLOCKED) | V12.10 |
| T14 | SpeedFilter | Adaptive threshold | spread_mult × range_mult × vel_mult | 70/30 EMA smoothing | V12.10 |
| T15 | SpeedFilter | Stats tracking | total_evals, blocked, allowed | Correct counts | V12.10 |
| T16-T49 | SpeedFilter | Boundary/edge/combined | Various | Various | V12.10 |

### Suite 2: Reentry Gate (`tests/test_reentry_gate.py`) — 8 tests

| ID | Component | Scenario | Input | Expected | Version |
|----|-----------|----------|-------|----------|---------|
| T50 | MomentumBurst | Same-side BUY after loss, low disp | close BUY at -10, disp=5, reentry_min=8 | NONE (blocked) | V12.13 |
| T51 | MomentumBurst | Same-side BUY after loss, high disp | close BUY at -10, disp=10, reentry_min=8 | BUY (allowed) | V12.13 |
| T52 | MomentumBurst | Same-side after WIN, low disp | close BUY at +5, disp=5, reentry_min=8 | BUY (no gate after win) | V12.13 |
| T53 | MomentumBurst | Flip after loss, low disp | close BUY at -10, SELL signal disp=-5 | SELL (no gate for flip) | V12.13 |
| T54 | MomentumBurst | Gate disabled (threshold=0) | reentry_min=0, close at -10, disp=5 | BUY (gate off) | V12.13 |
| T55 | MomentumBurst | Same-side SELL after loss, low disp | close SELL at -10, disp=-5, reentry_min=8 | NONE (blocked) | V12.13 |
| T56 | MomentumBurst | Same-side SELL after loss, high disp | close SELL at -10, disp=-10, reentry_min=8 | SELL (allowed) | V12.13 |
| T57 | MomentumBurst | First trade (no close history) | No previous close, disp=5 | BUY (no gate) | V12.13 |

### Suite 3: Micro Structure Reentry (`tests/test_micro_structure_reentry.py`) — 17 tests

| ID | Component | Scenario | Input | Expected | Version |
|----|-----------|----------|-------|----------|---------|
| T58 | MicroStructureEngine | Pullback allow (retrace candle) | Close at 100, retrace to 97, BUY signal at 99 | ALLOW (retrace_score >0) | V12.14 |
| T59 | MicroStructureEngine | Breakout allow (breaking candle) | Close at 100, breakout candle high=103, BUY at 102 | ALLOW (breakout_score >0) | V12.14 |
| T60 | MicroStructureEngine | Echo trade block | Price ≈ last close, no retrace/breakout/consistency | BLOCK (echo ×0.1) | V12.14 |
| T61 | MicroStructureEngine | Chop market block | LENTO speed filter, low consistency | BLOCK (chop_penalty + low scores) | V12.14 |
| T62 | MicroStructureEngine | Fake breakout block | Breakout + immediate reversal candle | BLOCK (structure contradicts) | V12.14 |
| T63 | MicroStructureEngine | Retrace + reaccelerate allow | Retrace candle followed by strong resumption | ALLOW (retrace + structure + velocity) | V12.14 |
| T64 | MicroStructureEngine | Structural reversal block | 3 candles against signal direction | BLOCK (structure_score=0) | V12.14 |
| T65 | MicroStructureEngine | Flip entry no gate | Opposite side after close | NO GATE (flip bypasses) | V12.14 |
| T66 | MicroStructureEngine | First trade no gate | No _last_close_price | NO GATE | V12.14 |
| T67 | MicroStructureEngine | Sell-side pullback allow | Close SELL, retrace up, SELL signal | ALLOW (retrace works SELL) | V12.14 |
| T68 | MicroStructureEngine | Adaptive threshold relaxes | freq < target×0.5 | threshold < threshold_base | V12.14 |
| T69 | MicroStructureEngine | Candle finalization | 15 ticks fed | direction, body_ratio, wicks correct | V12.14 |
| T70 | MicroStructureEngine | Deep retrace penalty | retrace >0.8 | score ×0.5 penalty | V12.14 |
| T71 | MicroStructureEngine | No retrace + no breakout block | Both scores =0 | BLOCK (raw score too low) | V12.14 |
| T72 | MicroStructureEngine | Spread penalty | High spread > max | score reduced | V12.14 |
| T73 | MicroStructureEngine | Retrace priority > breakout | Compare weights | retrace_weight(0.30) > breakout_weight(0.20) | V12.14 |
| T74 | MicroStructureEngine | Performance benchmark | 1000 evaluations | <1ms/eval (~400-800µs) | V12.14 |

---

## Version History — Live Metrics

| Version | Date | Duration | Trades | WR | PnL (pts) | Avg Win | Avg Loss | R:R | Trades/min | sf_reject | Key Changes |
|---------|------|----------|--------|-----|-----------|---------|----------|-----|------------|-----------|-------------|
| V12.7 | 18/05 | 15:00-15:59 (~60min) | 155 | 72.9% | +35 | +3.35 | -9.05 | 0.37 | 2.63 | 97% | Baseline (pre-V12.8 settings) |
| V12.8 | 18/05 | 16:00-16:55 (~55min) | 177 | 62.7% | -193 | +4.23 | -10.87 | 0.39 | 3.22 | — | — |
| V12.10 | 19/05 | 09:10-09:25 (~15min) | 210 | 68.6% | -27 | +4.08 | -10.41 | 0.39 | ~14 | 91% | SpeedFilter rewrite, threshold=5.5 |
| V12.11 | 19/05 | 10:00-10:44 (~44min) | 201 | 61.7% | +99 | +4.94 | -8.03 | 0.62 | 4.57 | 91.5% | loss_min=18, trailing_act=6, offset=8, reversal_disp=9 |
| V12.12 | 19/05 | 11:16-11:30 (~14min) | 109 | 60.6% | -12 | +4.50 | -8.35 | 0.54 | 6.99 | 88-90% | Latency trimmed mean, loss_exit urgent |
| V12.13 | — | — | — | — | — | — | — | — | — | — | Reentry displacement gate, set_position_side bug fix |
| V12.14 | — | — | — | — | — | — | — | — | — | — | MicroStructureEngine: 7-score probabilistic reentry, anti-echo, adaptive threshold |

---

## Regression Checklist (pre-deploy)

| # | Check | Command | Status |
|---|-------|---------|--------|
| 1 | SpeedFilter tests (49/49) | `python tests/test_speed_filter.py` | ☐ |
| 2 | Reentry gate tests (8/8) | `python tests/test_reentry_gate.py` | ☐ |
| 3 | Micro structure tests (17/17) | `python tests/test_micro_structure_reentry.py` | ☐ |
| 4 | Settings compile | `python -c "from config.settings import Settings; s=Settings(); print(s.reentry)"` | ☐ |
| 5 | MomentumBurst import + engine | `python -c "from strategies.momentum_burst import MomentumBurst"` | ☐ |
| 6 | MicroStructureEngine import | `python -c "from core.micro_structure import MicroStructureEngine"` | ☐ |
| 7 | Risk engine import + trimmed mean | `python -c "from core.risk_engine import RiskEngine"` | ☐ |
| 8 | Main loop import | `python -c "from main import HFTBot"` | ☐ |
| 9 | No stale _position_side bug | Verify set_position_side(BUY) sets _position_side | ☐ |
| 10 | notify_close_pnl wired | Verify main.py calls strategy.notify_close_pnl on both close paths | ☐ |
| 11 | on_tick wired in main loop | Verify main.py calls strategy.on_tick(tick) | ☐ |
| 12 | set_point wired in main init | Verify main.py calls strategy.set_point(self._point) | ☐ |
| 13 | set_position_side passes close_price | Verify main.py passes close_price in close paths | ☐ |
| 14 | Reentry diagnostics in HFT metrics | Verify _report_hft_metrics includes reentry_thresh, reentry_tpm | ☐ |
| 15 | [REENTRY SCORE] log output | Appears when reentry engine evaluates | ☐ |

---

## Key Parameters Per Version

| Parameter | V12.7 | V12.10 | V12.11 | V12.12 | V12.13 | V12.14 |
|-----------|-------|--------|--------|--------|--------|--------|
| loss_min_pts | 25 | 25 | **18** | 18 | 18 | 18 |
| loss_max_pts | 40 | 40 | **35** | 35 | 35 | 35 |
| trailing_activation_pts | 10 | 10 | **6** | 6 | 6 | 6 |
| trailing_virtual_offset_pts | 5 | 5 | **8** | 8 | 8 | 8 |
| speed_threshold | 8.0 | **5.5** | 5.5 | 5.5 | 5.5 | 5.5 |
| reversal_min_disp | 5 | 5 | **9** | 9 | 9 | 9 |
| loss_exit urgent | No | No | No | **Yes** | Yes | Yes |
| avg_latency method | simple | simple | simple | **trimmed** | trimmed | trimmed |
| reentry_min_displacement_pts | — | — | — | — | **8.0** | **obsoleto** |
| set_position_side bug | Present | Present | Present | Present | **Fixed** | Fixed |
| reentry engine | — | — | — | — | disp gate | **MicroStructure (7-score)** |
| reentry threshold_base | — | — | — | — | 8.0 (disp) | **0.55 (score)** |
| reentry echo_proximity_pts | — | — | — | — | — | **3.0** |
| reentry candle_ticks | — | — | — | — | — | **15** |
| reentry freq_target | — | — | — | — | — | **3.0** |
