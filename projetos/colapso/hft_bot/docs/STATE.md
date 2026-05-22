# CURRENT PROJECT STATE

## V12.14 STATUS: HFT MICRO-SCALPER — MICRO STRUCTURE REENTRY ENGINE — VALIDADO ✅

Bot operacional em Clear DEMO (WINM26, NETTING). V12.13 validou reentry displacement gate + bug fix. **V12.14**: **MicroStructureEngine** substitui displacement gate simples por scoring probabilístico com 7 componentes. Echo trades (re-entry mesmo preço sem contexto) bloqueados por anti-echo hard gate. Adaptive threshold relaxa/aperta baseado em frequência vs target. 74/74 tests pass (49 SpeedFilter + 8 reentry gate + 17 micro structure).

### MicroStructureEngine — `core/micro_structure.py` (552 lines)

- **MicroCandle**: tick-based (15 ticks/candle, ~150-300ms WINM26), ring buffer 3 candles, finalize() com direction/body_ratio/wick_ratios/strength
- **ReentryResult**: 7 sub-scores + final_score + echo_blocked + threshold + mode
- **evaluate_reentry()**: scoring completo com echo detection + adaptive threshold
- **Score model**: `raw = retrace×0.30 + breakout×0.20 + structure×0.15 + consistency×0.15 + velocity×0.10 - chop_pen - spread_pen`; echo → ×0.1; weak pullback/breakout → ×0.3
- **Anti-echo hard gate**: preço <3pts do último close + sem retrace (>0.3) + sem breakout (>0.5) + sem consistência (>0.4) → BLOCK
- **Adaptive threshold**: freq < 1.5/min → threshold -0.15 (min 0.30); freq > 7.5/min → threshold +0.15 (max 0.80)
- **Retracement prioritário** (weight=0.30 vs breakout=0.20)
- **`get_diagnostics()`**: threshold, trades_per_min, candle states

### ReentrySettings — `config/settings.py` (14 params)

`enabled=True, candle_ticks=15, retrace_weight=0.30, breakout_weight=0.20, structure_weight=0.15, consistency_weight=0.15, velocity_weight=0.10, chop_penalty_max=0.10, spread_penalty_max=0.05, threshold_base=0.55, echo_proximity_pts=3.0, freq_target=3.0, freq_window_s=60.0`

### Integration changes

- `momentum_burst.py`: `on_tick()` delega ao engine; `set_position_side(side, close_price)` rastreia `_last_close_price`; `set_point()` passa ao engine; reentry gate em 3 pontos (_check_hft_entry, idle_fallback BUY, idle_fallback SELL); `notify_trade_time()` → `engine.notify_trade()`
- `main.py`: `strategy.on_tick(tick)` no loop; `set_position_side(None, close_price=last_tick.mid)` em close paths; reentry stats em HFT metrics report; `strategy.set_point(self._point)` init
- **`reentry_min_displacement_pts` obsoleto** — substituído por scoring

### Test results

| Suite | Pass | Total |
|-------|------|-------|
| SpeedFilter | 49 | 49 |
| Reentry Gate | 8 | 8 |
| Micro Structure | 17 | 17 |
| **Total** | **74** | **74** |

### Key observable metrics (deploy)

- `[REENTRY SCORE]` logs: retrace, breakout, structure, consistency, velocity, chop_pen, spread_pen, final, threshold, echo, mode, decision
- `[HFT METRICS]` includes: reentry_thresh, reentry_tpm
- Benchmark: ~400-1100µs/eval, <2µs/tick (target: <2ms/eval, <100µs/tick)

---

## MÓDULOS — STATUS INDIVIDUAL

| Módulo | Arquivo | Status | Notas |
|--------|---------|--------|-------|
| DTOs/Enums/Buffer | `core/utils.py` | DONE | TickMetrics inclui `velocity_very_fast`, `trend_bars` |
| Logger | `core/logger.py` | DONE | 8 named loggers, console=INFO, file=DEBUG, tick=file-only |
| Settings | `config/settings.py` | DONE | **V12.9**: hft_min_velocity=6.0, hft_min_displacement_pts=4.0, hft_min_micro_range=2.0, hft_max_spread_ticks=5, **hft_acceleration_gate=False**, cooldown_after_loss_ms=1500, adaptive_threshold_low=5.0/mid=7.0/high=10.0, adaptive_velocity_low=4.0/mid=12.0, fallback_min_velocity=6.0, **trailing_activation_pts=6.0**, trailing_offset_pts=200.0, **trailing_virtual_enabled=True**, **trailing_virtual_offset_pts=8.0**, **loss_min_pts=18.0**, loss_max_pts=35.0, reversal_min_disp=9.0, reversal_vel_mult=1.2, min_hold_seconds=5.0, post_close_cooldown_s=0.3, hft_stop_loss_ticks=4000; **V12.10: SpeedFilterSettings** (speed_period=5, **speed_threshold=5.5**, **strength_exhaustion=0.30**, micro_range_window=30, **chop_consistency_threshold=0.45**, **chop_speed_cap_factor=0.8**, **neutro_min_strength=0.20**); **V12.14: ReentrySettings** (14 params — enabled=True, candle_ticks=15, weights: retrace=0.30/breakout=0.20/structure=0.15/consistency=0.15/velocity=0.10, chop_penalty_max=0.10, spread_penalty_max=0.05, threshold_base=0.55, echo_proximity_pts=3.0, freq_target=3.0, freq_window_s=60.0); **V12.13: reentry_min_displacement_pts=8.0 (obsoleto em V12.14)** |
| Config Loader | `config/config_loader.py` | DONE | JSON → dataclass merge, fallback automático, BOM-safe, type coercion, secret masking |
| MT5 Connector | `core/mt5_connector.py` | DONE | NETTING validation, reconnect, heartbeat, session filter, account_snapshot (cached+interval), terminal_path, filling_mode autodetect |
| Tick Engine | `core/tick_engine.py` | DONE | velocity SIGNED, velocity_very_fast(200ms), acc=vel_very_fast-vel_fast, trend_bars com zero tolerance, displacement em pontos (total/point), **V12.10: `get_recent_ticks(count)` public method** |
| Signal Engine | `core/signal_engine.py` | DONE | StrategyBase ABC + dispatcher |
| Execution Engine | `core/execution_engine.py` | DONE | async ThreadPoolExecutor(1), stops validation com auto-detecção broker stops_level + fallback 200pts, filling fallback IOC→FOK→RETURN, **_validate_stops pula TP quando tp=0** |
| Position Manager | `core/position_manager.py` | DONE | **V12.6**: `self._point` sem `100 *`; **deactivation gate** BUY/SELL; **`self._min_stop_distance`** field + `set_min_stop_distance()`; **min_dist validation** em check_trailing_stop; **V12.9: `check_virtual_trailing()`** — SL rastreado internamente (sem broker modify), close via market order quando bid/ask cruza virtual SL; offset=5pts (vs 200pts broker); deactivation gate; log a cada 5 moves; **`_virtual_trailing_sl`**, **`_virtual_trailing_activated`**, **`_virtual_trailing_move_count`** fields |
| Risk Engine | `core/risk_engine.py` | DONE | rate limit=30/min, risk_block_cooldown=500ms, spread_max=5, cooldown_after_loss=1500ms, NO permanent stop for excessive_losses, **V12.12: trimmed mean avg_latency (drop 10% outliers), reject samples >5000ms** |
| Watchdog | `core/watchdog.py` | DONE | daemon thread, dead tick (20s grace quando execution_busy), freeze detection, threading.Event |
| MomentumBurst | `strategies/momentum_burst.py` | DONE | **V12.14: MicroStructureEngine integration** — `on_tick()` delega ao engine; `set_position_side(side, close_price)` rastreia `_last_close_price`; `set_point()` passa ao engine; `notify_trade_time()` → `engine.notify_trade()`; `evaluate_reentry()` em 3 pontos (_check_hft_entry, idle_fallback BUY, idle_fallback SELL); **V12.13: bug fix set_position_side(BUY) agora seta _position_side**; notify_close_pnl(pnl) recebe PnL; **trend_bars=booster**, acc=booster, **_check_exit só com loss_exit** (gain_exit removido), **reversal gate usa loss_min_pts (20pts) + vel×1.2**, min_hold=5s, post-close=0.3s, dedup=100ms |
| Main Loop | `main.py` | DONE | async execution com callback queue, close_cooldown=500ms, drain_async_results(), min_stop_distance init do broker, **L111 chama `position_manager.set_min_stop_distance(min_stop_dist)`**, **L417 `_check_position_management` chama `check_virtual_trailing()` antes de `check_trailing_stop()`**, **V12.10: SpeedFilter integration, filter stats in HFT metrics report**, **V12.12: loss_exit/loss_max bypassam close cooldown (urgent)**, **V12.13: chama strategy.notify_close_pnl(pnl) após close**, **V12.14: strategy.on_tick(tick) no loop; set_position_side(None, close_price=last_tick.mid); strategy.set_point(self._point); reentry diagnostics em _report_hft_metrics** |
| Speed Filter | `core/speed_filter.py` | DONE | **V12.10: Rewritten+Calibrated** — EMA-smoothed speed (alpha=0.4, clamp=80), composite strength (range 40% + consistency 35% + accel 25%), 5 states (LENTO/NEUTRO/ACELERANDO/FORTE/EXAUSTAO), allow NEUTRO+ACELERANDO+FORTE, block LENTO+EXAUSTAO, chop gate (consistency<0.45 + speed<0.8×threshold), NEUTRO min strength=0.20, adaptive threshold with 70/30 smoothing, SpeedFilterStats, diagnostic logs every 10s; **49/49 tests pass**, selectivity: slow=0% allowed, normal=100%, active=100%, chop=50% blocked |
| MicroStructure Engine | `core/micro_structure.py` | DONE | **V12.14: MicroStructureEngine** — tick-based MicroCandle (15 ticks/candle), ring buffer 3 candles, finalize() com direction/body_ratio/wick_ratios/strength; ReentryResult com 7 sub-scores + final_score + echo_blocked + threshold + mode; evaluate_reentry() scoring probabilístico (retrace×0.30 + breakout×0.20 + structure×0.15 + consistency×0.15 + velocity×0.10 - chop_pen - spread_pen); anti-echo hard gate (preço <3pts close + sem contexto); adaptive threshold (freq-based); `get_diagnostics()`; **17/17 tests pass**; benchmark: ~400-800µs/eval |
| Entry Point | `__main__.py` + `__init__.py` | DONE | `python -m hft_bot` (from parent dir) ou `python main.py` (from hft_bot dir) |
| Requirements | `requirements.txt` | DONE | MetaTrader5, numpy |

---

## MUDANÇAS REALIZADAS (V12.14) — MICRO STRUCTURE REENTRY ENGINE

### Diagnóstico V12.13 (reentry displacement gate)

**Problema**: Displacement gate simples (|disp| ≥ 8pts) é binário — não distingue pullback saudável de breakout chase. Echo trades (re-entry no mesmo preço sem retracement/breakout/consistência) não eram bloqueados. Threshold fixo não adapta à frequência de trading.

### 1. MicroStructureEngine — `core/micro_structure.py`

**Antes (V12.13)**: `_check_hft_entry` verificava `|displacement| >= reentry_min_displacement_pts (8.0)` — gate binário. Echo trades com disp≥8 passavam. Pullbacks com disp<8 mas contexto saudável eram bloqueados.

**Depois (V12.14)**: MicroStructureEngine com scoring probabilístico de 7 componentes:

| Component | Weight | Description |
|-----------|--------|-------------|
| retrace_score | 0.30 | Pullback saudável: min(current, last2) body_ratio>0.3 na direção oposta |
| breakout_score | 0.20 | Breakout real: candle breaking previous high/low com body_ratio>0.3 |
| structure_score | 0.15 | 2 de 3 candles alinhados na direção do sinal |
| consistency_score | 0.15 | dir_align×0.6 + vel_ratio×0.2 + disp_score×0.2 |
| velocity_score | 0.10 | vel_fast vs threshold (speed_threshold do SpeedFilter) |
| chop_penalty | -max 0.10 | LENTO/EXAUSTAO no SpeedFilter → penalidade proporcional |
| spread_penalty | -max 0.05 | Spread > max_spread → penalidade proporcional |

**Score final**: `raw = retrace×0.30 + breakout×0.20 + structure×0.15 + consistency×0.15 + velocity×0.10 - chop_pen - spread_pen`

**Echo detection** (hard gate): se `|price - last_close| < echo_proximity_pts (3.0)` E `retrace<0.3` E `breakout<0.5` E `consistency<0.4` → score ×0.1 (quase bloqueia)

**Weak pullback/breakout**: retrace ou breakout >0 mas <0.3 → score ×0.3 (reduz sem matar)

**Adaptive threshold**:
| Frequency | Threshold Adjustment | Effect |
|-----------|---------------------|--------|
| < target×0.5 (<1.5/min) | -0.15 (min 0.30) | Relaxa — mais trades em baixa freq |
| < target (<3/min) | -0.08 | Leve relaxamento |
| > target×1.5 (>4.5/min) | +0.08 | Aperta — frequência ok |
| > target×2.5 (>7.5/min) | +0.15 (max 0.80) | Aperta — overtrading |

**MicroCandle**: tick-based (15 ticks/candle ≈ 150-300ms em WINM26). Ring buffer 3 slots, finalize() computa direction(+1/-1/0), body_ratio, wick_upper/lower_ratio, strength=body_ratio×direction.

### 2. ReentrySettings — `config/settings.py`

**14 parâmetros**: `enabled=True, candle_ticks=15, retrace_weight=0.30, breakout_weight=0.20, structure_weight=0.15, consistency_weight=0.15, velocity_weight=0.10, chop_penalty_max=0.10, spread_penalty_max=0.05, threshold_base=0.55, echo_proximity_pts=3.0, freq_target=3.0, freq_window_s=60.0`

**Obsoleto**: `reentry_min_displacement_pts` (V12.13) — substituído por scoring probabilístico.

### 3. Integração em momentum_burst.py

- `_reentry_engine = MicroStructureEngine(settings.reentry, tick_engine, speed_filter)` instanciado em `__init__`
- `on_tick(tick)` → `_reentry_engine.on_tick(tick)` — engine recebe todos ticks
- `set_point(point)` → `_reentry_engine.set_point(point)` — propaga point para conversões
- `set_position_side(side, close_price=0.0)` → `_last_close_price = close_price` — rastreia preço de close
- `notify_trade_time()` → `_reentry_engine.notify_trade()` — engine conta trades/min
- `_check_hft_entry` e `_check_idle_fallback` (BUY+SELL): `evaluate_reentry(side, price)` substitui displacement gate
- `[REENTRY SCORE]` log com todos sub-scores + threshold + decision

### 4. Integração em main.py

- `strategy.on_tick(tick)` no tick loop (quando reentry enabled)
- `strategy.set_position_side(None, close_price=last_tick.mid)` em ambos close paths
- `strategy.set_point(self._point)` após `set_instrument_info()`
- `_report_hft_metrics()` inclui: `reentry_thresh`, `reentry_tpm`
- Import `MicroStructureEngine` no topo

### 5. Test suite — `tests/test_micro_structure_reentry.py` (17 tests)

| # | Scenario | Expected | Key Assertion |
|---|----------|----------|---------------|
| 1 | Pullback after close (retrace candle) | ALLOW | retrace_score eleva score |
| 2 | Breakout after close (breaking candle) | ALLOW | breakout_score eleva score |
| 3 | Echo trade (price≈close, no context) | BLOCK | echo detection ×0.1 |
| 4 | Chop market (LENTO speed filter) | BLOCK | chop_penalty + low scores |
| 5 | Fake breakout (breakout + immediate reversal) | BLOCK | structure contradicts |
| 6 | Retrace + reaccelerate | ALLOW | retrace + structure + velocity |
| 7 | Structural reversal (3 candles against) | BLOCK | structure_score=0 |
| 8 | Flip entry (opposite side) | NO GATE | flip bypasses engine |
| 9 | First trade (no close history) | NO GATE | no _last_close_price |
| 10 | Sell-side pullback | ALLOW | retrace works SELL side |
| 11 | Adaptive threshold (low freq) | RELAX | threshold drops below base |
| 12 | Candle finalization (15 ticks) | CORRECT | direction, body_ratio, wicks |
| 13 | Deep retrace penalty | REDUCED | retrace>0.8 → ×0.5 penalty |
| 14 | No retrace + no breakout | BLOCK | both 0 → raw score low |
| 15 | Spread penalty | REDUCED | high spread → penalty |
| 16 | Retrace priority > breakout | CONFIRMED | retrace_weight > breakout_weight |
| 17 | Performance benchmark | <1ms/eval | ~400-800µs measured |

### 6. test_reentry_gate.py atualizado

- `_init_strategy()` helper chama `set_point(5.0)` além de `set_instrument_info`
- Testes usam `close_price` em `set_position_side(None, close_price=...)`
- Pullback tests feed mixed candles ao engine via `on_tick()`

### 7. Bug fixes durante integração

- **main.py indentation**: watchdog/reentry/tick loop indent 8→16 spaces; `_report_hft_metrics` body indent 8→12
- **momentum_burst.py indentation**: idle_fallback inner `if` indent 8→12; SELL branch indent 4→8
- **Residual `reentry_min_disp`** removido de `_check_idle_fallback` L309

---

## MUDANÇAS REALIZADAS (V12.13) — REENTRY DISPLACEMENT GATE + BUG FIX

### Análise de Re-entry (318 closes, logs combinados V12.11-12)

**Dados extraídos** (cross-referencing SIGNAL ENTRY + POSICAO FECHADA):

| Re-entry Type | N | WR | Avg PnL |
|---|---|---|---|
| Same-side after loss (CHASE) | 61 | 60.7% | +0.18 |
| Flip after loss | 51 | 49.0% | -0.94 |
| Same-side after WIN | 93 | 62.4% | -0.38 |
| **Quick+HighDisp (<5s, >5pt)** | **21** | **71.4%** | **+2.43** |
| **Quick+LowDisp (<5s, <=5pt)** | **5** | **80%** | **+2.00** |
| Slow+HighDisp (>=5s, >5pt) | 26 | 53.8% | -1.85 |
| **Slow+LowDisp (>=5s, <=5pt)** | **9** | **44.4%** | **-0.22** |

**Displacement vs outcome (all trades)**:
- |disp| <= 5pt: N=67, WR=52.2%, AvgPnL=-1.0
- |disp| 5-15pt: N=150, WR=51.3%, AvgPnL=-2.31
- **|disp| > 15pt: N=99, WR=74.7%, AvgPnL=+3.21**

**Conclusão**: Chase entries (same-side after loss) são +EV vs flip (-0.94). O problema real é **baixo displacement** — entrar no mesmo preço com momentum fraco. Quick re-entries com high disp são as melhores (71.4% WR, +2.43). **Cooldown mataria os trades mais lucrativos** — a solução é um displacement gate, não tempo.

### 1. Reentry displacement gate (reentry_min_displacement_pts=8.0)

**Arquivos**: `strategies/momentum_burst.py:199-209`, `config/settings.py:85`

**Antes (V12.12)**: Same-side re-entry após loss usava o mesmo `hft_min_displacement_pts=4.0` que entradas normais. Com disp=4-5pts (momentum fraco), WR=52.2% e avg PnL negativo.

**Depois (V12.13)**:
- `PositionSettings.reentry_min_displacement_pts = 8.0` — threshold separado para re-entry
- `_check_hft_entry`: se `_last_close_pnl < 0` e `_last_close_side == same direction`, requer `|displacement| >= 8pts`
- `_check_idle_fallback`: mesmo gate para fallback entries
- `_last_close_pnl = 0.0` resetado quando nova posição abre (evita stale state)
- `[REENTRY BLOCKED]` log com displacement e required threshold

**Por quê**: Dados mostram que |disp|>5pt com same-side após loss = 68.2% WR, +2.32. |disp|<=5pt = 57.1% WR, +0.57. O gate em 8pts (vs hft_min=4pts) exige confirmação de momentum mais forte para re-entry após loss, mantendo entradas rápidas válidas quando o mercado está se movendo. Flip entries não são afetadas (podem entrar com disp=4pt normal).

### 2. Bug fix: set_position_side(BUY) não setava _position_side

**Arquivo**: `strategies/momentum_burst.py:38-40`

**Antes (V12.12)**: `if side is not None and self._position_side is None: self._position_entry_time = time.time()` — **não** setava `self._position_side = side`. Resultado: `_position_side` sempre None, `_last_close_side` sempre None (elif branch nunca executava porque `_position_side is not None` era sempre False).

**Depois (V12.13)**: `self._position_side = side` adicionado no if branch. `_last_close_pnl = 0.0` resetado quando nova posição abre.

**Impacto**: Este bug existia desde V12.9+. Significava que o post_close_cooldown (L191-195) NUNCA funcionava — `_last_close_side` era sempre None, então as condições `self._last_close_side == OrderSide.BUY` eram sempre False. Agora o cooldown funciona corretamente E o novo reentry gate também.

### 3. notify_close_pnl(pnl) — strategy recebe PnL do close

**Arquivos**: `strategies/momentum_burst.py:47-48`, `main.py:425,391`

**Antes (V12.12)**: Strategy não sabia se close foi win ou loss. Reentry gate precisava dessa informação.

**Depois (V12.13)**: `main.py` chama `self._strategy.notify_close_pnl(pnl)` após close bem-sucedido (tanto normal quanto broker-close). Strategy armazena em `_last_close_pnl` para uso no reentry gate.

---

## MUDANÇAS REALIZADAS (V12.12) — LATENCY FIX + LOSS_EXIT URGENT BYPASS

### Diagnóstico V12.11 (19/05/2026, 10:00-10:23, ~23min)

**Métricas**: 173 trades, **61.8% WR** (107W/54L/12BE), avg_win=+4.93pts, avg_loss=-8.02pts, **PnL=+94pts**, 7.55 trades/min.

**Problemas críticos**:
1. **Latência avg envenenada por outliers**: `_avg_latency()` fazia `sum/len` simples em deque(maxlen=50). Um outlier de 22,888ms arrastava a média para >500ms, mantendo risk_block ativo por dezenas de samples. Pós-restart (10:44+): 204 sinais bloqueados por risk_block, avg_latency=815.7ms stuck
2. **Loss_exit overshoot**: loss_min=18 gera CLOSE, mas execução tem 500ms cooldown entre close attempts + sync_with_mt5 latency → losses de -23pts quando trigger era 18pts (5pts de overshoot). 21 losses ≥10pts totalizaram -289pts
3. **SpeedFilter 88% LENTO com threshold=5.5**: threshold real varia por EMA smoothing (3.0-3.5 vs esperado 2.75). EMA warmup após restart parte de speed_threshold=5.5 e decai lentamente

**Raiz**: (1) Média simples de latência é estatisticamente inválida — outliers de demo server (8-22 segundos) são eventos extremos que não representam latência real. Trimmed mean + outlier cap resolvem. (2) loss_exit é não-urgente no código → sofre 500ms close cooldown → preço move 5-10pts contra enquanto espera. loss_exit DEVE ser urgente.

### 1. avg_latency: simple mean → trimmed mean + outlier rejection (>5000ms)

**Arquivo**: `core/risk_engine.py:97-99,287-290`

**Antes (V12.11)**: `_avg_latency()` = `sum(samples) / len(samples)` — média simples. Outlier de 22,888ms em 50 samples → avg = 457+815ms → risk_block todos os sinais. `record_latency()` aceitava qualquer valor >0.

**Depois (V12.12)**: 
- `record_latency()`: rejeita samples >5000ms com warning log ("Latência extrema ignorada (outlier)") — demo server spikes de 8-22s são eventos de conexão, não latência real de trading
- `_avg_latency()`: usa trimmed mean — ordena samples, remove top/bottom 10% (min 1 de cada lado), calcula média dos restantes. Para <5 samples, usa `statistics.median()` como fallback

**Por quê**: Média simples é extremamente sensível a outliers (não-robusta). Um único outlier de 22s arrasta a média de 50 samples por dezenas de ciclos. Trimmed mean descarta os extremos, representando a latência "típica" do sistema. Cap de 5000ms previne que eventos de reconexão/demo lag entrem no pool — latência real de trading nunca excede 5s em condições normais. Resultado esperado: avg_latency volta para ~150-200ms (faixa normal demo), risk_block desbloqueia.

### 2. loss_exit e loss_max bypassam close cooldown (urgent)

**Arquivo**: `main.py:378`

**Antes (V12.11)**: `is_urgent = signal.reason in ("session_block", "shutdown", "daily_loss_limit")` — loss_exit e loss_max não eram urgentes → sofreriam 500ms cooldown entre close attempts.

**Depois (V12.12)**: `is_urgent = signal.reason in ("session_block", "shutdown", "daily_loss_limit", "loss_exit", "loss_max")` — loss_exit e loss_max bypassam cooldown, executam close imediato.

**Por quê**: Loss_exit fires quando adverse >= loss_min_pts (18). Cada ms de delay = preço pode mover mais contra. Em 500ms de cooldown, WINM26 pode mover 5-10pts (em momentum adverso). Loss de -18pts (trigger) vira -23pts (executado). Com urgent bypass, close é imediato → reduz overshoot de loss. Session_block/shutdown/daily_loss_limit continuam urgentes. Risk: mais close attempts em sequência → mitigado pelo execution_engine.is_execution_busy check.

---

## MUDANÇAS REALIZADAS (V12.11) — R:R FIX + SPEED FILTER RELAX + TRAILING TUNING

### Diagnóstico V12.10 (19/05/2026, 09:10-09:25, ~15min)

**Métricas**: 75 trades, **66.7% WR** (50W/23L/2BE), avg_win=+3.7pts, avg_loss=-11.4pts, **PnL=-79pts**, 4.93 trades/min, avg_hold=10.6s, avg_latency=169ms, avg_slippage=7.5 ticks.

**Problemas críticos**:
1. **R:R destrutivo**: avg win +3.7pts vs avg loss -11.4pts (1:3). Mesmo com 67% WR, sistema é perdedor. 33 small wins (1-3pts) = +69pts vs 14 big losses (≥10pts) = -230pts
2. **SpeedFilter 91% LENTO**: 82,000+ avaliações, ~91% bloqueadas. Mercado LENTO na maior parte do tempo com threshold=8.0
3. **Virtual trailing breakeven stops**: activation=10 fazia trailing desativar quando profit caía abaixo de 10pts → sai em breakeven +1-5pts (não captura moves)
4. **258 position_exists blocks + 220 below_loss_min blocks**: sinais válidos bloqueados por posição aberta ou reversal gate muito restritivo

**Raiz**: loss_min=25 segura trades ruins até -25pts (losses avg -11.4). Virtual trailing com activation=10+offset=5 captura só gains de 1-5pts (breakeven territory). SpeedFilter threshold=8.0 bloqueia mercado normal (speed 3-7 pts/s).

### 1. loss_min_pts: 25.0 → 18.0

**Arquivo**: `config/settings.py:82`

**Antes (V12.10)**: loss_min_pts=25.0 — losses segurados até -25pts. Avg loss=-11.4pts mas 14 trades com loss≥10pts totalizaram -230pts.

**Depois (V12.11)**: loss_min_pts=18.0 — sai de trades ruins ~30% mais rápido. Evita boundary noise de 15pts (V12.3: 71% exits em adverse=15, WR=24%). 18pts é sweet spot: 3pts acima do problemático 15, 7pts abaixo do 25 que segurava demais.

**Por quê**: V12.3 com loss_min=15 colapsou (24% WR, boundary noise). V12.6 com 25 funcionou (47% WR) mas losses eram grandes demais para wins de +3.7. 18pts dá espaço para trailing ativar (agora em +6pts) e preço reverter, mas corta losses antes de acumular -25 a -35pts.

### 2. trailing_activation_pts: 10.0 → 6.0

**Arquivo**: `config/settings.py:74`

**Antes (V12.10)**: activation=10.0 — trailing só ativava com +10pts lucro. Na prática, profit frequentemente caía abaixo de 10 antes de trailing proteger → breakeven stop em +1-5pts.

**Depois (V12.11)**: activation=6.0 — trailing ativa com +6pts lucro. Com virtual offset=8, trailing protege a partir de profit≥6pts com 8pts de margem.

**Por quê**: Dos 50 wins de V12.10, 33 eram de 1-3pts (breakeven stops). Trailing nunca capturou moves porque activation=10 era muito alto — profit tocava 10, trailing ativava, mas qualquer pullback desativava (profit<10). Com activation=6, mais trades atingem ativação e trailing tem 8pts de margem para pullbacks (6-8=-2 máximo drawdown antes de breakeven).

### 3. trailing_virtual_offset_pts: 5.0 → 8.0

**Arquivo**: `config/settings.py:77`

**Antes (V12.10)**: offset=5.0 — trailing muito tight, saía no primeiro pullback de 5pts. Com activation=10, trades que atingiam +10pts perdiam tudo quando preço recuava 5pts (breakeven +5pts).

**Depois (V12.11)**: offset=8.0 — trade respira 8pts de pullback (R$1.60). Com activation=6, trailing aperta SL a 8pts atrás do melhor preço. Trade com +10pts tem SL em +2pts (captura mínimo +2pts se reverter).

**Por quê**: Offset=5 com activation=10 = margem negativa (trailing desativa antes de proteger). Offset=8 com activation=6 = margem positiva de 2pts (trade que atinge +6pts e recua 8pts = sai em -2pts vs entry, mas na prática trailing já protegeu parte). Mais trades capturam moves de 6-15pts em vez de sair em breakeven.

### 4. speed_threshold: 8.0 → 5.5

**Arquivo**: `config/settings.py:117`

**Antes (V12.10)**: speed_threshold=8.0 — LENTO = speed<4.0 pts/s. 91% dos ticks bloqueados. Mercado WINM26 normal tem speed 3-7 pts/s em micro-moves.

**Depois (V12.11)**: speed_threshold=5.5 — LENTO = speed<2.75 pts/s. NEUTRO ≥ 2.75, ACELERANDO ≥ 3.575, FORTE ≥ 5.5. Espera rejeição ~60-70% (vs 91%).

**Por quê**: Threshold=8.0 era calibrado para burst conditions (5-8 pts/50ms = 100+ pts/s). Micro-scalping opera em condições normais (3-7 pts/s). Com threshold=5.5, NEUTRO e ACELERANDO cobrem a faixa 2.75-5.5 que é o regime normal de operação. Apenas mercado genuinamente parado (<2.75 pts/s) é bloqueado.

### 5. loss_max_pts: 40.0 → 35.0

**Arquivo**: `config/settings.py:83`

**Por quê**: Alinhado com loss_min=18. Gap loss_min→loss_max era 15pts (25→40), agora 17pts (18→35). Proporcionalmente similar. Limita perda máxima a 35pts (R$7.00).

### 6. reversal_min_disp: 5.0 → 9.0

**Arquivo**: `config/settings.py:84`

**Antes (V12.10)**: reversal_min_disp=5.0 — permitia reversal com disp adverso ≥5pts, muito fácil.

**Depois (V12.11)**: reversal_min_disp=9.0 — metade de loss_min=18. Reversal requer displacement adverso real (≥9pts = mercado efetivamente reverteu).

**Por quê**: Com loss_min=18, reversal com disp=5 era desproporcional — mercado mal moveu e já tentávamos reverter. 9pts = 50% de loss_min, consistente com a lógica de que reversal só faz sentido quando adverse é significativo mas ainda não atingiu loss_exit.

---

## MUDANÇAS REALIZADAS (V12.10) — SPEED FILTER REWRITE + CALIBRATION + TICK ENGINE PUBLIC INTERFACE

### Diagnóstico

SpeedFilter original tinha métricas e lógica de gate inadequadas para HFT:
1. **strength = body / (ask - bid)**: spread WINM26 ~5pts é tiny vs range real → strength sempre ~1.0, sem poder discriminatório
2. **speed = move / period**: pts por tick-period, não normalizado pelo tempo real entre ticks → varia com tick rate
3. **allowed=False por default**: só FORTE passava → matava frequência (NEUTRO e ACELERANDO bloqueados)
4. **Acesso a `_ticks` privado do TickEngine**: acoplamento direto ao buffer interno, violando encapsulamento
5. **Sem métricas agregadas**: impossível diagnosticar taxa de rejeição, distribuição de estados
6. **Acelerando branch unreachable**: gate com `else` morto após ACELERANDO, nunca alcançado
7. **NEUTRO era free pass**: qualquer sinal moderado passava sem verificação de qualidade

### 1. SpeedFilter reescrito + calibrado — `core/speed_filter.py`

**Antes (V12.9)**: strength = body / (ask - bid), speed = move / period, 3 estados (LENTO/RAPIDO/EXAUSTAO), allowed=False default, acesso a `_ticks` privado, NEUTRO free pass, ACELERANDO unreachable.

**Depois (V12.10 calibrado)**:
- **EMA-smoothed speed**: alpha=0.4, clamp=80 pts/s. `smoothed = alpha * raw + (1-alpha) * prev_smoothed`
- **Composite strength** = range_strength×0.40 + directional_consistency×0.35 + normalized_accel×0.25 (clamped 0-1.5)
- **range_strength** = |price_span_pts| / directional_range_pts (high-past.mid BUY, past.mid-low SELL, max 2.0)
- **normalized_accel** = min(max(accel/10.0, 0), 1.0) — /10.0 (era /20.0, mais responsivo)
- **5 estados** com gate calibrado:
  - LENTO: speed < threshold×0.5 → BLOCKED
  - NEUTRO: speed ≥ threshold×0.5 AND accel>0 AND consistency≥chop_threshold(0.45) AND strength≥neutro_min(0.20) → ALLOWED
  - ACELERANDO: speed ≥ threshold×0.65 AND consistency > 0.55 → ALLOWED (chop sub-check: consistency<0.45 AND speed<0.8×threshold → LENTO)
  - FORTE: speed ≥ threshold AND strength>0.45 AND consistency>0.50 AND accel>0 → ALLOWED
  - EXAUSTAO: speed > threshold×1.3 AND strength < exhaustion(0.30) → BLOCKED (override de NEUTRO/ACELERANDO/FORTE)
- **Chop gate**: dual condition (consistency<0.45 AND speed<0.8×threshold) — single condition era muito agressiva
- **Adaptive threshold**: base×spread_mult×range_mult×vel_mult, smoothed 70/30 (prev/new) — previne flip-flop
- **SpeedFilterStats**: total_evaluations, blocked_lento/exhaustao/chop, allowed_neutro/acelerando/forte, filter_rejection_rate
- **Diagnostic logs**: a cada 10s — estado, speed, strength, dir_consistency, accel, allowed, reason + stats agregados
- **`point` property**: usa `tick_engine.point` em vez de `tick_engine._point`

**Calibration changes from initial V12.10**:
| Parameter | Before | After | Reason |
|-----------|--------|-------|--------|
| chop_consistency_threshold | 0.35 | **0.45** | Zigzag with 0.52 consistency now filtered |
| strength_exhaustion | 0.15 | **0.30** | Accel /10.0 raises strength values, threshold must match |
| neutro_min_strength | N/A | **0.20** | NEUTRO no longer free pass — requires minimum quality |
| ACELERANDO consistency gate | ≥0.4 | **>0.55** | Filters low-consistency mid-speed |
| NEUTRO else branch | allowed | **BLOCKED (LENTO)** | Must have strength≥0.20, accel>0, consistency≥0.45 |
| Accel normalization | /20.0 | **/10.0** | More responsive to real acceleration |

**Selectivity results (49/49 tests pass)**:
| Scenario | Allowed | Blocked | States |
|----------|---------|---------|--------|
| Slow (1pt/200ms) | 0% | 100% | LENTO only |
| Normal (3pt/100ms) | 100% | 0% | FORTE 50% + ACELERANDO 50% |
| Active (5pt/50ms) | 100% | 0% | FORTE 60% + ACELERANDO 40% |
| Chop (±5pt/100ms) | 50% | 50% | FORTE 36% + LENTO 49% + ACELERANDO 0.3% + NEUTRO 13% |
| Burst (8-22pt/30ms) | 100% | 0% | ACELERANDO 83% + FORTE 17% |

**Por quê**: O SpeedFilter anterior matava frequência porque (a) strength baseado em spread era metricamente inútil (sempre ~1.0), (b) NEUTRO era bloqueado por default, (c) só FORTE passava, (d) ACELERANDO era unreachable. Com nova métrica de strength, gate permissivo (allow 3 de 5 estados), e NEUTRO com min strength, o filtro bloqueia apenas entradas genuinamente ruins: LENTO (mercado parado), EXAUSTAO (blowoff), chop (zigzag sem direção). NEUTRO agora requer qualidade mínima (strength≥0.20, accel>0, consistency≥0.45) — previne overtrade.

### 2. TickEngine.get_recent_ticks(count) — interface pública

**Arquivo**: `core/tick_engine.py`

**Antes**: SpeedFilter acessava `_ticks` (buffer privado) diretamente.

**Depois**: `get_recent_ticks(count: int) -> List[TickData]` — retorna os últimos `count` ticks do buffer. SpeedFilter usa `tick_engine.get_recent_ticks(self._speed_period + 1)` para speed e `tick_engine.get_recent_ticks(self._micro_range_window)` para strength.

**Por quê**: Encapsulamento — SpeedFilter não deve depender de internos do TickEngine. Método público permite mudança de implementação do buffer sem quebrar consumidores.

### 3. SpeedFilterSettings — `config/settings.py`

**Arquivo**: `config/settings.py`

**Dataclass (9 fields)**:
- `speed_period: int = 5` — número de ticks para cálculo de speed
- `speed_threshold: float = 8.0` — threshold de speed (pts/second) para classificação
- `strength_exhaustion: float = 0.30` — strength abaixo deste valor com speed alta = EXAUSTAO (era 0.15)
- `micro_range_window: int = 30` — janela de ticks para cálculo de directional range
- `chop_consistency_threshold: float = 0.45` — consistency abaixo = chop candidato (era 0.35)
- `chop_speed_cap_factor: float = 0.8` — speed abaixo de threshold×factor = chop confirmado
- `neutro_min_strength: float = 0.20` — strength mínimo para NEUTRO ser ALLOWED (NEW)
- `ema_alpha: float = 0.4` — EMA smoothing factor para speed
- `speed_clamp: float = 80.0` — speed máximo antes de clamp

**Por quê**: Parâmetros do SpeedFilter externalizados em settings, configuráveis via JSON. Valores calibrados: exhaustion=0.30 (com accel/10.0, strength values são maiores), chop_threshold=0.45 (zigzag 0.52 consistency agora filtrado), neutro_min=0.20 (NEUTRO requer qualidade mínima), ema_alpha=0.4 (rápido para HFT, lento o suficiente para suprimir spikes).

### 4. main.py integração — SpeedFilter no signal path + stats no report

**Arquivo**: `main.py`

- SpeedFilter instanciado com todos os 9 params do settings
- `evaluate()` chamado antes de aceitar sinal — se `not allowed`, sinal bloqueado
- Filter stats incluídos em `_report_hft_metrics()` e `_get_final_status()`
- `get_metrics_summary()` retorna dict com rejection rate, blocked counts, allowed counts
- Diagnostic logs: estado, speed, strength, dir_consistency, accel, adaptive_threshold, allowed, blocked_reason

### 5. TickEngine.point — propriedade pública

**Arquivo**: `core/tick_engine.py`

**Antes**: SpeedFilter acessava `_point` (atributo privado) diretamente.

**Depois**: `point` property pública — `tick_engine.point` em vez de `tick_engine._point`.

**Por quê**: Encapsulamento — consumidores não devem acessar atributos privados. Property permite validação (retorna 0.0 se não inicializado).

### 6. Test suite — `tests/test_speed_filter.py`

**49/49 tests pass**: 27 unit tests + 4 selectivity scenarios + 2 gate boundary + 1 point property + 1 mixed scenario + 1 NEUTRO min strength + 1 detailed metrics dump + 12 core logic tests.

### 5. trailing_virtual_offset_pts: 8.0 → 5.0 (correção de settings)

**Arquivo**: `config/settings.py:77`

**Antes**: trailing_virtual_offset_pts=8.0 (valor documentado em V12.9 mas settings real era 5.0 desde implementação).

**Depois**: trailing_virtual_offset_pts=5.0 — consistente com valor real em produção. Offset 5pts = R$1.00 atrás do preço (vs 8pts = R$1.60). Mais tight = captura mais gains.

---

## MUDANÇAS REALIZADAS (V12.9) — VIRTUAL TRAILING + LOSS_MIN=25 + RELAXED ENTRY FILTERS

### Diagnóstico Cross-Version (V7→V12.8)

**Análise completa de todas versões de produção revelou**:

| Version | WR% | Trades/min | PnL | loss_min | Trailing | Key |
|---------|-----|------------|-----|----------|----------|-----|
| V7 | 37.8% | ~15 | -407 | N/A | 80pts | Exits prematuros |
| V11.1 | 39.6% | 0.80 | +7 | 30 | offset=2pts | **58.9% WR com trailing** |
| V12.2 | 44.2% | 1.31 | +766 | 30 | 1242 mods | Melhor PnL |
| V12.3 | 24% | 1.5 | -276 | 15 | **0** | loss_min=15 mata trailing |
| V12.6 | 47% | 3-5 | +17 | 25 | 217 act | Melhor WR c/trailing broker |
| V12.7 | 38.1% | 8.39 | -88 | 15 | decorative | Alta freq, baixo WR |

**Descobertas**:
1. **Trailing efetivo = WR alto**: V11.1 com offset=2pts → 58.9% WR com trailing. Atual offset=200pts = decorativo (SL R$40 atrás, nunca protege gains de R$1-2)
2. **loss_min=15 = boundary noise**: V12.3 (71% exits no mínimo), V12.8-log (77.6% exits em adverse=15 exato). loss_min=25 = provado (V12.6: 47% WR, +17pts)
3. **Entry filters muito restritivos matam freq**: V12.7 vel=8.0/disp=5.0/thresh 6/8/12 cortaram ~44% entries por acc gate
4. **Hold<5s = 0% WR**: V12.7 dados, 27 trades com hold≤3.5s todos loss

### 1. Virtual Trailing Stop — `check_virtual_trailing()` (CODE CHANGE)

**Arquivo**: `core/position_manager.py:237-321`

**Antes (V12.8)**: Apenas `check_trailing_stop()` com offset=200pts (decorativo). SL fica R$40 atrás do preço — para avg_win de 6-7pts (R$1.20-1.40), trailing nunca aperta.

**Depois (V12.9)**: Novo método `check_virtual_trailing()`:
- SL rastreado internamente (`_virtual_trailing_sl`) — sem broker SL modify
- Quando bid/ask cruza virtual SL → emite `Signal(CLOSE, reason="virtual_trailing_stop")`
- Close via market order (execução normal do execution_engine)
- **offset = 8pts (R$1.60)** vs 200pts (R$40.00) do broker trailing
- Activation = +8pts profit (mesmo que broker trailing)
- Deactivation gate: virtual trailing desativa quando profit < activation_pts
- Log a cada 5 moves (reduz spam vs broker trailing a cada move)
- Zero 10016 risk (nunca modifica SL no broker)
- Zero ~89ms latency por trailing move (sem IPC order_send)

**Por quê**: V11.1 com trailing efetivo (offset=2pts) = **58.9% WR com trailing** vs 9.3% sem. A constraint de 200pts min stop distance do broker torna trailing baseado em broker incompatível com micro-scalping. Virtual trailing ignora essa constraint — o broker SL fica em 200pts atrás como safetynet, enquanto o virtual SL a 5pts atrás protege gains reais. Com avg_win ~6-10pts, offset=5pts captura a maioria do move.

**Integração**: `main.py:_check_position_management()` chama `check_virtual_trailing()` ANTES de `check_trailing_stop()`. Se virtual trailing trigger, close imediato. Broker trailing continua funcionando como backup decorativo.

### 2. trailing_activation_pts: 10.0 (mantido)

**Arquivo**: `config/settings.py:74`

**V12.9**: activation=10.0 mantido — exigia +10pts (R$2.00) lucro antes de trailing ativar. Com virtual offset=5pts, trade captura tudo acima de +10pts-5pts=+5pts (na prática, trailing protege gains a partir de activation).

**Por quê**: 10pts continua sendo o threshold de ativação. Com virtual trailing (offset=5pts vs 200pts decorativo), o trailing agora é EFETIVO — 10pts de ativação garante que só trades com lucro real ativam. V11.1 com activation=5pts tinha 61% de trades com trailing. Com 10pts, menos trades ativam mas os que ativam têm lucro mais significativo. Pode reduzir para 8pts se poucos trades ativarem.

### 3. loss_min_pts: 20.0 → 25.0

**Arquivo**: `config/settings.py:82`

**Antes (V12.8)**: loss_min=20.0 — V12.8-log ainda mostrava 77.6% exits em adverse=15 (V12.8 nunca deployado).

**Depois (V12.9)**: loss_min=25.0 — provado em V12.6 (47% WR, +17pts, 217 trailing activations).

**Por quê**: V12.3 loss_min=15 = 24% WR, 71% boundary exits, zero trailing. V12.6 loss_min=25 = 47% WR, trailing funcionando. V12.2 loss_min=30 = 44.2% WR, PnL=+766. 25 é o sweet spot entre frequency (mais rápido que 30) e WR (muito melhor que 15-20).

### 4. hft_min_velocity: 8.0 → 6.0

**Arquivo**: `config/settings.py:44`

**Antes (V12.8)**: hft_min_velocity=8.0 — V12.7 cortou muitos entries; 64% dos ticks em low regime com threshold=6.0, vel_fast precisava ≥6.0.

**Depois (V12.9)**: hft_min_velocity=6.0 — V12.2 usava threshold_low=4.0 com sucesso (44.2% WR). 6.0 filtra weakest entries (V11.1: vel<5=2% WR) mas permite vel 6-8 que V12.7 bloqueava.

**Por quê**: V12.7 cortou ~44% entries com filtros restritivos (vel=8 + acc_gate=ON). Frequência 8.39/min mas WR 38.1%. Com vel=6.0 + acc_gate=OFF + disp=4.0, espera-se +30% entries vs V12.7, mantendo qualidade superior a V12.2.

### 5. hft_min_displacement_pts: 5.0 → 4.0

**Arquivo**: `config/settings.py:50`

**Antes (V12.8)**: hft_min_displacement_pts=5.0 — V12.7 cortou entries com disp 4-5 (V12.2: disp 3-5 = 39% WR).

**Depois (V12.9)**: hft_min_displacement_pts=4.0 — captura disp 4-5 bucket (39% WR, aceitável) enquanto filtra disp 1-3 (3% WR).

**Por quê**: V12.2 provou que disp≥3 tem 39% WR. V12.7 com disp≥5 cortou esses entries. 4.0 é compromisso entre 3.0 (V12.2) e 5.0 (V12.7).

### 6. hft_min_micro_range: 3.0 → 2.0

**Arquivo**: `config/settings.py:45`

**Antes (V12.8)**: hft_min_micro_range=3.0 — V12.1 matou frequency com 3.0.

**Depois (V12.9)**: hft_min_micro_range=2.0 — V12.2 usou 2.0 com sucesso (44.2% WR).

**Por quê**: 3.0 era muito restritivo (V12.1 matou freq). 2.0 é provado (V12.2).

### 7. adaptive_thresholds: 6/8/12 → 5/7/10

**Arquivo**: `config/settings.py:121-123`

**Antes (V12.8)**: adaptive_threshold_low=6.0, mid=8.0, high=12.0 — V12.7 thresholds altos demais.

**Depois (V12.9)**: adaptive_threshold_low=5.0, mid=7.0, high=10.0 — V12.2 usou 4/6/10 (44.2% WR). 5/7/10 é ligeiramente mais rigoroso que V12.2, ainda menos restritivo que V12.7.

**Por quê**: 64% dos ticks em low regime. Com threshold_low=5.0, exige vel_fast ≥5.0 — filtra weakest (vel<5=2% WR) sem ser draconiano como 6.0.

### 8. fallback_min_velocity: 8.0 → 6.0

**Arquivo**: `config/settings.py:117`

**Por quê**: Alinhado com hft_min_velocity=6.0.

### 9. cooldown_after_loss_ms: 2000 → 1500

**Arquivo**: `config/settings.py:58`

**Antes (V12.8)**: cooldown_after_loss_ms=2000.

**Depois (V12.9)**: cooldown_after_loss_ms=1500 — V12.3 usou 1500ms com sucesso (3-5s cycles).

**Por quê**: 2s adiciona delay desnecessário. Com loss_min=25 (exits mais lentos), menos cooldowns acumulam. LOSS+flip mitigado pelo reversal gate + min_hold.

### 10. post_close_cooldown_s: 0.5 → 0.3

**Arquivo**: `config/settings.py:81`

**Antes (V12.8)**: post_close_cooldown_s=0.5.

**Depois (V12.9)**: post_close_cooldown_s=0.3 — previne same-tick echo trades, maximiza frequency.

**Por quê**: Com filtros de entry mais rigorosos que V11.1 (que tinha 52% re-entries <1s com cooldown=1.0s), 0.3s é suficiente para evitar echo trades do mesmo tick. Ganha 0.2s por cycle.

---

## MUDANÇAS REALIZADAS (V12.8) — CONFIG-ONLY: HOLD LONGER + WIDER LOSS BOUNDARY + EASIER REVERSAL + ACC GATE OFF

### Diagnóstico V12.7 (May 15, 18.5min + post-restart 11:42+)

**Métricas (18.5min)**: 155 trades, 38.1% WR, avg_win=+6.49, avg_loss=-5.23, PnL=-88pts, 8.39 trades/min.

**Métricas (post-restart)**: 59 trades, 30.5% WR, avg_win=+6.5, avg_loss=-3.89, PnL=-19pts, 8.19 trades/min.

**Descoberta crítica — Hold time vs Winrate**:
- hold≤3.5s: 27 trades, **0% WR**, Sum=-112pts (TODOS losses ou draws)
- hold>3.5s: 91 trades, 38.5% WR, Sum=-23pts
- hold≥5s: 65 trades, **44.6% WR**, Sum=**+48pts** ← lucrativo!
- hold=14s: 3 trades, 100% WR, Sum=+42pts
- **3s HOLD BUCKET**: 37 trades, 8% WR, Sum=-130pts — principal fonte de prejuízo

**Exit adverse distribution**: 57% no adverse=15 exato (boundary noise), 24% no adverse=20, 4% no adverse≥25

**Acceleration gate impact**: 44% de entries cortadas por acc negativo; momentum desacelerando mas direção frequentemente correta

**Reversals bloqueadas**: reversal_min_disp=10 bloqueia reversões com disp 5-10 quando loss já ≥15+; muito restrito

### 1. min_hold_seconds: 3.0 → 5.0

**Arquivo**: `config/settings.py:78`

**Antes (V12.7)**: min_hold_seconds=3.0 — trades com hold≤3.5s são 0% WR (27 trades, -112pts).

**Depois (V12.8)**: min_hold_seconds=5.0 — trades com hold≥5s são 44.6% WR (+48pts).

**Por quê**: Dados V12.7 provam que 3s min_hold é a principal fonte de prejuízo. Trades que saem em 3-3.5s são 100% losses — adverse atinge loss_min=15 e sai instantaneamente. 5s dá tempo para preço reverter ou trailing ativar. V12.6 com min_hold=5s tinha 47% WR e PnL=+17pts.

### 2. loss_min_pts: 15.0 → 20.0

**Arquivo**: `config/settings.py:80`

**Antes (V12.7)**: loss_min_pts=15.0 — 57% dos exits no adverse=15 exato (boundary noise).

**Depois (V12.8)**: loss_min_pts=20.0 — 5pts mais de espaço para reverter antes de loss_exit.

**Por quê**: Exits em adverse=15 eram em sua maioria noise — preço tocou 15pts contra e saiu imediatamente. Dar 5pts mais de espaço permite que trades que estão em -15 a -19 recuperem. Com min_hold=5s, trades ficam pelo menos 5s antes de qualquer exit.

### 3. reversal_min_disp: 10.0 → 5.0

**Arquivo**: `config/settings.py:82`

**Antes (V12.7)**: reversal_min_disp=10.0 — bloqueava reversões com disp 5-10 quando loss já ≥15+.

**Depois (V12.8)**: reversal_min_disp=5.0 — permite reversões quando disp adverso ≥5 e loss ≥20.

**Por quê**: Com loss_min=20, reversões precisam de menos displacement para fazer sentido. Disp 5-10 com loss≥20 indica que mercado já reverteu parcialmente. reversal_min_disp=5 é metade do loss_min=20 — consistente.

### 4. hft_acceleration_gate: True → False

**Arquivo**: `config/settings.py:51`

**Antes (V12.7)**: hft_acceleration_gate=True — 44% de entries cortadas por acc negativo.

**Depois (V12.8)**: hft_acceleration_gate=False — acc gate desativado, acc continua como booster no strength.

**Por quê**: V12.2 já tinha desativado o acc gate pelos mesmos motivos: acceleration = vel_very_fast(200ms) - vel_fast(500ms). Um pullback momentâneo de 200ms faz acc<0 mesmo em move forte de 500ms. Com vel_fast≥8.0 + disp≥5.0, direção já está confirmada. Acc negativo indica desaceleração mas não inversão. Acc continua como booster (strength×(1+acc×0.05)).

---

## MUDANÇAS REALIZADAS (V12.7) — CONFIG-ONLY: STRICTER ENTRY + FASTER EXIT + EARLIER REVERSAL

### Diagnóstico V12.6 (May 15, ~3.5h, 39 trades closed)

**Métricas**: 47% WR (15W/16L+8 draws), avg_win=+6.52pts (R$1.30), avg_loss=-7.91pts (R$1.58), PnL=+17pts, 3-5 trades/min, avg_hold=12.8s, avg_latency=130ms, 217 trailing activations, 419 trailing moves, zero 10016.

**Problemas**:
1. **Entries fracas**: displacement=5 em 25% (477/1975) — 5pts é ruído. Entries com vel_fast=5-10 (threshold boundary) entram sem direção forte.
2. **trend_bars=0 em 75%** (1483/1975) — último tick foi contra a direção do sinal e ainda entramos. trend_bars=1 só 473 (24%).
3. **Acceleration contraditória**: 54% entries com acc>0 (favorável), 46% com acc<0 (desacelerando). Metade das entries é em momentum que está morrendo.
4. **737 reversals bloqueadas** por `loss_min_pts=25` — mercado reverteu com disp 5-20 mas ficamos presos até adverse=25pts.
5. **Loss_exit sempre em adverse=25-35** — hold 5-42s em prejuízo. PnL por trade: losses de -4 a -17, wins de +1 a +20.
6. **Trailing offset=200pts decorativo** — ativa e move, mas SL fica R$40 atrás. Para avg_win=6.52pts (R$1.30), trailing nunca protege.

### 1. hft_min_velocity: 5.0 → 8.0

**Arquivo**: `config/settings.py:44`

**Antes (V12.6)**: hft_min_velocity=5.0 — 73% dos ticks usavam threshold=4.0 (low regime), entries com vel_fast=5 eram marginais.

**Depois (V12.7)**: hft_min_velocity=8.0 — exige velocity_fast ≥8.0 (ou ≥6.0 em low regime, ver threshold abaixo). Filtra entries com momentum fraco.

**Por quê**: Entries com vel_fast<8 tinham direção incerta. Com threshold_low=6.0 (abaixo), exige mínimo real de momentum. Dados V12.6: entries com |velocity|≥10 eram 1136 vs 417 com |vel|<5 — as fortes tinham mais direção.

### 2. hft_min_displacement_pts: 3.0 → 5.0

**Arquivo**: `config/settings.py:50`

**Antes (V12.6)**: hft_min_displacement_pts=3.0 — deixava passar disp=3-5 (ruído).

**Depois (V12.7)**: hft_min_displacement_pts=5.0 — exige ≥5pts de displacement na direção.

**Por quê**: Em V12.6, 477/1975 entries (25%) tinham displacement=5 exatamente — mínimo absoluto. Aumentar para 5.0 corta as mais fracas (disp 3-5 eram aceitas em V12.2 com WR=39%). Com threshold mais alto, só entramos quando preço moveu ≥5pts na direção.

### 3. hft_min_micro_range: 2.0 → 3.0

**Arquivo**: `config/settings.py:45`

**Antes (V12.6)**: hft_min_micro_range=2.0 — mercado com range 2pts era aceito.

**Depois (V12.7)**: hft_min_micro_range=3.0 — exige range ≥3pts.

**Por quê**: Micro_range=2 indica mercado muito quieto. Volatilidade ≥3pts confirma que há movimento real para capturar.

### 4. hft_acceleration_gate: False → True

**Arquivo**: `config/settings.py:51`

**Antes (V12.6)**: hft_acceleration_gate=False — entrava mesmo com momentum desacelerando (acc<0 para BUY).

**Depois (V12.7)**: hft_acceleration_gate=True — bloqueia entry quando acc contradiz a direção (acc<0 para BUY, acc>0 para SELL).

**Por quê**: Dados V12.6: 46% das entries tinham acc contrária (desacelerando). Essas entravam no final de um move, quando direção ia reverter. Acc gate exige que momentum esteja acelerando na direção do sinal. Nota: V12.1–V12.2 desabilitou este gate porque cortava entries em pullback momentâneo (200ms). Com threshold mais alto (6.0 vs 4.0), pullback de 200ms agora precisa ser >6.0 para gerar sinal — o gate corta genuínamente entries ruins, não pullbacks em moves fortes.

### 5. adaptive_threshold_low: 4.0 → 6.0

**Arquivo**: `config/settings.py:119`

**Antes (V12.6)**: adaptive_threshold_low=4.0 — 73% dos ticks em low regime, threshold muito permissivo.

**Depois (V12.7)**: adaptive_threshold_low=6.0 — exige vel_fast ≥6.0 em regime low (64% → menos ticks passam).

**Por quê**: Com threshold=4.0, vel_fast=5.0 já gerava sinal (5.0>4.0). Isso é ruído — momentum fraco = direção incerta. Com 6.0, precisa vel_fast ≥6.0 mesmo em regime low.

### 6. adaptive_threshold_mid: 6.0 → 8.0

**Arquivo**: `config/settings.py:120`

**Por quê**: Progressão 6→8→12 (era 4→6→10). Thresholds mais exigentes em todos os regimes.

### 7. adaptive_velocity_mid: 15.0 → 12.0

**Arquivo**: `config/settings.py:118`

**Por quê**: Muda a fronteira entre regime mid e high. avg_velocity <4=low (64%), 4-12=mid (mais estreito), ≥12=high. Mais ticks classificados como high (threshold=12) em vez de mid (threshold=8).

### 8. loss_min_pts: 25.0 → 15.0

**Arquivo**: `config/settings.py:80`

**Antes (V12.6)**: loss_min_pts=25.0 — 737 reversals bloqueadas por loss_min. Trades segurados em prejuízo até adverse=25-35pts (5-42s).

**Depois (V12.7)**: loss_min_pts=15.0 — saída por loss_exit quando adverse ≥15pts. Reversal gate usa 15pts.

**Por quê**: V12.3 testou 15pts e WR colapsou (24%) porque trailing nunca ativava (bug 100×). Agora o bug está corrigido. Com profit_pts correto, trailing ativa em +5pts antes de adverse atingir 15pts — trade tem janela de 20pts (5→15) para desenvolver lucro. Se adverse atinge 15pts sem trailing, saída rápida corta loss em vez de segurar até 25.

**Risco**: V12.3 com 15pts teve 71% exits no mínimo. Mas V12.3 tinha o bug de point=1.0 (profit 100× menor). Agora profit_pts é correto — trailing ativa de verdade.

### 9. loss_max_pts: 60.0 → 40.0

**Arquivo**: `config/settings.py:81`

**Por quê**: Limita perda máxima a 40pts (R$8.00) em vez de 60pts (R$12.00). Com SL broker=4000 ticks (40pts), loss_max=40pts = alinhado com SL. Se adverse>40, SL broker já protege.

### 10. hft_stop_loss_ticks: 6000 → 4000

**Arquivo**: `config/settings.py:24`

**Por quê**: SL broker=4000 ticks = 40pts. Alinhado com loss_max=40pts. 60pts (6000 ticks) era largo demais — perda de R$12.00 antes do broker SL.

### 11. reversal_min_disp: 25.0 → 10.0

**Arquivo**: `config/settings.py:82`

**Antes (V12.6)**: reversal_min_disp=25.0 (não usado diretamente — reversal usa loss_min_pts no código).

**Depois (V12.7)**: reversal_min_disp=10.0 — alinhado com loss_min_pts=15.0 (não diretamente, mas consistente).

**Por quê**: Consistência. reversal_min_disp era 25 (desalinhado com loss_min=15). 10pts é metade do loss_min — indica que displacement adverso é real mas ainda não atingiu loss_exit.

### 12. reversal_vel_mult: 1.5 → 1.2

**Arquivo**: `config/settings.py:83`

**Antes (V12.6)**: reversal_vel_mult=1.5 — reversal precisava vel_fast ≥1.5× threshold (≥6.0 em low).

**Depois (V12.7)**: reversal_vel_mult=1.2 — reversal precisa vel_fast ≥1.2× threshold (≥7.2 em low).

**Por quê**: Com loss_min=15 (vs 25), reversal acontece mais cedo. Vel×1.2 ainda exige momentum real (20% acima do threshold normal) mas é atingível quando mercado reverte forte. Permite sair mais rápido quando direção muda.

### 13. min_hold_seconds: 5.0 → 3.0

**Arquivo**: `config/settings.py:78`

**Antes (V12.6)**: min_hold_seconds=5.0 — posição presa por mínimo 5s.

**Depois (V12.7)**: min_hold_seconds=3.0 — posição pode sair após 3s.

**Por quê**: Avg_hold=12.8s em V12.6 era longo demais. Com entries mais precisas (acc gate + disp≥5 + vel≥8), se o trade vai contra em 3s, é melhor sair rápido. 3s protege contra noise de 1-2s mas permite cycle time mais rápido. Cycle potencial: entry(0s) → hold 3s → loss_exit adverse=15 → re-entry ~0.5s = 3.5-4s vs 13-16s em V12.2.

### 14. post_close_cooldown_s: 1.0 → 0.5

**Arquivo**: `config/settings.py:79`

**Antes (V12.6)**: post_close_cooldown_s=1.0 — 1s same-dir penalty após close.

**Depois (V12.7)**: post_close_cooldown_s=0.5 — 0.5s same-dir penalty.

**Por quê**: Com entries mais rigorosas (acc gate + vel≥8 + disp≥5), re-entries após close já são filtradas naturalmente. 0.5s previne echo trades de mesmo tick sem matar frequency em trends sustentados. Opposite-dir (reversals) já filtradas pelo reversal gate.

### 15. cooldown_after_loss_ms: 1500 → 2000

**Arquivo**: `config/settings.py:58`

**Por quê**: Aumentou de 1.5s para 2s. Com loss_min=15 (exits mais rápidos), mais losses vão acontecer. 2s dá mais tempo para o mercado estabilizar antes de re-entrar. LOSS+flip continua sendo o pior padrão.

### 16. trailing_activation_pts: 5.0 → 10.0

**Arquivo**: `config/settings.py:74`

**Por quê**: Com offset=200pts, trailing ativar em +5pts é inútil — SL fica 200pts atrás, nunca protege. 10pts exige lucro mais significativo (R$2.00) antes de tentar trailing. Com acc gate + vel mais alto, trades que atingem +10pts têm momentum mais forte = mais probabilidade de continuar.

### 17. fallback_min_velocity: 4.0 → 8.0

**Arquivo**: `config/settings.py:115`

**Por quê**: Alinhado com hft_min_velocity=8.0. Fallback = idle entry quality. Se exige vel≥8.0 no HFT path, fallback não deve ser mais fraco (4.0 era metade).

---



### Diagnóstico V12.5

V12.5 corrigiu o bug de `100 * self._point` (profit_pts agora correto), mas May 14 mostrou 5143 "Trailing SL modify rejeitado | Retcode: 10016". Causas: (1) `trailing_offset_pts=7.0` → `offset_price=7*1.0=7.0` → SL fica 7pts do bid/ask, broker exige ≥200pts; (2) `_trailing_activated` ficava True permanentemente — quando profit caía abaixo de activation_pts, flag não resetava, trailing continuava tentando mover SL em prejuízo; (3) sem validação de min_stop_distance no cálculo de new_sl.

### 1. trailing_offset_pts: 7.0 → 200.0

**Arquivo**: `config/settings.py:75`

**Antes (V12.5)**: trailing_offset_pts=7.0 — offset_price=7.0, SL fica 7pts do preço. Broker min stop distance=200pts → 10016 Invalid stops.

**Depois (V12.6)**: trailing_offset_pts=200.0 — offset_price=200.0, SL fica 200pts do preço (≥broker min).

**Por quê**: WINM26 broker exige SL ≥200pts do preço atual. Offset=7pts fazia SL cair dentro dessa zona proibida. 5143 rejeições em May 14. 200pts = R$40.00 (WINM26 R$0.20/point). Trailing agora respeita a constraint do broker.

**Impacto**: offset=200pts (R$40) é muito largo para micro-scalper. Trailing só protege ganhos >R$40 acima do entry. Para trades que atingem +5pts activation (R$1.00), o SL fica 200pts atrás — na prática trailing nunca aperta SL até preço subir >200pts acima do entry. Ver alternativa "trailing virtual" nos Next Steps.

### 2. Deactivation gate — `_trailing_activated` reset quando profit < activation

**Arquivo**: `core/position_manager.py:183-185 (BUY), 213-215 (SELL)`

**Antes (V12.5)**: `_trailing_activated` só virava True, nunca voltava a False. Se profit atingia +5pts (activation), flag=True. Depois se preço revertia e profit caía para -15pts, flag continuava True → trailing tentava mover SL em prejuízo → 10016 Invalid stops (SL 200pts atrás de um preço que está abaixo do entry).

**Depois (V12.6)**: No bloco `else` (already activated), BUY: `if profit_pts < activation_pts: self._trailing_activated = False; return False`. SELL: mesma lógica. Quando profit cai abaixo de activation_pts, trailing é desativado. Na próxima vez que profit atingir activation, trailing reativa.

**Por quê**: Flag permanente causava tentativas de SL modify em prejuízo. Com offset=200pts, em BUY: `new_sl = bid - 200`. Se bid < entry, SL fica abaixo do entry (pior que o SL original). Deactivation gate impede isso — trailing só tenta mover SL quando posição está realmente em lucro ≥ activation_pts.

### 3. min_stop_distance validation no trailing

**Arquivo**: `core/position_manager.py:34,42-43,163,174-175,187-188,204-205,217-218`

**Antes (V12.5)**: `new_sl` calculado como `bid - offset_price` (BUY) ou `ask + offset_price` (SELL), sem verificar se distância ao bid/ask ≥ broker min_stop_distance. Se offset_price < min_dist, SL seria rejeitado.

**Depois (V12.6)**:
- `self._min_stop_distance: float = 0.0` field no `__init__`
- `set_min_stop_distance(distance: float)` method
- Em check_trailing_stop, BUY: `if min_dist > 0 and bid - new_sl < min_dist: new_sl = bid - min_dist`
- SELL: `if min_dist > 0 and new_sl - ask < min_dist: new_sl = ask + min_dist`
- Validação aplicada tanto no activation block quanto no already-activated block
- `main.py:111` chama `position_manager.set_min_stop_distance(min_stop_dist)` após calcular do broker

**Por quê**: Double-safety contra 10016. Mesmo que offset_price < min_dist (ex: se alguém configurar offset=100 com min_dist=200), new_sl é ajustado para respeitar broker constraint. Previne rejeições em qualquer configuração de offset.

### 4. Resíduo L205-206 removido

**Arquivo**: `core/position_manager.py` (linhas removidas)

**Antes (V12.5)**: Bloco SELL ainda tinha `return True / return False` residual do código antigo, que causava early return antes do bloco `else` (already activated) ser alcançado.

**Depois (V12.6)**: Resíduo removido. Fluxo SELL agora cai corretamente para o bloco `else` quando `_trailing_activated=True`, executando `new_sl = ask + offset_price` com min_dist validation.

---



### Diagnóstico V12.4

V12.4 reverteu loss_min_pts para 25pts mas ZERO trailing activations persistiu em May 14. Investigação de logs com debug logging revelou bug CRITICAL: MT5 reporta `Point=1.0` para WINM26 (índice brasileiro, Digits=0), não `Point=0.01` como o código assumia. Com `100 * self._point = 100 * 1.0 = 100` como divisor, `profit_pts = price_diff / 100` era 100x menor que o correto. Exemplo concreto: BUY trade 181170→181385 (+215 price units, +R$43.00 PnL) → profit_pts=2.15, nunca atingindo activation=3.0. V12.2 "funcionava" possivelmente com versão anterior do código ou point value diferente.

### 1. BUG FIX: `100 * self._point` → `self._point` (3 ocorrências)

**Arquivo**: `core/position_manager.py:158,161,183`

**Antes (V11-V12.4)**: `offset_price = trailing_offset_pts * 100 * self._point`, `profit_pts = (bid - entry) / (100 * self._point)`, `profit_pts = (entry - ask) / (100 * self._point)`

**Depois (V12.5)**: `offset_price = trailing_offset_pts * self._point`, `profit_pts = (bid - entry) / self._point`, `profit_pts = (entry - ask) / self._point`

**Por quê**: WINM26 tem `Point=1.0, Digits=0`. O código assumia point=0.01 (padrão forex onde 1pt=100ticks). Para WINM26, 1 point = 1 tick = 1 unidade de preço. Divisor `100 * 1.0 = 100` reduzia profit_pts em 100x. Com `self._point` diretamente, profit_pts reflete a realidade: +215 price units = 215.0 pts, não 2.15 pts.

### 2. trailing_activation_pts: 3.0 → 5.0

**Arquivo**: `config/settings.py:74`

**Antes (V12)**: trailing_activation_pts=3.0 — com point=1.0, 3pts = R$0.60 PnL (0.6 preço × R$0.20/point). Ruído puro.

**Depois (V12.5)**: trailing_activation_pts=5.0 — 5pts = R$1.00 PnL. Mais significativo, evita trailing em micro moves.

**Por quê**: Com o bug fix, profit_pts agora é correto (centenas em vez de unidades). 5pts de lucro real ainda é conservador (R$1.00) mas acima do ruído. Pode aumentar depois se trailing ativar demais em trades marginais.

### 3. trailing_offset_pts: 2.0 → 7.0

**Arquivo**: `config/settings.py:75`

**Antes (V11-V12.4)**: trailing_offset_pts=2.0 — com point=1.0, 2pts offset = 2 unidades de preço. Spread=5 unidades. Offset DENTRO do spread.

**Depois (V12.5)**: trailing_offset_pts=7.0 — 7pts offset = 7 unidades de preço. Acima do spread=5.

**Por quê**: Com point=1.0, 2pts offset ficava dentro do spread de 5pts — SL seria triggered imediatamente por pullback normal ou spread widening. 7pts offset dá margem acima do spread, permitindo que preço respire sem triggered prematuro. Broker min stop distance=200pts é respeitado (SL enviado ao broker sempre ≥200pts do preço).

### 4. Debug logging em check_trailing_stop

**Arquivo**: `core/position_manager.py:162-164,184-186`

INFO logs a cada 10s mostrando: entry, bid/ask, profit_pts, activated, point value, activation threshold. `_last_trailing_log_time` adicionado ao `__init__` e `_reset_state`.

**Por quê**: Sem visibilidade do cálculo interno, trailing "não funcionava" silenciosamente. Debug logs revelaram o bug de point=1.0 vs 0.01.

---

## MUDANÇAS REALIZADAS (V12.4) — LOSS_MIN FIX (TRAILING RECOVERY)

### Diagnóstico V12.3

V12.3 reduziu loss_min de 30→15pts para acelerar cycle time, mas dados de May 14 mostraram resultado desastroso: 71% dos exits saem no adverse mínimo (15.0pts), ZERO trailing activations em toda a sessão, WR colapsou para 24% (vs 44.2% em V12.2 com loss_min=30). Em V12.2 (May 13), havia 1242 "Trailing SL modificado" — trailing funcionava. Com loss_min=15, trades não têm chance de recuperação: adverse atinge 15pts antes que preço possa atingir +3pts para ativar trailing. Saída prematura em loss destrói WR e elimina trailing como saída de gain.

### 1. loss_min_pts: 15→25

**Arquivo**: `config/settings.py:80`

**Antes (V12.3)**: loss_min_pts=15.0 — 71% dos exits saem no mínimo. Zero trailing activations.

**Depois (V12.4)**: loss_min_pts=25.0 — saída por estratégia requer 25pts adverse.

**Por quê**: 15pts é pouco demais — preço move 15pts contra antes de qualquer recuperação ser possível. Com trailing activation=3pts, trade precisa atingir +3pts lucro ANTES de adverse atingir 25pts. 25pts é compromisso entre 30 (funcionava mas lento) e 15 (muito rápido, mata trailing). 25pts dá ~8-15s para trade desenvolver lucro em movimento normal.

### 2. reversal_min_disp: 15→25 (consistência)

**Arquivo**: `config/settings.py:82`

**Antes (V12.3)**: reversal_min_disp=15.0

**Depois (V12.4)**: reversal_min_disp=25.0 — alinhado com loss_min_pts=25.0.

**Por quê**: Reversal gate usa `loss_min_pts` no código, não `reversal_min_disp`. Manter ambos alinhados evita confusão. Com 25pts adverse, reversal só acontece quando loss é real e momentum adverso é forte (vel×1.5).

---

## MUDANÇAS REALIZADAS (V12.3) — BOTTLENECK REMOVAL (FREQUENCY UNLOCK)

### Diagnóstico V12.2

V12.2 relaxou filtros de entry mas frequency ainda <3 trades/min. Análise de bottlenecks acumulativos revelou que cooldowns/gates se acumulam sequencialmente após close, criando cycle time de 13-16s. Mesmo com entries mais fáceis, cada trade ocupa posição por 10s mínimo (min_hold) e após close há 3s+ de cooldowns. Loss exit requer 30pts adverse = 20-40s de espera. Reversal exige vel×3.0 = quase impossível.

### 1. min_hold_seconds: 10→5

**Arquivo**: `config/settings.py:78`

**Antes (V12.2)**: min_hold_seconds=10.0 — cada trade ocupa posição por mínimo 10s. Dominant bottleneck.

**Depois (V12.3)**: min_hold_seconds=5.0 — trade pode sair após 5s se condições de saída forem atingidas.

**Por quê**: min_hold=10s é o #1 bottleneck. Cada trade prende posição por 10s incondicionalmente. Com trailing activation=3pts, muitos trades atingem trailing em <5s. Hold de 5s ainda protege contra noise mas permite exits significativamente mais rápidos. Full cycle potencial: entry(0s) → hold 5s → exit → re-entry ~1-2s = 6-7s cycle vs 13-16s anterior.

### 2. post_close_cooldown_s: 3.0→1.0

**Arquivo**: `config/settings.py:79`

**Antes (V12.2)**: post_close_cooldown_s=3.0 — 3s same-dir penalty após close.

**Depois (V12.3)**: post_close_cooldown_s=1.0 — 1s same-dir penalty após close.

**Por quê**: 3s era excessivo. Quick flips (opposite dir) já são filtrados pelo cooldown_after_loss e reversal gate. Post-close só bloqueia same-dir re-entry — 1s é suficiente para evitar echo trades sem matar frequency em trends sustentados.

### 3. reversal_vel_mult: 3.0→1.5

**Arquivo**: `config/settings.py:83`

**Antes (V12.2)**: reversal_vel_mult=3.0 — reversão precisava vel_fast ≥ 3× adaptive_threshold (12-30 em regime low). Quase impossível.

**Depois (V12.3)**: reversal_vel_mult=1.5 — reversão precisa vel_fast ≥ 1.5× adaptive_threshold (6-15 em regime low). Exequível com momentum moderado.

**Por quê**: Vel×3.0 eliminava praticamente todas reversões. Com loss_min=15pts (abaixo), reversões acontecem mais cedo com menos adverse. Vel×1.5 ainda exige momentum real (50% acima do threshold normal) mas é atingível em condições normais de mercado.

### 4. loss_min_pts: 30→15

**Arquivo**: `config/settings.py:80`

**Antes (V12.2)**: loss_min_pts=30.0 — saída por estratégia requer 30pts adverse. Em moves lentos, trade preso 20-40s.

**Depois (V12.3)**: loss_min_pts=15.0 — saída por estratégia requer 15pts adverse. Loss_max=60pts inalterado.

**Por quê**: 30pts adverse em WINM26 é muito — preço precisa mover 15k ticks contra. Com 15pts, saída loss acontece ~2× mais rápido. Trailing activation=3pts significa que trades lucrativos de +3pts já têm trailing proteção — loss de 15pts só acontece quando trade nunca atingiu +3pts ou trailing foi triggered e preço reverteu 12pts+ (3+15=18pts round trip). loss_max=60pts continua como safetynet + SL broker.

### 5. cooldown_after_loss_ms: 3000→1500

**Arquivo**: `config/settings.py:58`

**Antes (V12.2)**: cooldown_after_loss_ms=3000 — 3s sem trade após loss.

**Depois (V12.3)**: cooldown_after_loss_ms=1500 — 1.5s sem trade após loss.

**Por quê**: 3s acumulava com outros cooldowns (post_close=3s + hft_cooldown=200ms + risk_block=500ms + dedup=100ms = 6.7s total). Com 1.5s + post_close=1s = máximo ~3.3s de cooldown combinado após loss. Ainda evita o pior padrão (LOSS+flip=37.8% WR) mas permite re-entry mais rápido.

### 6. reversal_min_disp: 30→15 (consistência)

**Arquivo**: `config/settings.py:82`

**Antes (V12.2)**: reversal_min_disp=30.0 (não usado diretamente no código — reversal usa loss_min_pts).

**Depois (V12.3)**: reversal_min_disp=15.0 — alinhado com loss_min_pts=15.0.

**Por quê**: Consistência. O reversal gate no código usa `loss_min_pts`, não `reversal_min_disp`. Mas manter ambos alinhados evita confusão futura.

### Cumulative bottleneck timeline (V12.3 vs V12.2)

**V12.2 worst case after LOSS**: post_close(3.0s) + cooldown_after_loss(3.0s) + hft_cooldown(0.2s) + dedup(0.1s) + risk_block(0.5s) + min_hold(10.0s) + loss_min(30pts/20-40s) = **13-16s+ per cycle**

**V12.3 worst case after LOSS**: post_close(1.0s) + cooldown_after_loss(1.5s) + hft_cooldown(0.2s) + dedup(0.1s) + risk_block(0.5s) + min_hold(5.0s) + loss_min(15pts/10-20s) = **3-5s typical cycle**

---

## MUDANÇAS REALIZADAS (V12.2) — FREQUENCY RECOVERY + BALANCED FILTERS

### Diagnóstico V12.1

V12.1 overcorrigiu: filtros muito rigorosos mataram frequency. O bot quase não entrava. Causas:
1. **adaptive_threshold_low=5.0**: 64% dos ticks usam este threshold; vel_fast precisava >5.0 em regime low — raro
2. **hft_min_displacement_pts=5.0**: Exige 5pts de displacement — cortou entries com disp 3-5pt (39% WR, aceitável)
3. **hft_max_spread_ticks=3**: Spread=4 (comum) bloqueado — reduziu pool de ticks drasticamente
4. **hft_acceleration_gate=True**: Cortava entries quando acc<0 (BUY) mesmo em moves fortes com pullback momentâneo
5. **cooldown_after_loss_ms=5000**: 5s sem trade após loss — em sequência de losses, gaps enormes
6. **hft_min_micro_range=3.0**: Muitos mercados com range 2-3pts bloqueados

### 1. adaptive_thresholds: 5/8/12 → 4/6/10

**Arquivo**: `config/settings.py:119-121`

**Antes (V12.1)**: adaptive_threshold_low=5.0, mid=8.0, high=12.0

**Depois (V12.2)**: adaptive_threshold_low=4.0, mid=6.0, high=10.0

**Por quê**: Threshold 5.0 em regime low (64% dos ticks) era agressivo demais. 4.0 exige momentum real mas não tão extremo. Progressão 4→6→10 mantém filtragem por regime.

### 2. hft_min_displacement_pts: 5.0 → 3.0

**Arquivo**: `config/settings.py:50`

**Antes (V12.1)**: hft_min_displacement_pts=5.0

**Depois (V12.2)**: hft_min_displacement_pts=3.0

**Por quê**: Dados V11.1 mostram disp 3-5pt tem 39% WR — aceitável. Disp 1-3pt=3% WR continua filtrado. 3.0 é o sweet spot: corta garbage entries, mantém entries com direção clara.

### 3. hft_max_spread_ticks: 3 → 4

**Arquivo**: `config/settings.py:46`

**Antes (V12.1)**: hft_max_spread_ticks=3

**Depois (V12.2)**: hft_max_spread_ticks=4

**Por quê**: Spread=4 ainda é tight. Com max=3, muitos ticks eram bloqueados. Spread=5 continua bloqueado (risk engine max_spread_ticks=5).

### 4. hft_min_micro_range: 3.0 → 2.0

**Arquivo**: `config/settings.py:45`

**Antes (V12.1)**: hft_min_micro_range=3.0

**Depois (V12.2)**: hft_min_micro_range=2.0

**Por quê**: Mercado com range 2pts ainda tem direção. 3.0 era muito restritivo para mercados com volatilidade moderada.

### 5. hft_acceleration_gate: True → False

**Arquivo**: `config/settings.py:51`

**Antes (V12.1)**: hft_acceleration_gate=True — bloqueava entry quando acc<0 (BUY) ou acc>0 (SELL)

**Depois (V12.2)**: hft_acceleration_gate=False — gate desativado

**Por quê**: Acceleration = vel_very_fast(200ms) - vel_fast(500ms). Um pullback momentâneo de 200ms faz acc<0 mesmo em move forte de 500ms. O gate cortava entries em momentos de pullback natural dentro de trends. Velocity_fast (500ms) + displacement são filtros suficientes para direção. Acc continua como booster no strength.

### 6. cooldown_after_loss_ms: 5000 → 3000

**Arquivo**: `config/settings.py:58`

**Antes (V12.1)**: cooldown_after_loss_ms=5000 — 5s sem trade após loss

**Depois (V12.2)**: cooldown_after_loss_ms=3000 — 3s sem trade após loss

**Por quê**: 5s matava frequency em sequências de losses. 3s ainda evita o pior padrão (LOSS+flip=37.8% WR) mas permite re-entry mais rápido quando momentum continua favorável.

### 7. fallback_min_velocity: 3.0 → 4.0

**Arquivo**: `config/settings.py:115`

**Antes (V12.1)**: fallback_min_velocity=3.0

**Depois (V12.2)**: fallback_min_velocity=4.0

**Por quê**: Alinhado com novo adaptive_threshold_low=4.0. Fallback é para idle entries — exige vel≥4.0 consistente com regime low.

---

## MUDANÇAS REALIZADAS (V12.1) — STRICTER ENTRY FILTERS BASEADO EM DADOS V11.1

### 1. hft_min_velocity: 3.0 → 5.0

**Arquivo**: `config/settings.py:44`

**Antes (V12)**: hft_min_velocity=3.0 — filtra quase nada (98% dos ticks passam).

**Depois (V12.1)**: hft_min_velocity=5.0 — filtra ~2% dos ticks, exige momentum mínimo real.

**Por quê**: Entry vel_fast 5-10=2%WR, 10-15=52%WR, 20+=44%WR. Velocity <5 quase não gera wins. Filtro em 5.0 corta os piores entries sem impactar volume significativamente.

### 2. hft_min_displacement_pts: 1.0 → 5.0

**Arquivo**: `config/settings.py:50`

**Antes (V12)**: hft_min_displacement_pts=1.0 — filtra quase nada. Entry displacement 1-3pt=3%WR.

**Depois (V12.1)**: hft_min_displacement_pts=5.0 — exige displacement mínimo de 5pts na direção do sinal.

**Por quê**: Displacement 1-3pt tem 3% WR, 5-10pt tem 39% WR, 10+pt tem 58% WR. min_disp=1.0 deixava passar sinais sem direção clara. 5.0 exige movimento real antes de entrar.

### 3. hft_min_micro_range: 1.0 → 3.0

**Arquivo**: `config/settings.py:45`

**Antes (V12)**: hft_min_micro_range=1.0 — micro_range mínimo quase zero.

**Depois (V12.1)**: hft_min_micro_range=3.0 — exige range mínimo de 3pts.

**Por quê**: Mercado flat/choppy = zero direção. Micro_range <3 indica mercado sem volatilidade suficiente. Evita entrar em dead markets.

### 4. adaptive_threshold_low: 3.0 → 5.0

**Arquivo**: `config/settings.py:119`

**Antes (V12)**: adaptive_threshold_low=3.0 — 64% dos ticks usam este threshold, muito baixo.

**Depois (V12.1)**: adaptive_threshold_low=5.0 — threshold mínimo mais alto para velocity.

**Por quê**: avg_velocity <3=30% dos ticks, 3-6=34%. 64% dos signal checks usam threshold_low=3.0 — muito permissivo. Aumentar para 5.0 exige mais momentum para gerar sinal.

### 5. adaptive_threshold_mid: 5.0 → 8.0

**Arquivo**: `config/settings.py:120`

**Antes (V12)**: adaptive_threshold_mid=5.0

**Depois (V12.1)**: adaptive_threshold_mid=8.0

**Por quê**: Consistente com o aumento de low. Thresholds em sequência 5→8→12 mantêm progressão proporcional.

### 6. adaptive_threshold_high: 8.0 → 12.0

**Arquivo**: `config/settings.py:121`

**Antes (V12)**: adaptive_threshold_high=8.0

**Depois (V12.1)**: adaptive_threshold_high=12.0

**Por quê**: Completa a progressão 5→8→12. Em alta volatilidade (vel >15), exige velocity ≥12 para gerar sinal — filtra noise em mercados rápidos.

### 7. cooldown_after_loss_ms: 2000 → 5000

**Arquivo**: `config/settings.py:58`

**Antes (V12)**: cooldown_after_loss_ms=2000 — 2s após loss.

**Depois (V12.1)**: cooldown_after_loss_ms=5000 — 5s após loss.

**Por quê**: LOSS+flip é o pior padrão sequencial (37.8% WR). LOSS+same=50.5% WR (melhor). Após loss, momentum provavelmente continua adverso. 5s dá mais tempo para o mercado estabilizar antes de re-entrar.

### 8. hft_max_spread_ticks: 5 → 3

**Arquivo**: `config/settings.py:46`

**Antes (V12)**: hft_max_spread_ticks=5 — permite spread até 5 ticks.

**Depois (V12.1)**: hft_max_spread_ticks=3 — só entra com spread ≤3 ticks.

**Por quê**: Spread=5 é dominante (96% dos signal checks). Mas spread alto = slippage + custo. Com max=3, filtra momentos de baixa liquidez onde spread widen. Reduz custo por trade.

---

## MUDANÇAS REALIZADAS (V12) — REDUZIR EXITS PREMATUROS + TRAILING ATIVAÇÃO MAIS CEDO

### 1. Trailing activation: 5pts → 3pts

**Arquivo**: `config/settings.py:74`

**Antes (V11)**: trailing_activation_pts=5.0 — trailing só ativava após posição ter +5pts de lucro.

**Depois (V12)**: trailing_activation_pts=3.0 — trailing ativa após +3pts de lucro.

**Por quê**: 39% dos trades nunca chegavam a +5pts. Dados V11.1 mostram que trades COM trailing têm 58.9% WR vs 9.3% sem trailing. Reduzir para 3pts significa mais trades ativam trailing, capturando gains menores mas consistentes.

### 2. min_hold_seconds: 5s → 10s + gate no reversal path

**Arquivo**: `config/settings.py:78`, `strategies/momentum_burst.py:108-110`

**Antes (V11)**: min_hold_seconds=5.0, só bloqueava loss_exit em _check_exit.

**Depois (V12)**: min_hold_seconds=10.0, bloqueia TANTO loss_exit quanto reversal em _evaluate_with_position.

**Por quê**: Reversals estavam fechando posições antes dos 5s (min_hold só bloqueava _check_exit). Com 10s, posição tem mais tempo para desenvolver lucro antes de qualquer saída por estratégia.

### 3. Post-close cooldown: 1s → 3s

**Arquivo**: `config/settings.py:79`

**Antes (V11)**: post_close_cooldown_s=1.0 — 52% das re-entradas aconteciam em <1s após close, incluindo 147 quick flips (direção oposta).

**Depois (V12)**: post_close_cooldown_s=3.0 — previne re-entradas impulsivas e quick flips.

**Por quê**: Quick flips eram a maior fonte de perdas. Após close, momentum está em transição. 3s dá tempo para o mercado definir direção antes de re-entrar.

### 4. Reversal velocity multiplier: ×2.0 → ×3.0

**Arquivo**: `config/settings.py:83`

**Antes (V11)**: reversal_vel_mult=2.0 — reversão precisava vel_fast ≥ 2× adaptive_threshold.

**Depois (V12)**: reversal_vel_mult=3.0 — reversão precisa vel_fast ≥ 3× adaptive_threshold.

**Por quê**: 51 reversões passaram o gate V11 e geraram closes prematuros. Com ×3.0, só reversões com momentum extremo passam. Mais posições ficam abertas e atingem trailing.

### 5. HFT cooldown: 100ms → 200ms

**Arquivo**: `config/settings.py:48`

**Antes (V11)**: hft_cooldown_ms=100 — sinais gerados a cada 100ms.

**Depois (V12)**: hft_cooldown_ms=200 — sinais gerados a cada 200ms.

**Por quê**: Reduz signal noise. 100ms gerava sinais duplicados no mesmo micro movement. 200ms filtra micro flutuações.

---

## MUDANÇAS REALIZADAS (V11) — TRAILING STOP +5PTS/2PTS + SEM TP FIXO + LOSS BOUNDED 30-60PTS

### 1. Trailing stop como única saída de gain — activation +5pts, offset 2pts

**Arquivo**: `core/position_manager.py:145-196`, `config/settings.py:72-74`

**Antes (V9)**: trailing_stop_ticks=150 (15pts distância fixa do preço), sem activation gate. Trailing movia SL toda vez que preço melhorava, sem exigir lucro mínimo.

**Depois (V11)**: 
- `trailing_activation_pts=5.0` — trailing só ativa após posição ter +5pts de lucro real
- `trailing_offset_pts=2.0` — SL fica 2pts atrás do preço após activation
- `_trailing_activated` state — booleano que vira True quando profit_pts >= activation_pts
- `trailing_attempt_cooldown_s=0.3` — 300ms entre tentativas de modify

**Por quê**: TP fixo corta winners. Com trailing stop: posição corre enquanto preço favorável, SL aperta 2pts atrás. Activation de +5pts garante que só trailing quando realmente em lucro. Offset 2pts é tight o suficiente para capturar a maioria do move, mas largo o suficiente para não ser triggered por pullback normal.

### 2. Sem take profit fixo — hft_take_profit_ticks=0

**Arquivo**: `config/settings.py:23`, `strategies/momentum_burst.py:345,349`, `core/execution_engine.py:240,250`

**Antes (V9)**: hft_take_profit_ticks=200 (TP broker em 200 ticks = 20pts), _create_hft_signal calculava TP em toda entrada.

**Depois (V11)**: 
- `hft_take_profit_ticks=0` — sem TP no broker
- `_create_hft_signal`: quando tp_ticks=0, tp=0.0 (não calcula TP)
- `_validate_stops`: pula validação de TP quando tp=0 (não força min_dist em TP zero)

**Por quê**: TP fixo limita ganhos. O trailing stop é a única saída de gain — deixa lucro correr. TP=0 no broker significa que posição só é fechada por gain via trailing stop ou por loss via SL/estratégia.

### 3. Loss bounded 30-60pts — loss_min_pts=30, loss_max_pts=60

**Arquivo**: `config/settings.py:78-79`, `strategies/momentum_burst.py:146-167`

**Antes (V9)**: exit_min_sl_pct=0.5 (50% do SL=200 → 100 ticks = 10pts mínimo para exit). SL broker=200 ticks (20pts).

**Depois (V11)**:
- `loss_min_pts=30.0` — saída por estratégia quando displacement adverso >= 30pts
- `loss_max_pts=60.0` — se adverse > 60pts, loga `loss_max` mas ainda gera CLOSE
- `_check_exit` simplificado: só loss_exit (gain_exit removido completamente)
- `hft_stop_loss_ticks=6000` — SL broker = 60pts safetynet (6000 ticks × 0.01 = 60.00 preço)

**Por quê**: V9 tinha exit em 50% de SL=200 ticks (10pts). Muito cedo — saía em noise. Com loss_min=30pts, só sai quando displacement adverso é inequívoco (30+ pontos contra). Loss_max=60pts é o limite superior — além disso o SL broker protege. Range 30-60pts = janela de saída por estratégia, SL broker=60pts = proteção final.

### 4. _check_exit reescrito — só loss_exit

**Arquivo**: `strategies/momentum_burst.py:146-167`

**Antes (V9)**: `_check_exit` com direction_reversal (|disp|>=20 + exit_min_sl_pct), displacement_flip, quick_profit, gain_exit favorável.

**Depois (V11)**: `_check_exit` simplificado para apenas loss_exit:
- Calcula `adverse` (displacement adverso baseado em position_side)
- Se `adverse >= loss_min_pts (30pts)` → CLOSE com reason="loss_exit"
- Se `adverse > loss_max_pts (60pts)` → loga `[EXIT] reason=loss_max`
- Senão loga `[EXIT] reason=loss_range`
- Todas saídas de gain removidas (direction_reversal, displacement_flip, quick_profit, gain_exit favorável)

**Por quê**: Gain exits (direction_reversal, displacement_flip, quick_profit) cortavam winners cedo e geravam whipsaw. Com trailing stop como única saída de gain, o preço corre livremente. Loss exit em adverse >= 30pts corta losers antes do SL broker (60pts).

### 5. Reversal gate usa loss_min_pts (30pts)

**Arquivo**: `strategies/momentum_burst.py:118-119,133-134`

**Antes (V9)**: reversal gate exigia `|disp| >= reversal_min_disp (20pts)`

**Depois (V11)**: reversal gate exige `|disp| >= loss_min_pts (30pts)`. `reversal_min_disp=30.0` em settings.

**Por quê**: Reversal sem perda suficiente é whipsaw. Com 30pts adverse, a posição já está em prejuízo real — reversal faz sentido porque momentum adverso é forte. Abaixo de 30pts, não há evidência suficiente de reversão sustentada.

### 6. PositionManager.check_trailing_stop corrigido — cálculo de profit em pontos

**Arquivo**: `core/position_manager.py:145-196`

**Correções** (V11, corrigido novamente em V12.5):
- `profit_pts = (bid - entry) / self._point` — BUY: diferença de preço → pontos (WINM26 Point=1.0)
- `profit_pts = (entry - ask) / self._point` — SELL: mesmo cálculo
- `offset_price = trailing_offset_pts * self._point` — 200pts offset = 200.0 preço (V12.6)
- Logs em pontos corretamente (profit_pts, offset_pts)

**Por quê**: V11 assumia point=0.01 (1pt=100ticks), usando `100 * self._point` como divisor. WINM26 tem Point=1.0, Digits=0. V12.5 removeu o `100 *` em 3 locais. Profit_pts agora é em unidades de preço reais (ex: 215.0 pts em vez de 2.15 pts). V12.6 aumentou offset para 200pts (broker min stop distance).

### 7. _modify_sl envia tp=self._take_profit (0.0)

**Arquivo**: `core/position_manager.py:209`

Quando _modify_sl modifica o SL do trailing stop, envia tp=0.0 (sem TP) no request. Broker aceita tp=0 sem problema — significa "manter TP atual" (que também é 0).

---

## MUDANÇAS REALIZADAS (V10) — EXIT BOUNDED GAIN/LOSS + REMOVED DIRECTION_REVERSAL/DISPLACEMENT_FLIP/QUICK_PROFIT

### 1. Removed direction_reversal exit

**Arquivo**: `strategies/momentum_burst.py`

**Antes**: direction_reversal gerava CLOSE quando displacement adverso >= threshold. Era a saída mais usada em V7-V9.

**Depois**: Removido completamente. A única saída de gain é o trailing stop. A única saída de loss é _check_exit com loss_min_pts.

### 2. Removed displacement_flip exit

**Arquivo**: `strategies/momentum_burst.py`

**Antes**: displacement_flip gerava CLOSE quando displacement mudava de +N para -N (flip completo). Gerava muitos exits em noise.

**Depois**: Removido. Trailing stop cuida de saída de gain. Loss_exit cuida de saída de loss.

### 3. Removed quick_profit exit

**Arquivo**: `strategies/momentum_burst.py`

**Antes**: quick_profit gerava CLOSE quando displacement favorável >= 25 após 5s. Cortava winners.

**Depois**: Removido. Trailing stop deixa winners correrem sem limite de tempo ou lucro.

---

## DADOS DE PRODUÇÃO

### V12.7 (2026-05-15, 18.5min): 155 trades

| Métrica | Valor | Target |
|---|---|---|
| Winrate | 38.1% | 60% |
| PnL acumulado | -88 pts | Positivo |
| Avg win | +6.49 pts | |
| Avg loss | -5.23 pts | |
| Trades/min | 8.39 | 5.0 |
| Hold≤3.5s WR | **0%** (27 trades, -112pts) | |
| Hold≥5s WR | **44.6%** (65 trades, +48pts) | |

### V12.7 (2026-05-15, post-restart 11:42+): 59 trades

| Métrica | Valor | Target |
|---|---|---|
| Winrate | 30.5% | 60% |
| PnL acumulado | -19 pts | Positivo |
| Avg win | +6.5 pts | |
| Avg loss | -3.89 pts | |
| Trades/min | 8.19 | 5.0 |

### V7 (2026-05-13, 09:12-10:28): 1173 trades totais

| Métrica | Valor | Target |
|---|---|---|
| Winrate | 37.8% (443W/602L/128BE) | 60% |
| PnL acumulado | -407 pts | Positivo |
| Avg win | +4.16 pts | |
| Avg loss | -3.74 pts | |
| Últimos 50 trades WR | 22% (11W/28L/11BE) | |
| Avg hold | 1.4s | >5s |
| Avg latency | 134.3ms | |
| avg_slippage | 4.0 ticks | |
| #1 PnL value | -2.00 (131x) | |
| #2 PnL value | 0.00 (128x) | |
| #3 PnL value | -1.00 (127x) | |

### V11.1 (2026-05-12 a 13, 27.4h): 1340 trades totais

| Métrica | Valor | Target |
|---|---|---|
| Winrate | 39.6% (531W/674L/135BE) | 60% |
| PnL acumulado | +7 pts | Positivo |
| Avg win | +5.95 pts | |
| Avg loss | -4.26 pts | |
| Trades/min | 0.80 | 5.0 |
| Trades com trailing | 823 (61%) | |
| WR com trailing | **58.9%** | 60% |
| WR sem trailing | 9.3% | |
| Avg hold | 11.9s | |
| Post-close re-entry <1s | 52% | |

### Diagnóstico V11.1 → V12

**Raiz do 39.6% WR**: 39% dos trades nunca chegam a +5pts lucro → trailing nunca ativa → fechados por reversais rápidas com tiny losses (-1 a -7pts).

1. **Trailing activation alto demais (+5pts)**: Muitos trades ficam em +3/+4pts, são revertidos antes de ativar trailing. Solução: activation=3pts
2. **min_hold_seconds=5s não protege contra reversais**: Reversal em _evaluate_with_position não verificava hold time. Solução: min_hold=10s + gate no reversal path
3. **Post-close cooldown curto (1s)**: 52% re-entram em <1s, 147 quick flips (direção oposta). Solução: cooldown=3s
4. **Reversal fácil (vel×2.0)**: 51 reversais passaram o gate. Solução: vel×3.0

### V12.2 (2026-05-13, 7.6h, 597 trades)

| Métrica | Valor | Target |
|---|---|---|
| Winrate | 44.2% | 60% |
| PnL acumulado | +766 pts | Positivo |
| Avg win | +9.62 pts | |
| Avg loss | -6.23 pts | |
| Trades/min | 1.31 | 5.0 |
| Trailing activations | 1242 | |
| Avg hold | ~12s | |

### V12.3 (2026-05-14, full day até ~12:45, 146 trades)

| Métrica | Valor | Target |
|---|---|---|
| Winrate | 24% | 60% |
| PnL acumulado | -276 pts | Positivo |
| Avg win | +6.8 pts | |
| Avg loss | -5.19 pts | |
| Trades/min | ~1.5 | 5.0 |
| Trailing activations | **0** | |
| Exits no adverse=15.0 (mínimo) | **71%** | |
| Reversals | **0** | |

### Diagnóstico V12.3 → V12.4

**Raiz do 24% WR**: loss_min_pts=15 matou trailing. Trades saem no mínimo adverse antes de atingir +3pts para ativar trailing. Zero trailing = zero saída de gain por estratégia = só losses.

1. **loss_min_pts=15 muito baixo**: 71% dos exits saem no adverse mínimo. Trailing activation=3pts requer profit ≥3pts ANTES de adverse atingir 15pts — quase impossível em move adverso. Solução: loss_min=25pts
2. **Zero trailing activations**: Com loss_min=30 (V12.2), havia 1242 trailing mods. Com 15, zero. Solução: 25pts dá ~8-15s para trade desenvolver lucro
3. **Zero reversals**: vel×1.5 + disp≥15 é atingível mas só após loss_min ser atingido primeiro. Solução: disp≥25 alinhado com loss_min=25

### V6 (2026-05-13, 09:12-09:30): 36 trades

| Métrica | Valor | Target |
|---|---|---|
| Winrate | 47.2% (17W/19L) | 60% |
| Trades/min | 2.1 | 5.0 |
| PnL acumulado | -22 pts | Positivo |
| Avg win | +3.59 pts | |
| Avg loss | -4.37 pts | |

### Diagnóstico V7 → V8 → V9 → V10 → V11

Evolução das saídas:
1. **V7**: direction_reversal disp±5, displacement_flip ±3, quick_profit 15/3s, trailing 80pts → WR 37.8%, exits prematuros
2. **V8**: direction_reversal ±20, displacement_flip ±10, quick_profit 25/5s, trailing 150pts → menos exits prematuros
3. **V9**: exit_min_sl_pct=0.5 (50% SL gate), thresholds em settings → ainda TP fixo limitando winners
4. **V10**: removido direction_reversal, displacement_flip, quick_profit → só trailing stop + loss_exit
5. **V11**: trailing stop com activation +5pts/offset 2pts, sem TP, loss 30-60pts, SL broker=60pts safetynet
6. **V11.1**: displacement gate (≥1.0pt) + acceleration gate → pouco impacto, WR ainda 39.6%
 7. **V12**: trailing activation 3pts, min_hold=10s bloqueia reversal, post-close=3s, reversal vel×3.0
 8. **V12.1**: filtros rigorosos demais (thresholds 5/8/12, disp≥5, spread≤3, acc_gate=ON, cooldown=5s) → matou frequency
 9. **V12.2**: frequency recovery — thresholds 4/6/10, disp≥3, spread≤4, acc_gate=OFF, cooldown=3s, micro_range=2
10. **V12.3**: bottleneck removal — min_hold 10→5s, loss_min 30→15pts, post_close 3→1s, reversal_vel×1.5, cooldown_after_loss 3→1.5s

---

## CONFIGURAÇÃO ATUAL (V12.9 DEFAULTS)

### Trading
- symbol=WINM26, lot=1.0, **hft_take_profit_ticks=0** (sem TP), **hft_stop_loss_ticks=4000** (40pts safetynet)
- magic=123456, deviation=20, filling_type=1

### Tick
- buffer_size=200, velocity_window_ms=1000, micro_range_window=30, min_ticks_for_signal=20

### Signal (HFT)
- **hft_min_velocity=6.0**, **hft_min_micro_range=2.0**, hft_max_spread_ticks=5
- hft_cooldown_ms=200, hft_reversal_factor=0.5, **hft_acceleration_gate=False**
- **Filtros de entrada**: velocity_fast ≥ threshold + disp mesma direção ≥4pts + micro_range ≥2.0 + spread ≤5 (acc gate OFF)
- **trend_bars**: booster (1.0 + min(trend_bars,5) * 0.1), não gate

### Risk
- max_daily_loss=500, max_consecutive_losses=8, **cooldown_after_loss_ms=1500**
- max_trades_per_minute=30, max_spread_ticks=5, max_latency_ms=500
- circuit_breaker_errors=3, circuit_breaker_cooldown_ms=60000
- risk_block_cooldown=500ms
- **NO permanent stop for excessive_consecutive_losses** (removed)

### Position
- max_open_positions=1, trade_timeout_ms=60000
- trailing_stop_enabled=true, **trailing_activation_pts=6.0**, **trailing_offset_pts=200.0** (broker SL, decorativo), **trailing_virtual_enabled=true**, **trailing_virtual_offset_pts=8.0**, **trailing_attempt_cooldown_s=0.3**
- allow_reversal=true, **min_hold_seconds=5.0**, **post_close_cooldown_s=0.3**
- **loss_min_pts=18.0**, **loss_max_pts=35.0**, **reversal_min_disp=9.0**, **reversal_vel_mult=1.2**, **reentry_min_displacement_pts=8.0**

### System
- tick_sleep_ms=5, heartbeat_interval_ms=30000, watchdog_tick_timeout_ms=10000
- status_report_interval_sec=30

### HFT
- enabled=true, idle_timeout_ms=3000, **fallback_min_velocity=6.0**
- **adaptive_velocity_low=4.0**, **adaptive_velocity_mid=12.0**
- **adaptive_threshold_low=5.0**, **adaptive_threshold_mid=7.0**, **adaptive_threshold_high=10.0**

### Strategy (MomentumBurst)
- signal_dedup_ms=100, risk_block_cooldown_s=0.5
- **min_hold_seconds=5.0** (loss_exit E reversal bloqueados nos primeiros 5s)
- **_check_exit**: só loss_exit — adverse >= 18pts → CLOSE, adverse > 35pts → CLOSE com log loss_max
- **Gain exit**: **virtual trailing stop** — activation +6pts, virtual offset 8pts (R$1.60 atrás), close via market order quando preço cruza; broker trailing offset=200pts decorativo (SL de segurança)
- **Reversal**: |vel_fast| ≥ adaptive_threshold × 1.2 AND |disp| ≥ 9pts AND hold >= 5s
- post-close cooldown: 0.3s
- trailing_attempt_cooldown: 0.3s (broker trailing, decorative)
- **Sem TP fixo** — hft_take_profit_ticks=0, tp=0.0 no signal e no broker
- **V12.9 entry filters**: min_vel=6.0, min_disp=4.0pts, min_micro_range=2.0, max_spread=5, adaptive_thresholds 5/7/10, **acceleration_gate=OFF**
- **V12.13 reentry gate**: same-side re-entry após loss requer |displacement| >= reentry_min_displacement_pts (8pts); flip entries usam hft_min_displacement_pts (4pts) normal; gate desativado se threshold=0

### Speed Filter (V12.13)
- **enabled=True**, speed_period=5, **speed_threshold=5.5**, strength_exhaustion=0.30, micro_range_window=30
- **Speed (pts/second)**: |price_span| / time_elapsed_s over speed_period ticks
- **Strength**: |price_span_pts| / directional_range_pts (high-low of micro_range_window, directional)
- **5 states**: LENTO (speed < threshold×0.5, BLOCKED), NEUTRO (speed ≥ threshold×0.5 + strength≥0.20 + accel>0 + consistency≥0.45, ALLOWED), ACELERANDO (speed ≥ threshold×0.65 + consistency>0.55, ALLOWED), FORTE (speed ≥ threshold + strength>0.45 + consistency>0.50 + accel>0, ALLOWED), EXAUSTAO (speed > threshold×1.3 + strength<0.30, BLOCKED)
- **Chop gate**: consistency < 0.45 AND speed < threshold×0.8 → LENTO (BLOCKED)
- **Adaptive threshold**: base×spread_mult×range_mult×vel_mult, smoothed 70/30 (EMA)
- **Diagnostic logs**: every 10s with state/speed/strength/allowed + aggregated stats
- **SpeedFilterStats**: rejection_rate, blocked_lento, blocked_exhaustao, allowed counts

---

## INVARIANTES — NÃO QUEBRAR

1. Single Position NETTING — 1 posição por símbolo
2. ExecutionEngine._lock protege order_send — obrigatório
3. symbol_info_tick() = única fonte de preço em hot path
4. PositionManager.sync_with_mt5() = única fonte de truth para posição
5. Point cache nunca zero em produção (division by zero)
6. Watchdog DEVE ser daemon thread
7. Tick logger NÃO vai para console (anti-spam)
8. Cooldown entre sinais obrigatório (signal_cooldown_ms)
9. RiskEngine.check_pre_trade() = gate final antes de order_send
10. NETTING reversal = BUY/SELL direto, nunca CLOSE+OPEN
11. Main loop = single-thread (exceção: Watchdog + ExecutionEngine worker)
12. SL em toda ordem (TP=0 é válido = sem TP). Minimum SL = 200pts do broker
13. velocity = SIGNED (nunca abs) — direção é fundamental
14. trend_bars = booster (não gate) — strength * (1.0 + min(trend_bars,5) * 0.1)
15. Hold mínimo 5s antes de QUALQUER saída por estratégia (loss_exit E reversal)
16. **Trailing stop é a ÚNICA saída de gain** — sem TP fixo, sem direction_reversal gain, sem quick_profit
17. **Loss bounded 18-35pts** — saída por estratégia quando adverse >= 18pts, SL broker=35pts safetynet
18. **Trailing activation gate** — trailing só ativa após +6pts lucro real (profit_pts >= activation_pts); deactivation gate: volta a False quando profit < activation_pts
19. **Virtual trailing offset 8pts (real)** + **Broker trailing offset 200pts (decorativo/safetynet)** — virtual SL rastreado internamente, close via market order quando preço cruza; broker SL ≥200pts atrás (nunca atingido em operação normal)
20. Reversal gate: |vel_fast| ≥ adaptive_threshold × 1.2 AND |disp| ≥ reversal_min_disp (9pts) AND hold >= min_hold_seconds (5s)
21. Post-close cooldown 0.3s — permite re-entrada rápida, previne echo trades
22. Idle fallback = mesmos filtros que HFT entry (sem trend_bars gate, acc/disp mesma direção) + reentry displacement gate
23. Settings defaults devem sempre corresponder ao STATE.md documentado
24. **Displacement está em pontos** (não ticks): `_calc_net_displacement` divide por `self._point`
25. **TP=0 no broker significa sem take profit**: `_validate_stops` pula TP quando tp=0
26. **Trailing offset_price = trailing_offset_pts × point**: WINM26 Point=1.0, offset 200pts = 200.0 preço (≥broker min=200pts)
27. **profit_pts = price_diff / point**: Conversão correta preço→pontos. WINM26 Point=1.0, 215 price units = 215.0 pts
28. **min_stop_distance validation no trailing**: new_sl ajustado se distância ao bid/ask < min_stop_distance. Previne 10016 Invalid stops
29. **Deactivation gate**: `_trailing_activated` volta a False quando profit_pts < activation_pts. Impede trailing em prejuízo
30. **SpeedFilter não deve matar frequência**: allow NEUTRO/ACELERANDO/FORTE, block apenas LENTO/EXAUSTAO. Rejection rate target: <20%
31. **TickEngine.get_recent_ticks()**: interface pública ao buffer — SpeedFilter NÃO acessa `_ticks` privado
32. **Reentry displacement gate**: same-side re-entry após loss requer |displacement| >= reentry_min_displacement_pts (8pts); flip entries usam hft_min_displacement_pts (4pts) normal; gate desativado se threshold=0
33. **notify_close_pnl()**: strategy DEVE receber PnL do close via notify_close_pnl() — reentry gate depende de _last_close_pnl
34. **set_position_side()**: DEVE setar _position_side = side em TODOS os branches (if e elif) — _last_close_side depende disso

---

## RISCOS ARQUITETURAIS

| ID | Risco | Mitigação | Status |
|----|-------|-----------|--------|
| RA1 | Cache stale inerente ao design | sync antes de close E antes de signal | MITIGADO |
| RA2 | Risk Engine cego a PnL de broker closes | _last_known_pnl preserva PnL | MITIGADO |
| RA3 | ExecutionEngine._lock contention em falha | Single-strategy | Aceitável V1 |
| RA4 | Watchdog não protege contra hang em MT5 IPC | freeze detection | Não pode interromper chamada MT5 bloqueada |
| RA5 | _stop_trading permanente até restart | Removido excessive_losses stop; daily_loss continua | **FIXED V8** |
| RA6 | Session filter usa datetime.now() local | Assumir servidor em BRT | Sem timezone config |
| RA7 | TP/SL podem ser rejeitados por broker (retcode 10016) | Auto-detecção stops_level + fallback 200pts + SL=60pts | FIXED V3 |
| RA8 | Sem trend_bars gate, pode entrar em spikes isolados | acc_boost + trend_boost penalizam spikes | Aceitável |
| RA9 | Trailing stop pode causar exits prematuros | V12.11: virtual trailing activation=6pts, offset=8pts (R$1.60) — captura gains >6pts com 8pts pullback room; broker trailing offset=200pts decorativo | MONITORAR V12.13 |
| RA10 | Loss exit em 18pts pode sair em noise | SL broker=35pts safetynet; profit_pts correto (V12.5); loss_min=18 provado em V12.11 (+99pts) | MONITORAR V12.13 |

---

## BUGS CORRIGIDOS (V1-V11)

| ID | Fix | Descrição |
|----|-----|-----------|
| R1/M6 | FIXED | sync_with_mt5() + _update_position_side() antes de _handle_signal |
| R2/M1 | FIXED | _last_known_pnl preserva PnL antes de _reset_state() |
| R3/M4 | FIXED | _last_close_attempt_time com cooldown; urgent reasons bypassam |
| R5/M2 | FIXED | Latência usa avg_latency_ms do RiskEngine |
| R6/M3 | FIXED | Único momentum_history.push(momentum) em evaluate() |
| R4/M7 | FIXED | Watchdog threading.Event; request_shutdown() idempotente |
| R7/M5 | FIXED | consecutive_losses reset em check_pre_trade |
| V2-1 | FIXED | _calc_velocity() usa signed deltas (removido np.abs) |
| V2-2 | FIXED | _check_hft_reversal() thresholds com abs() para momentum signed |
| V3-1 | FIXED | SL/TP inoperante — auto-detecção stops_level + fallback 200pts |
| V3-2 | FIXED | trend_bars filtro < 2 → < 3 |
| V3-3 | FIXED | Trailing stop spam — cooldown 2s + stops compatíveis |
| V4-1 | FIXED | Reversal sem filtro — vel_fast ×1.5 + disp ≥ 8.0 → V11: vel×2.0 + disp≥30 |
| V4-2 | FIXED | Whipsaw após CLOSE — post-close cooldown |
| V5-1 | FIXED | Settings dessincronizados |
| V7-1 | FIXED | trend_bars gate removido — booster |
| V8-1 | FIXED | direction_reversal disp±5 → ±20 (saindo cedo demais) |
| V8-2 | FIXED | displacement_flip disp±3 → ±10 (saindo em noise) |
| V8-3 | FIXED | quick_profit disp≥15→25, após 5s (winners cortados cedo) |
| V8-4 | FIXED | trailing_stop 80→150 (trailing atingido antes de min_hold) |
| V8-5 | FIXED | min_hold 3→5s com TODAS saídas bloqueadas |
| V8-6 | FIXED | Risk engine permanent stop removido (excessive_consecutive_losses) |
| V8-7 | FIXED | max_consecutive_losses 5→8 |
| V8-8 | FIXED | cooldown_after_loss 1500→2000ms |
| V8-9 | FIXED | post_close_cooldown 0.5→1.0s |
| V9-1 | FIXED | Exit adverso abaixo de 50% SL bloqueado — exit_min_sl_pct=0.5 gate |
| V9-2 | FIXED | Thresholds hardcoded no strategy movidos para settings.py (PositionSettings) |
| V10-1 | FIXED | direction_reversal, displacement_flip, quick_profit removidos — simplificação extrema |
| V11-1 | FIXED | Trailing stop com activation gate (+5pts) — não trilha em prejuízo |
| V11-2 | FIXED | profit_pts calculado corretamente em pontos — não em preço |
| V11-3 | FIXED | offset_price = trailing_offset_pts × 100 × point — conversão correta |
| V11-4 | FIXED | TP=0 no broker — _validate_stops pula validação TP quando tp=0 |
| V11-5 | FIXED | loss_min_pts=30, loss_max_pts=60 — saída bounded em vez de 50% SL |
| V11.1-1 | FIXED | momentum_burst.py _check_idle_fallback indentação — linhas 256-286 com indent-4 a menos |
| V12-1 | FIXED | 39% trades sem trailing (activation +5pts alto demais) → activation=3pts |
| V12-2 | FIXED | Reversal não verificava min_hold_seconds → gate adicionado em _evaluate_with_position |
| V12-3 | FIXED | 52% re-entradas <1s após close (147 quick flips) → post-close cooldown 3s |
| V12-4 | FIXED | Reversal gate fraco (vel×2.0) → vel×3.0 |
| V12-5 | FIXED | Signal noise (cooldown 100ms) → 200ms |
| V12.1-1 | FIXED | hft_min_velocity=3.0 filtra quase nada → 5.0 |
| V12.1-2 | FIXED | hft_min_displacement_pts=1.0 filtra quase nada → 5.0 |
| V12.1-3 | FIXED | hft_min_micro_range=1.0 permite flat market → 3.0 |
| V12.1-4 | FIXED | adaptive_threshold_low=3.0 muito permissivo (64% ticks) → 5.0 |
| V12.1-5 | FIXED | adaptive_threshold_mid=5.0 → 8.0, high=8.0 → 12.0 (progressão 5/8/12) |
| V12.1-6 | FIXED | cooldown_after_loss 2s curto demais (LOSS+flip WR=37.8%) → 5s |
| V12.1-7 | FIXED | hft_max_spread_ticks=5 permite spread alto → 3 |
| V12.2-1 | FIXED | adaptive_threshold_low=5.0 mata frequency → 4.0 |
| V12.2-2 | FIXED | hft_min_displacement_pts=5.0 corta entries 3-5pt (39%WR) → 3.0 |
| V12.2-3 | FIXED | hft_max_spread_ticks=3 muito restritivo → 4 |
| V12.2-4 | FIXED | hft_min_micro_range=3.0 bloqueia range moderado → 2.0 |
| V12.2-5 | FIXED | hft_acceleration_gate corta moves em pullback → OFF |
| V12.2-6 | FIXED | cooldown_after_loss 5s mata frequency → 3s |
| V12.2-7 | FIXED | fallback_min_velocity=3.0 desalinhado com threshold_low → 4.0 |
| V12.3-1 | FIXED | min_hold=10s dominant bottleneck → 5s |
| V12.3-2 | FIXED | loss_min=30pts prende trade 20-40s → 15pts |
| V12.3-3 | FIXED | post_close_cooldown=3s mata frequency → 1s |
| V12.3-4 | FIXED | reversal_vel_mult×3.0 torna reversal impossível → ×1.5 |
| V12.3-5 | FIXED | cooldown_after_loss=3s acumula com outros → 1.5s |
| V12.3-6 | FIXED | reversal_min_disp=30 desalinhado com loss_min_pts=15 → 15 |
| V12.4-1 | FIXED | loss_min_pts=15 mata trades antes de trailing activation → 25pts (71% exits no mínimo, zero trailing) |
| V12.4-2 | FIXED | reversal_min_disp=15 desalinhado com loss_min_pts=25 → 25 |
| V12.5-1 | FIXED | `100 * self._point` divisor 100x errado (WINM26 Point=1.0) → `self._point` em 3 locais. ZERO trailing activations explicado |
| V12.5-2 | FIXED | trailing_activation_pts=3.0 ruído com point=1.0 (3pts=R$0.60) → 5.0 (R$1.00) |
| V12.5-3 | FIXED | trailing_offset_pts=2.0 dentro do spread=5 → 7.0 (acima do spread) |
| V12.6-1 | FIXED | trailing_offset_pts=7.0 << broker min 200pts → 5143× "10016 Invalid stops" → offset=200.0 |
| V12.6-2 | FIXED | `_trailing_activated` permanente (nunca reset) → trailing em prejuízo + spam 10016 → deactivation gate (profit < activation → False) |
| V12.6-3 | FIXED | Sem min_stop_distance validation no trailing → new_sl podia violar broker constraint → min_dist check ajusta new_sl |
| V12.6-4 | FIXED | Resíduo `return True/False` no SELL block causava early return antes do already-activated block → removido |
| V12.8-1 | FIXED | min_hold=3s permite exits prematuros 0% WR (27 trades, -112pts) → 5s (44.6% WR, +48pts) |
| V12.8-2 | FIXED | loss_min_pts=15 boundary noise: 57% exits no adverse=15 exato → 20pts (+5pts espaço para reverter) |
| V12.8-3 | FIXED | reversal_min_disp=10 bloqueia reversões com disp 5-10 quando loss≥15+ → 5.0 (metade de loss_min=20) |
| V12.8-4 | FIXED | hft_acceleration_gate=True corta 44% entries (acc negativo mas direção correta) → False (acc como booster) |
| V12.10-1 | FIXED | SpeedFilter strength = body/spread era metricamente inútil (spread~5pts → strength sempre ~1.0) → price_span/directional_range |
| V12.10-2 | FIXED | SpeedFilter allowed=False por default matava frequência → allow NEUTRO/ACELERANDO/FORTE, block apenas LENTO/EXAUSTAO |
| V12.10-3 | FIXED | SpeedFilter acessava `_ticks` privado do TickEngine → `get_recent_ticks(count)` interface pública |
| V12.10-4 | FIXED | SpeedFilter sem métricas agregadas → SpeedFilterStats com rejection rate, diagnostic logs a cada 10s |
| V12.10-5 | FIXED | trailing_virtual_offset_pts documentado como 8.0 mas settings real = 5.0 → STATE.md atualizado para 5.0 |
| V12.12-1 | FIXED | avg_latency média simples envenenada por outliers (8-22s) → risk_block mata todos sinais → trimmed mean (drop top/bottom 10%) + reject samples >5000ms |
| V12.12-2 | FIXED | loss_exit/loss_max não-urgent sofre 500ms close cooldown → loss overshoot 5-10pts → urgent bypass (igual session_block/shutdown) |
| V12.13-1 | FIXED | `set_position_side(BUY)` if branch não setava `_position_side = side` → `_last_close_side` sempre None → post_close_cooldown NUNCA funcionava desde V12.9+ → adicionado `self._position_side = side` no if branch (L40) |
| V12.13-2 | FIXED | Strategy não sabia se close foi win ou loss → `notify_close_pnl(pnl)` adicionado; main.py chama após close normal (L428) e broker-close (L392) |
| V12.13-3 | FIXED | Same-side re-entry após loss com displacement fraco (|disp|<=5pt WR=52.2%, avgPnL=-1.0) → reentry displacement gate: requer |disp|>=8pts para same-side after loss; flip entries não afetadas |

---

## FUNCIONALIDADE IMPLEMENTADA

- `PositionManager.check_trailing_stop` — **IMPLEMENTADO** com activation gate (+5pts), offset 200pts (≥broker min), cooldown 0.3s, `_trailing_activated` state, **V12.6: deactivation gate + min_stop_distance validation + resíduo removido**, **V12.5: profit_pts = price_diff / point (sem 100×)**
- `_modify_sl` — **IMPLEMENTADO** envia tp=self._take_profit (0.0 quando sem TP)
- Daily reset automático — **IMPLEMENTADO** em `main.py:126-137`
- Status reporting periódico — **IMPLEMENTADO** em `main.py:418-446`
- Config do usuário (JSON) — **IMPLEMENTADO** em `config/config_loader.py`
- Account snapshot — **IMPLEMENTADO** em `mt5_connector.py:get_account_snapshot()`, cached
- Async execution — **IMPLEMENTADO** em `execution_engine.py:96-115`, callback via queue
- Invalid stops fallback — **IMPLEMENTADO** em `execution_engine.py:282-298`
- Signal dedup — **IMPLEMENTADO** em `momentum_burst.py:366-380` + `main.py:283-295`
- Trend bars — **IMPLEMENTADO** em `tick_engine.py:124-141`
- Hold mínimo — **IMPLEMENTADO** em `momentum_burst.py:148-149,113`, loss_exit E reversal bloqueados nos primeiros 5s
- Reversal filter — **IMPLEMENTADO** em `momentum_burst.py:113-144`, vel_fast ×1.2 + disp ≥20pts + hold ≥5s
- Post-close cooldown — **IMPLEMENTADO** em `momentum_burst.py:35,43,191-195`, 0.5s após close
- Loss exit bounded — **IMPLEMENTADO** em `momentum_burst.py:146-167`, adverse 20-40pts
- TP=0 suportado — **IMPLEMENTADO** em `execution_engine.py:240,250` (_validate_stops pula tp=0)
- SpeedFilter — **IMPLEMENTADO** em `core/speed_filter.py` — speed (pts/s), strength (price_span/directional_range), 5 states, allow NEUTRO/ACELERANDO/FORTE, block LENTO/EXAUSTAO, SpeedFilterStats, diagnostic logs
- TickEngine.get_recent_ticks() — **IMPLEMENTADO** em `core/tick_engine.py` — interface pública ao buffer de ticks

---

## BUGS RESTANTES

| ID | Severidade | Descrição | Status |
|----|-----------|-----------|--------|
| R8 | MÉDIO | positions_get() sob ExecutionEngine._lock | Deferido |
| R9 | MÉDIO-BAIXO | _calc_velocity cria lista temporária a cada tick | Deferido |
| R10 | MÉDIO-BAIXO | CircularBuffer.to_array() cria lista temporária ×4 por tick | Deferido |
| V2-11 | MÉDIO | sync_with_mt5() blocking IPC a cada 50 ciclos + antes de signal | Deferido |
| V2-13 | BAIXO | Excessive INFO logging no hot path (console I/O bottleneck) | Deferido |

---

## IPC MT5 — ORÇAMENTO POR CICLO

| Cenário | IPC |
|---------|-----|
| Idle (sem sinal) | 1x (symbol_info_tick) |
| A cada 30s | +1x (terminal_info) |
| A cada 30s | +1x (account_info = get_account_snapshot) |
| A cada 50 ciclos | +1x (positions_get) |
| Sinal detectado | +1x (sync_with_mt5 = positions_get) |
| Sinal → trade (async) | +2x (symbol_info_tick + order_send) |
| Trade com requote | +3-5x |
| Close | +3x (positions_get + symbol_info_tick + order_send) |
| Trailing SL modify | +1x (order_send SLTP) |

---

## LOCKS ATIVOS

| Lock | Classe | Protege | Contenção |
|------|--------|---------|-----------|
| ExecutionEngine._lock | threading.Lock | order_send + price refresh + positions_get (em _close_position) | Baixa |
| ExecutionEngine._execution_busy_lock | threading.Lock | _execution_busy flag | Muito baixa |
| HFTBot._async_results_lock | threading.Lock | _pending_async_results queue | Muito baixa |

---

## DECISÕES DE DESIGN

- NETTING-only — validação com fallback chain
- Tick-based — nenhum timeframe, nenhuma vela
- Execution-first — lock, slippage, retry, circuit breaker
- IPC minimizado — point cached, positions_get raro
- No pandas/TF/AI — numpy aceitável V1 para <200 elem
- Position side injection — strategy não depende de PositionManager
- Session filter — bloqueia open/close/rollover, força close em bloqueio
- Watchdog daemon — dead tick (20s grace quando execution_busy) + freeze detection
- Close cooldown — 500ms entre tentativas; urgent reasons bypassam
- Broker PnL recovery — _last_known_pnl preserva PnL quando posição some
- Velocity SIGNED — direção é fundamental, np.abs destrói informação
- trend_bars=booster — continuação é bonus (strength×1.1-1.5), não obrigatório
- Hold mínimo 5s — loss_exit E reversal bloqueados nos primeiros 5 segundos
- **Virtual trailing stop = ÚNICA saída de gain** — activation +6pts, virtual offset 8pts (R$1.60 atrás), close via market order; broker trailing offset 200pts decorativo (safetynet). Deactivation gate: virtual trailing desativa quando profit < activation
- **Loss bounded 18-35pts** — estratégia sai em adverse >= 18pts, SL broker=35pts safetynet
- Reversal entry: vel_fast ×1.2 + disp ≥9pts + hold ≥5s — reverte em momentum moderado e loss real
- Risk engine NÃO para permanentemente (exceto daily_loss) — cooldown após loss basta
- Post-close cooldown 0.3s — previne same-tick echo trades, maximiza frequency
- micro_range HARD block — mercado lateral = só perde spread, nunca entra
- Fallback = HFT entry quality — mesmos filtros (sem trend_bars gate, disp mesma direção)
- **acceleration_gate=OFF** — 44% entries cortadas por acc negativo; momentum desacelerando mas direção correta; acc continua como booster no strength
- **Virtual trailing é prioritário** — check_virtual_trailing() roda ANTES de check_trailing_stop() no main loop; se virtual trailing trigger, close imediato sem broker SL modify
- **SpeedFilter gate**: allow NEUTRO/ACELERANDO/FORTE, block LENTO/EXAUSTAO — preserva frequência HFT enquanto filtra entradas sem qualidade
- **SpeedFilter strength = price_span / directional_range** (não body/spread) — spread (~5pts WINM26) é metricamente inútil como denominator; directional_range captura range real da janela
- **SpeedFilter speed em pts/second** (não pts/tick-period) — normaliza para tick rate variável
- **Reentry displacement gate** — same-side after loss requer |disp|>=8pts (vs normal 4pts); preserva quick high-disp re-entries (71.4% WR, +2.43pts), bloqueia slow low-disp (44.4% WR, -0.22pts); flip entries não afetadas

---

## NEXT STEPS

1. **Deploy V12.13 em demo e coletar métricas de sessão** — validar reentry gate + bug fix + notify_close_pnl em produção
2. Verificar `[REENTRY BLOCKED]` em logs — confirmar gate está filtrando low-disp same-side after loss
3. Verificar `_last_close_side` agora funciona (não é mais None) — post_close_cooldown ativo pela primeira vez
4. Monitorar WR: same-side re-entry after loss vs flip after loss — expectativa: menos flip entries ruinosas, mais chase entries filtradas
5. Se WR <55%: investigar se reentry_min_displacement_pts=8.0 é muito alto (reduzir para 6.0) ou muito baixo (aumentar para 10.0)
6. Se frequency cai muito: reentry gate pode estar bloqueando entries válidas — verificar |disp| distribution em logs
7. Atingir target: 60% WR + 5 trades/min + PnL>0
