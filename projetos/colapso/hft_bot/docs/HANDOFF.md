# HANDOFF.md — HFT Bot WIN$ Estado Atual

## 1. Arquitetura Atual

### 1.1 Diagrama de Componentes

```
main.py (HFTBot) — orquestrador, single-thread principal
 │
 ├─ MT5Connector ──── connect/reconnect/heartbeat/get_tick/session/account_snapshot
 ├─ TickEngine ────── process_tick → compute_metrics (numpy)
 ├─ SignalEngine ──── dispatcher → StrategyBase.evaluate()
 │   └─ MomentumBurst ── entry/reversal/close logic
 ├─ ExecutionEngine ── order_send com _lock, requote retry, slippage
 ├─ PositionManager ── sync_with_mt5, cached state, timeout/pnl stops
 ├─ RiskEngine ─────── pre-trade/post-trade/circuit-breaker/latency
 ├─ Watchdog ───────── daemon thread, dead tick/freeze detection
 └─ Log ────────────── 8 named loggers, console=INFO, file=DEBUG
```

### 1.2 Thread Model

| Thread | Função | Daemon |
|--------|--------|--------|
| Main | Loop principal: get_tick → process → metrics → signal → execute | Não |
| Watchdog | Monitora dead tick e freeze | Sim |

- Main loop é single-thread. Nenhum módulo spawn threads além do Watchdog.
- ExecutionEngine._lock protege order_send contra concorrência (relevante se futuro multi-strategy).

### 1.3 Fluxo do Main Loop (por tick)

```python
1. watchdog.notify_cycle()
2. watchdog.is_shutdown_requested? ──────── [threading.Event.is_set()]
3. connector.heartbeat() ────────────────── [MT5 IPC: terminal_info()] a cada 30s
4. connector.get_account_snapshot() ─────── [MT5 IPC: account_info()] a cada 30s (cached, cold path)
5. connector.is_session_allowed() ────────── [datetime math, zero IPC]
6. connector.get_tick() ──────────────────── [MT5 IPC: symbol_info_tick()] ← 1x obrigatório
7. tick_engine.process_tick(raw_tick) ────── [deque append, CircularBuffer.push]
8. watchdog.notify_tick()
9. position_manager.sync_with_mt5() ──────── [MT5 IPC: positions_get()] a cada 50 ciclos
10. update_position_side() ────────────────── [property read, zero IPC]
11. check_position_management() ────────────── [timeout=math, should_close_pnl=cache, trailing_stop]
12. tick_engine.compute_metrics() ─────────── [numpy: diff, abs, sum, mean <200 elem]
13. signal_engine.evaluate() ──────────────── [CircularBuffer.to_array() ×4]
14. risk_engine.check_pre_trade() ─────────── [deque ops, math, zero IPC]
15. execution_engine.execute_signal() ─────── [MT5 IPC: symbol_info_tick + order_send] ← lock
```

---

## 2. Arquivos Existentes

| Arquivo | Linhas | Responsabilidade |
|---------|--------|-----------------|
| `main.py` | 320 | Orquestrador HFTBot: init, main loop, daily reset, signal handling, close, shutdown, status report |
| `__init__.py` | 0 | Package init (vazio) |
| `__main__.py` | 12 | Entry point para `python -m hft_bot`: ajusta CWD+sys.path, chama main() |
| `core/utils.py` | 102 | DTOs (TickData, Signal, TradeResult, TickMetrics), enums (SignalType, OrderSide, TradeStatus), CircularBuffer, helpers (now_ms, elapsed_ms) |
| `core/logger.py` | 67 | Log singleton: 8 named loggers, console=INFO, file=DEBUG, RotatingFileHandler 5MB/5 backups |
| `core/mt5_connector.py` | 255 | MT5 connect/login/NETTING validation, reconnect com retry, heartbeat, get_tick, is_session_allowed, get_account_snapshot (cached+interval), symbol validation |
| `core/tick_engine.py` | 131 | Tick processing, metrics computation (velocity/acceleration/delta/micro_range/spread), numpy para small arrays |
| `core/signal_engine.py` | 74 | StrategyBase ABC (evaluate, _create_signal, _check_cooldown), SignalEngine dispatcher |
| `core/execution_engine.py` | 470 | Thread-safe order execution: execute_signal, close_position, _build_request, _validate_stops (auto-detecção broker stops_level + fallback 200pts), _send_order com requote retry, slippage calc |
| `core/position_manager.py` | 252 | Position state machine: sync_with_mt5, register_open/close, should_close_timeout, should_close_pnl, trailing stop (200pts, 2s cooldown), reset_daily |
| `core/risk_engine.py` | 231 | Pre-trade checks (circuit breaker, daily loss, consecutive losses, cooldown, rate, spread, latency), post-trade PnL, execution error tracking, reset_daily |
| `core/watchdog.py` | 85 | Daemon thread: dead tick detection, cycle freeze detection, shutdown request (threading.Event), reset_daily |
| `strategies/momentum_burst.py` | 417 | Momentum burst strategy: entry (velocity+acceleration+trend_bars≥3), direction_reversal (disp≥5.0), displacement_flip (≥3.0), position-aware evaluation, min_hold=5s |
| `config/settings.py` | 124 | 8 dataclasses: MT5Settings, TradingSettings (hft_tp=300, hft_sl=200), TickSettings, SignalSettings, RiskSettings (+ V2 sizing placeholders), PositionSettings (trail=200), SessionSettings, SystemSettings |
| `config/config_loader.py` | 120 | JSON → dataclass merge: load_user_config, type coercion, fallback, BOM-safe, secret masking |
| `core/__init__.py` | 8 | Re-exports dos módulos core |
| `config/__init__.py` | 1 | Vazio |
| `strategies/__init__.py` | 1 | Vazio |
| `requirements.txt` | 2 | MetaTrader5>=5.0.45, numpy>=1.26.0 |

### 2.1 Hierarquia de Dependências

```
main.py
 ├── config.settings (Settings)
 ├── core.logger (Log)
 ├── core.mt5_connector (MT5Connector)
 │    ├── core.utils (now_ms)
 │    └── config.settings (Settings, MT5Settings)
 ├── core.tick_engine (TickEngine)
 │    ├── core.utils (TickData, TickMetrics, CircularBuffer, now_ms)
 │    └── config.settings (Settings, TickSettings)
 ├── core.signal_engine (SignalEngine, StrategyBase)
 │    ├── core.utils (TickData, TickMetrics, Signal, SignalType)
 │    └── config.settings (Settings, SignalSettings)
 ├── strategies.momentum_burst (MomentumBurst)
 │    ├── core.signal_engine (StrategyBase)
 │    ├── core.utils (TickData, TickMetrics, Signal, SignalType, OrderSide, CircularBuffer)
 │    └── config.settings (Settings, SignalSettings, TickSettings)
 ├── core.execution_engine (ExecutionEngine)
 │    ├── core.utils (Signal, TradeResult, TradeStatus, SignalType, OrderSide, elapsed_ms)
 │    └── config.settings (Settings, TradingSettings)
 ├── core.risk_engine (RiskEngine)
 │    ├── core.utils (TickData, Signal, SignalType, OrderSide)
 │    └── config.settings (Settings, RiskSettings)
 ├── core.position_manager (PositionManager)
 │    ├── core.utils (Signal, SignalType, TradeResult, TradeStatus, OrderSide)
 │    └── config.settings (Settings, PositionSettings)
 └── core.watchdog (Watchdog)
      └── config.settings (Settings, SystemSettings)
```

- Sem dependência circular.
- Strategy recebe `position_side` via `set_position_side()` injetado do main loop — não depende de PositionManager.
- TickEngine, ExecutionEngine, StrategyBase recebem `point` via `set_point()`/`set_instrument_info()` — não fazem symbol_info IPC.

---

## 3. Responsabilidades por Módulo

### HFTBot (main.py)
- Orquestração completa do ciclo de vida: init → loop → shutdown
- Decisão de fluxo: session block, reversal, new entry, close
- Injeção de `position_side` no strategy
- Registro de PnL em RiskEngine após close
- Fechamento forçado em session block e shutdown
- Signal handler (SIGINT/SIGTERM) → stop()
- Daily reset: `_daily_reset_pending` flag, chama reset_daily em RiskEngine/PositionManager/Watchdog quando posição fecha e data mudou (main.py:104-115)
- Status reporting periódico: _report_status() a cada status_report_interval_sec — inclui balance/equity/margin_free/margin_used/account_pnl via get_account_snapshot()
- Final status: _get_final_status() — inclui balance/equity/margin_free via get_account_snapshot()
- Trailing stop: position_manager.check_trailing_stop() chamado por tick

### MT5Connector
- Conexão com validação NETTING (margin_mode com fallback chain)
- Reconnect com retry e delay configurável
- Heartbeat periódico (terminal_info)
- get_tick() — único ponto de acesso a symbol_info_tick
- is_session_allowed() — filtro de horário com open/close/rollover blocks
- get_symbol_info() — usado em init e re-init
- get_account_snapshot() — balance/equity/margin_free/margin_used/floating_pnl, cached + interval (heartbeat_interval_ms), fallback zeros se MT5 indisponível, zero hot-path impact (cold path)

### TickEngine
- Conversão raw_tick → TickData (mid, spread, delta, time_ms)
- Buffer circular de ticks (deque maxlen=200)
- Cálculo de métricas: velocity (windowed absolute diff/s), acceleration (vel delta/2), micro_range (ask-bid range), avg_velocity
- numpy para diff/abs/sum/mean em arrays <200

### SignalEngine + StrategyBase
- Dispatcher: delega evaluate() à strategy configurada
- StrategyBase ABC: evaluate(), _create_signal() com SL/TP em ticks, _check_cooldown(), _mark_signal_time()
- Proteção: is_valid check, cooldown entre sinais

### MomentumBurst
- Entry: velocity_fast > threshold + acceleration mesma direção + trend_bars ≥ 3 + micro_range hard block + spread ≤ 5
- Com posição: direction_reversal (|disp|≥5.0, hold≥5s) → CLOSE
- Com posição: displacement_flip (|entry_disp|≥3.0 → |now_disp|≥3.0 oposto) → CLOSE
- Com posição: sinal oposto → reversal com filtro reforçado (|vel_fast| ≥ threshold ×1.5 AND |disp| ≥ 8.0)
- Com posição: same-side signal → NONE (ignorado)
- Post-close cooldown: 2s — sem nova entrada após close por 2s
- CircularBuffer para recent_highs(50), recent_lows(50)
- Idle fallback com mesmos filtros (trend_bars≥3, acc, micro_range)

### ExecutionEngine
- Thread-safe: _lock protege todo order_send
- execute_signal: BUILD request → SEND → retry requote (3x) → calc slippage
- close_position: detecta position_type → ORDER_TYPE_SELL/BUY inverso
- _close_position (via Signal): positions_get → close_position
- Requote retry: refresh preço via symbol_info_tick
- FROZEN: retorno imediato sem retry
- Slippage: signed, convertido para ticks via _point cached
- _point cacheado via set_point() — zero symbol_info IPC em hot path

### PositionManager
- sync_with_mt5(): única fonte de truth para estado de posição (1x positions_get por sync)
- Cached: _current_ticket, _current_side, _current_volume, _current_pnl, _current_position_type, _entry_price, _entry_time, _stop_loss, _take_profit, _trailing_sl
- register_open(): atualiza cache após trade sucesso (inclui _trailing_sl)
- register_close(): _reset_state() após close sucesso
- should_close_timeout(): elapsed > trade_timeout_ms
- should_close_pnl(): _current_pnl <= -(max_daily_loss / 4)
- check_trailing_stop(): trailing stop logic — move SL a favor (offset=200pts), 2s cooldown entre tentativas, _modify_sl() fora de ExecutionEngine._lock (V1 debt, safe single-thread)
- _modify_sl(): mt5.order_send direto para SL modify — sem retry em requote (SL original protege, próximo tick retry natural)
- _last_known_pnl: preserva PnL antes de _reset_state() para broker closes
- add_realized_pnl(): tracking acumulado
- reset_daily(): reseta estado diário

### RiskEngine
- check_pre_trade(): 7 checks sequenciais (trading_enabled → circuit_breaker → daily_loss → consecutive_losses → cooldown → trade_rate → spread → latency)
- check_post_trade(): atualiza daily_pnl, consecutive_losses, auto_stop_check
- register_execution_error/success(): circuit breaker por erros consecutivos
- record_latency(): amostras para avg_latency
- check_close_signal(): projected daily + position PnL vs max_daily_loss
- _auto_stop_check(): para trading se daily_loss excedido OU 2× consecutive_losses
- _stop_trading(): idempotente (não para se já parado)
- register_trade_attempt(): rate limit tracking

### Watchdog
- Daemon thread monitorando:
- Dead tick: sem tick há > watchdog_tick_timeout_ms (10000ms) → shutdown
- Cycle freeze: ciclo parado há > 500ms → contador, 5 strikes → shutdown
- notify_tick()/notify_cycle() chamados do main loop
- request_shutdown(): idempotente via threading.Event (M7 fix)
- reset_daily(): reseta freeze_count e disconnect_count
- check_interval: max(1.0s, timeout/2)

### Log
- 8 named loggers com routing específico:

### Config Loader
- `load_user_config(path, Settings)` — chamado 1x no startup (main.py)
- Lê `config/user_config.json` (utf-8-sig, BOM-safe)
- Se arquivo não existe: loga INFO, retorna Settings inalterado (zero impacto)
- Se JSON inválido/corrompido: loga WARNING, retorna defaults
- Mapeia seções JSON → dataclasses via `_JSON_MAP`:
  - `"account"` → `Settings.mt5` (MT5Settings)
  - `"trading"` → `Settings.trading` (TradingSettings)
  - `"risk"` → `Settings.risk` (RiskSettings)
  - `"execution"` → `Settings.risk` (RiskSettings — max_spread_ticks, max_latency_ms)
  - `"strategy"` → split: `take_profit_ticks`/`stop_loss_ticks` → TradingSettings, resto → SignalSettings
  - `"position"` → `Settings.position` (PositionSettings)
  - `"session"` → `Settings.session` (SessionSettings)
  - `"system"` → `Settings.system` (SystemSettings)
- Type coercion: `type(field_default)(value)` — fallback a default se TypeError/ValueError
- Campo desconhecido: loga WARNING, ignora
- Seção desconhecida: loga WARNING, ignora
- Password: loga `***` (nunca exposta)
- `_LOADED_PATHS` protege contra double-load
- ZERO impacto em hot path — roda só no startup

### Log (cont.)
- 8 named loggers com routing específico:
  - trade → console + trades.log
  - error → console + errors.log
  - system → console + system.log
  - execution → console + system.log + trades.log
  - risk → console + system.log + errors.log
  - tick → system.log APENAS (sem console — anti-spam)
  - signal → console + system.log
  - position → console + system.log + trades.log
- Console: INFO. File: DEBUG. RotatingFileHandler: 5MB, 5 backups.

---

## 4. Decisões HFT

### 4.1 NETTING-Only
- Conta validada como NETTING na conexão (margin_mode com fallback: ACCOUNT_MARGIN_MODE_RETAIL_NETTING → EXCHANGE_NETTING → raw==2)
- 1 posição líquida por símbolo — sem multi-ticket
- Reversão: sinal oposto passado como BUY/SELL direto. MT5 liquida posição automaticamente.
- Sem tipo REVERSE — SignalType tem apenas BUY, SELL, CLOSE, NONE

### 4.2 Tick-Based, Not Candle-Based
- Nenhum timeframe, nenhuma vela, nenhum OHLC
- Unidade fundamental: tick (bid/ask/last/volume/time)
- Métricas derivadas: velocity (price movement/s em window), acceleration (vel delta), micro_range (ask-bid range em N ticks)

### 4.3 Execution-First
- ExecutionEngine._lock protege order_send — held só durante MT5 IPC
- Slippage calculado via cached _point — zero symbol_info em hot path
- Requote retry: refresh preço e tenta novamente (max 3x)
- FROZEN retcode: retorno imediato, sem retry

### 4.4 IPC Minimization
- symbol_info_tick(): 1x por ciclo (inevitável — fonte de dados)
- positions_get(): 1x a cada 50 ciclos (~250ms) + 1x antes de close
- terminal_info(): 1x a cada 30s (heartbeat)
- symbol_info(): 1x na init, 1x no re-init após reconnect
- point/digits: cached via set_point(), nunca consultados em hot path

### 4.5 No Pandas, No TF, No AI
- numpy: aceitável V1 para small arrays (<200 elem)
- CircularBuffer própria com __slots__
- deque(maxlen=N) para tick buffer

### 4.6 Position Side Injection
- Strategy não depende de PositionManager (sem circular dep)
- Main loop injeta position_side via strategy.set_position_side()
- Strategy lê _position_side para decidir: entry, reversal, close, same-side ignore

### 4.7 Session Filter
- Bloqueia: primeiro 5min após abertura, último 5min antes fechamento, janela de rollover (16:55-18:05)
- Se posição aberta quando sessão bloqueia: força fechamento
- Horário hardcoded em Settings defaults (9:05-17:50)

---

## 5. Hot Paths

### 5.1 Hot Path Principal (todo tick)

```
connector.get_tick()          → MT5 IPC obrigatório
tick_engine.process_tick()   → O(1) deque append + CircularBuffer.push
watchdog.notify_tick()       → time.time() assignment
tick_engine.compute_metrics():
  _calc_velocity()           → O(window) reversed iteration + np.diff + np.abs + np.sum
  _calc_avg_velocity()       → CircularBuffer.to_array() + np.mean
  _calc_acceleration()       → CircularBuffer.to_array() + arithmetic
  _calc_micro_range()        → list[-N:] + max/min
signal_engine.evaluate()     → CircularBuffer.to_array() ×4 + arithmetic
risk_engine.check_pre_trade() → deque popleft + arithmetic (no IPC)
```

### 5.2 Hot Path por Trade

```
execution_engine.execute_signal():
  _build_request()           → MT5 IPC: symbol_info_tick() para preço
  _send_order()              → MT5 IPC: order_send() (possível requote → +1 symbol_info_tick)
  _calc_slippage_ticks()     → arithmetic, cached _point
risk_engine.register_trade_attempt() → deque append
risk_engine.record_latency() → deque append
position_manager.register_open()    → cache update
```

### 5.3 Cold Paths

```python
connector.heartbeat() → a cada 30s
connector.get_account_snapshot() → a cada 30s (cached, same interval as heartbeat)
position_manager.sync_with_mt5() → a cada 50 ciclos
connector.reconnect() → sob falha
watchdog._monitor_loop() → a cada 5s
Log.shutdown() → apenas no encerramento
```

---

## 6. IPC MT5 — Inventário Completo

| Chamada MT5 | Local | Frequência | Contexto |
|---|---|---|---|
| `mt5.initialize()` | MT5Connector.connect() | 1x init + N reconnect | Startup |
| `mt5.login()` | MT5Connector.connect() | 1x init | Startup |
| `mt5.terminal_info()` | MT5Connector.connect/heartbeat/is_connected | 1x init + ~1x/30s | Cold |
| `mt5.account_info()` | MT5Connector.connect/get_account_info/get_account_snapshot | 1x init + ~1x/30s (snapshot refresh) | Cold |
| `mt5.symbol_info()` | MT5Connector._validate_symbol/get_symbol_info | 1x init + 1x/re-init | Startup |
| `mt5.symbol_select()` | MT5Connector._validate_symbol | 1x condicional | Startup |
| `mt5.symbol_info_tick()` | MT5Connector.get_tick() | Todo ciclo | Hot |
| `mt5.symbol_info_tick()` | ExecutionEngine._build_request() | Por trade | Hot-trade |
| `mt5.symbol_info_tick()` | ExecutionEngine._send_order() (requote) | Por requote retry | Hot-trade |
| `mt5.symbol_info_tick()` | ExecutionEngine.close_position() | Por close | Hot-trade |
| `mt5.positions_get()` | PositionManager.sync_with_mt5() | ~1x/50 ciclos + 1x/close | Warm |
| `mt5.positions_get()` | ExecutionEngine._close_position() | Por close via Signal | Hot-trade |
| `mt5.order_send()` | ExecutionEngine._send_order() | Por trade/close | Hot-trade |
| `mt5.last_error()` | ExecutionEngine._send_order()/MT5Connector._handle_init_failure | Por erro | Cold |
| `mt5.shutdown()` | MT5Connector.shutdown/reconnect | 1x encerramento | Shutdown |

### Contagem IPC por Cenário

| Cenário | IPC por tick |
|---|---|
| Idle (sem sinal) | 1x (symbol_info_tick) |
| A cada 30s | +1x (terminal_info) |
| A cada 50 ciclos | +1x (positions_get) |
| Sinal → trade | +2x (symbol_info_tick + order_send) |
| Sinal → trade com requote | +3-5x (+1 symbol_info_tick por retry) |
| Close | +2x (positions_get + symbol_info_tick + order_send = 3x) |

---

## 7. Locks

| Lock | Classe | Tipo | Protege | Contenção Esperada |
|---|---|---|---|---|
| `ExecutionEngine._lock` | `threading.Lock` | Mutex | order_send + price refresh + positions_get (em _close_position) | Baixa (só durante trade) |
| `Watchdog._shutdown_event` | `threading.Event` | Event | _shutdown_requested | Rara (só shutdown) |

### Observações sobre Locks
- ExecutionEngine._lock é held durante todo o request→send→retry cycle. Se order_send demora 100ms e requote retry acontece, lock held por ~300ms.
- PositionManager NÃO tem lock — acessado apenas pela thread principal.
- RiskEngine NÃO tem lock — acessado apenas pela thread principal.
- TickEngine NÃO tem lock — acessado apenas pela thread principal.
- Watchdog._shutdown_event: threading.Event (M7 fix) — set() idempotente via is_set(), wait() com timeout. notify_tick/notify_cycle são writes atômicos de float em CPython (GIL).

---

## 8. Bugs Conhecidos

### R1 — CRÍTICO: Position side stale entre sync e signal handling
- **Local**: `main.py:170-174`
- **Descrição**: Na reversão, `_handle_signal` lê `current_side` do PositionManager (cache com até 250ms de atraso). Se posição foi fechada por SL/TP do broker, `current_side` stale. Same-side check (`current_side == signal_side → return`) pode descartar sinal válido. Ou tentar reversão em posição inexistente (funciona em netting — abre nova, mas lógica está errada).
- **Fix**: sync_with_mt5() antes de _handle_signal quando signal ≠ NONE

### R2 — CRÍTICO: PnL perdido quando SL/TP do broker fecha posição
- **Local**: `position_manager.py:37`, `main.py:213-231`
- **Descrição**: sync_with_mt5() detecta posição sumiu → _reset_state() zera _current_pnl. get_current_pnl() retorna 0.0. add_realized_pnl(0.0) e check_post_trade(0.0) registram PnL zero. RiskEngine.daily_pnl diverge do real. max_daily_loss pode nunca ser atingido.
- **Fix**: Salvar _last_known_pnl antes de _reset_state. Consumir em _execute_close.

### R3 — ALTO: Loop de close sem cooldown
- **Local**: `main.py:132-133`, `main.py:245-256`
- **Descrição**: Se should_close_timeout() ou should_close_pnl() dispara e _execute_close falha, próximo tick tenta novamente sem cooldown. Spam de order_send.
- **Fix**: Cooldown de 2s entre tentativas de close.

### R4 — BAIXO: Watchdog._shutdown_requested lido sem lock
- **Local**: `watchdog.py:47-48`
- **Descrição**: is_shutdown_requested lê bool sem lock, enquanto request_shutdown escreve sob lock. Tecnicamente race condition, mas CPython GIL protege reads atômicos de bool.
- **Fix**: Substituir por threading.Event.

### R5 — ALTO: Latência calculada incorretamente em check_pre_trade
- **Local**: `main.py:158-160`
- **Descrição**: `latency_ms = (time.time() - last_order_time) * 1000.0` mede tempo desde a última ordem, não latência de conexão. Após 5min sem trades = 300000ms → sempre bloqueado por _check_latency(200). Na primeira ordem = 0 → nunca bloqueado.
- **Fix**: Usar avg_latency_ms do RiskEngine.get_status().

### R6 — ALTO: MomentumBurst push() duplo por tick
- **Local**: `momentum_burst.py:41` e `momentum_burst.py:130`
- **Descrição**: _evaluate_with_position() chama push(momentum) na linha 41. Depois chama _check_entry() que faz push(momentum) na linha 130. CircularBuffer(20) corrompido. _check_reversal() usa janela de 5 ticks que inclui duplicatas.
- **Fix**: Único push em evaluate(), passar momentum como parâmetro.

### R7 — MÉDIO: _check_consecutive_losses reseta contador como side effect
- **Local**: `risk_engine.py:126`
- **Descrição**: Se cooldown expirou, _consecutive_losses = 0 dentro de _check_consecutive_losses(). Mas _check_cooldown() logo depois pode bloquear. Consecutive_losses zerou mas cooldown ativo — estado inconsistente.
- **Fix**: Resetar consecutive_losses no caller (check_pre_trade) após ambos checks passarem.

### R8 — MÉDIO: positions_get() sob ExecutionEngine._lock
- **Local**: `execution_engine.py:432`
- **Descrição**: _close_position() chama positions_get() enquanto segura _lock. Se IPC lento (MT5 desconectado), lock held por mais tempo.
- **Fix**: Mover positions_get para antes do lock, ou usar dados do PositionManager.

### R9 — MÉDIO-BAIXO: _calc_velocity cria lista temporária a cada tick
- **Local**: `tick_engine.py:85-107`
- **Descrição**: prices = [] + append em reversed loop + .reverse(). Em hot path, 1-2 listas criadas por tick.
- **Fix**: V2 — usar iteração direta sem lista temporária.

### R10 — MÉDIO-BAIXO: CircularBuffer.to_array() cria lista temporária
- **Local**: `utils.py:101-112`
- **Descrição**: Chamado ~4x por tick no MomentumBurst. Cada chamada cria lista nova.
- **Fix**: V2 — __getitem__ com acesso direto por índice.

### V3-1 — FIXED: SL/TP inoperante (retcode 10016 Invalid stops)
- **Local**: `execution_engine.py:209-254`, `config/settings.py:23-24`
- **Descrição**: Broker exige stops ≥200pts. Settings tinham hft_tp=5, hft_sl=15, trail=5. 100% das ordens com SL/TP rejeitadas. Fallback sem SL/TP deixava posição sem proteção.
- **Fix**: _validate_stops() auto-detecta stops_level + fallback 200pts. Settings: hft_tp=300, hft_sl=200, trail=200. main.py: inicializa min_stop_distance no startup.

### V3-2 — FIXED: trend_bars filter usava < 2 em vez de < 3
- **Local**: `strategies/momentum_burst.py:206,229,268,280`
- **Descrição**: Config dizia 3, código usava 2. Spike isolado (1 tick) passava no filtro.
- **Fix**: Corrigido para < 3 em todos os 3 locais (BUY, SELL, fallback).

### V3-3 — FIXED: Trailing stop spam (6000+ order_send em 20min)
- **Local**: `core/position_manager.py:31-32,149-151,174`
- **Descrição**: Sem cooldown entre tentativas de trailing modify. Com stops <200pts, 100% rejeitados = spam contínuo.
- **Fix**: Cooldown de 2s + stops compatíveis com broker minimum.

### V3-4 — FIXED: Exit displacement thresholds muito baixos para stops de 200pts
- **Local**: `strategies/momentum_burst.py:134,146,158,170`
- **Descrição**: direction_reversal com |disp|≥1.0 e displacement_flip com qualquer mudança de sinal eram prematuros para SL=200pts.
- **Fix**: direction_reversal |disp|≥5.0, displacement_flip |entry_disp|≥3.0 AND |now_disp|≥3.0 oposto.

### V4-1 — FIXED: Reversal sem filtro de qualidade (mesmo threshold de entrada fresh)
- **Local**: `strategies/momentum_burst.py:106-149`
- **Descrição**: `_evaluate_with_position()` aceitava qualquer sinal oposto de `_check_hft_entry()` como reversal, sem exigir momentum mais forte. Gerava whipsaw — reversão com vel_fast fraco e disp baixo = posição flipada que revertia imediatamente.
- **Fix**: Reversal exige |vel_fast| ≥ adaptive_threshold × 1.5 AND |net_displacement| ≥ 8.0. Sinais fracos são bloqueados com log `[REVERSAL BLOCKED]`.

### V4-2 — FIXED: Whipsaw após CLOSE — re-entrada imediata em momentum instável
- **Local**: `strategies/momentum_burst.py:35,43,58-59`
- **Descrição**: Após CLOSE por direction_reversal/displacement_flip, a estratégia podia gerar nova entrada no tick seguinte (apenas 200ms cooldown). Momentum após close é instável — o preço está se definindo.
- **Fix**: `_last_close_time` rastreado em `set_position_side(None)`. Cooldown de 2s após qualquer close antes de aceitar novo sinal.

### R11 — BAIXO: TradingSettings.trade_timeout_ms órfão
- **Local**: `settings.py:23`
- **Descrição**: Valor=5000, mas PositionManager usa PositionSettings.trade_timeout_ms=30000. Ninguém lê TradingSettings.trade_timeout_ms.

### R12 — BAIXO: SignalSettings.position_side órfão
- **Local**: `settings.py:45`
- **Descrição**: position_side é injetado via set_position_side() em runtime. Campo nunca é lido.

---

## 9. TODO Real

### Prioridade 1 — Bugs Críticos e Altos — TODOS CORRIGIDOS

| ID | Status | Descrição |
|----|--------|-----------|
| M1 | FIXED | PnL perdido em SL/TP broker — _last_known_pnl |
| M2 | FIXED | Latência quebrada — avg_latency_ms do RiskEngine |
| M3 | FIXED | Momentum duplo push — único push em evaluate() |
| M4 | FIXED | Close loop sem cooldown — _last_close_attempt_time |
| M5 | FIXED | Consecutive losses side effect — reset no caller |
| M6 | FIXED | Position side stale — sync antes de handle_signal |

### Prioridade 2 — Consistência — TODOS CORRIGIDOS

| ID | Status | Descrição |
|----|--------|-----------|
| M7 | FIXED | Watchdog._shutdown_requested → threading.Event |
| M8 | FIXED | Cleanup settings órfãos (7 campos removidos) |

### Prioridade 3 — V2 Performance

| ID | Descrição | Arquivos |
|----|-----------|----------|
| P1 | _calc_velocity sem lista temporária | tick_engine.py |
| P2 | CircularBuffer.__getitem__ direto | utils.py |
| P3 | numpy → manual math em arrays pequenos | tick_engine.py |

### Prioridade 4 — Funcionalidade

| ID | Descrição | Status | Arquivos |
|----|-----------|--------|----------|
| P4 | Trailing stop | **IMPLEMENTADO** | position_manager.py, main.py |
| F1 | Carregar settings de arquivo (JSON) | **IMPLEMENTADO** | config/config_loader.py + user_config.json |
| F2 | Daily reset automático | **IMPLEMENTADO** | main.py (com _daily_reset_pending flag) |
| F3 | Status reporting periódico | **IMPLEMENTADO** | main.py (_report_status) |
| F4 | SL/TP modify em posição existente | Parcial (trailing SL ok, TP modify não existe) | — |

---

## 10. Riscos Arquiteturais

### RA1 — Cache Stale é Inerente ao Design
O PositionManager usa cache atualizado a cada 50 ciclos (~250ms) + antes de close. Qualquer decisão baseada em estado de posição entre syncs pode estar stale. Isso é aceitável para timeout/pnl checks, mas **não** para decisões de reversal que dependem de side correto.

**Mitigação atual**: sync antes de close (adicionado). **Necessário**: sync antes de signal handling (M6).

### RA2 — Risk Engine cego a PnL de broker closes
Se SL/TP do broker fecha posição sem que o bot detecte em tempo hábil, o PnL real é perdido no tracking. O bot pode continuar operando achando que o daily loss é menor que o real.

**Mitigação necessária**: M1 (_last_known_pnl). **Limitação residual**: se sync_with_mt5 nunca é chamado (ex: crash antes do próximo ciclo), PnL é perdido até próximo restart.

### RA3 — ExecutionEngine._lock contention em cenários de falha
Se MT5 está lento/conectado mas não respondendo, order_send pode demorar segundos. O lock fica segurado. Nenhuma outra ordem pode ser enviada. Em single-strategy isso é aceitável. Em multi-strategy seria deadlock potencial.

**Mitigação atual**: design é single-strategy. **Limite**: não escalar para multi-strategy sem re-thinking do lock model.

### RA4 — Watchdog não protege contra hang dentro de MT5 IPC
Se symbol_info_tick() trava (MT5 congelado mas não crashou), o main loop trava. Watchdog detecta "cycle freeze" mas não pode interromper a chamada MT5 bloqueada. Não há timeout configurável para chamadas MT5 Python (o timeout é do lado do MT5 terminal).

**Mitigação parcial**: mt5.initialize() aceita timeout param, mas symbol_info_tick não. **Realidade**: se MT5 trava, o bot trava até MT5 voltar ou watchdog matar o processo.

### RA5 — Circuit breaker e _stop_trading são permanentes até restart
RiskEngine._stop_trading() desabilita trading permanentemente (até reset_daily ou restart). Circuit breaker tem cooldown mas _stop_trading("daily_loss_exceeded") não tem recovery automático. Em operação noturna sem intervenção, o bot pode parar e não retomar.

**Mitigação parcial**: auto_stop_trading pode ser desabilitado. **Risco**: se habilitado e daily loss atingido, bot para até intervenção manual.

### RA6 — Session filter usa datetime.now() local
is_session_allowed() usa horário local do servidor Python. Se timezone diferente do broker, filtros de horário podem estar incorretos. B3 opera em Brasília (BRT). Servidor pode estar em UTC.

**Mitigação necessária**: F1 deve incluir timezone. **Workaround**: garantir servidor em BRT.

---

## 11. Invariantes que NÃO Podem Ser Quebradas

### I1 — Single Position NETTING
O bot assume e valida que a conta é NETTING. Só 1 posição por símbolo. Qualquer lógica que assuma multi-position (hedge, partial close, ticket tracking de múltiplas posições) quebra a arquitetura.

### I2 — ExecutionEngine._lock protege order_send
Qualquer chamada a mt5.order_send DEVE ser sob _lock. MT5 Python não é thread-safe — duas order_sends concorrentes podem corromper estado. O lock NÃO pode ser removido ou contornado.

### I3 — symbol_info_tick() é a única fonte de preço em hot path
Nenhum outro ponto do hot path pode chamar mt5.symbol_info(), mt5.symbol_info_tick(), mt5.copy_ticks_from() etc. O orçamento de IPC por tick é 1x symbol_info_tick (obrigatório) + posições_get (raro) + trade-path (condicional).

### I4 — PositionManager.sync_with_mt5() é a única fonte de truth para posição
register_open() atualiza cache após trade, mas sync_with_mt5() é a autoridade. Nenhum módulo pode fazer positions_get() independente sem atualizar o PositionManager — senão estado diverge. Exceção: ExecutionEngine._close_position() faz positions_get para obter ticket/volume/type antes de close — isso deve ser reconciliado (R8).

### I5 — Point cache nunca pode ser zero em produção
Se _point == 0 ou não inicializado, todos os cálculos em ticks (spread, slippage, SL, TP, velocity, micro_range, breakout) produzem division by zero ou valores infinitos. set_point() DEVE ser chamado em init e re-init. Guard: verificar _point > 0 antes de usar em divisão.

### I6 — Watchdog DEVE ser daemon thread
Se Watchdog rodar em thread non-daemon, o processo Python não termina até a thread do watchdog terminar. O while self._running loop pode impedir shutdown limpo. daemon=True garante que Python mata a thread no exit.

### I7 — Tick logger NÃO vai para console
Logger "tick" tem apenas file handler (system.log). Se um handler de console for adicionado ao tick logger, o output de ~100-200 ticks/segundo inviabiliza o uso do terminal. O tick logger DEVE permanecer file-only.

### I8 — Cooldown entre sinais é obrigatório
StrategyBase._check_cooldown() (signal_cooldown_ms=2000) impede que o strategy emita sinais em bursts. Sem cooldown, um tick de alta velocidade poderia gerar múltiplos sinais no mesmo milissegundo, saturando rate limit e execution.

### I9 — RiskEngine.check_pre_trade() é o gate final
Nenhuma ordem pode ser enviada sem passar por check_pre_trade(). Mesmo que o strategy emitiu signal, mesmo que position_manager diz que não há posição, risk check DEVE ser o último gate antes de order_send.

### I10 — NETTING reversal = BUY/SELL direto, nunca CLOSE+OPEN
Em netting, para reverter posição, envia-se ordem oposta (BUY se SELL, SELL se BUY). MT5 liquida automaticamente. NUNCA enviar CLOSE seguido de OPEN — isso não funciona em netting e pode gerar posição zero seguida de nova posição, perdendo a liquidação.

### I11 — Main loop é single-thread
Todo o fluxo de decisão (tick → metrics → signal → risk → execute) roda na mesma thread. Nenhum módulo pode spawn threads que modificam estado compartilhado (PositionManager, RiskEngine, TickEngine) sem sincronização. O Watchdog é exceção: só lê timestamps e escreve _shutdown_requested/Event.

### I12 — SL e TP são obrigatórios em toda ordem
StrategyBase._create_signal() sempre calcula SL e TP em ticks. Toda ordem enviada via _build_request inclui "sl" e "tp". Em WIN$ mini índice, operar sem SL é inaceitável — risco de loss ilimitado em gap.

---

## 12. Configuração de Settings (Defaults)

| Settings Group | Parâmetro | Default | Usado por |
|---|---|---|---|
| MT5 | login/password/server/path | vazio/0 | MT5Connector.connect |
| Trading | symbol | "WIN$" | Everywhere |
| Trading | lot | 1.0 | ExecutionEngine._build_request |
| Trading | take_profit_ticks | 1000 | StrategyBase._create_signal |
| Trading | stop_loss_ticks | 500 | StrategyBase._create_signal |
| Trading | magic_number | 123456 | ExecutionEngine (order comment) |
| Trading | deviation | 5 | ExecutionEngine (request) |
| Trading | filling_type | 1 | ExecutionEngine (ORDER_TIME_GTC) |
| Tick | buffer_size | 200 | TickEngine deque maxlen |
| Tick | velocity_window_ms | 500 | TickEngine._calc_velocity |
| Tick | micro_range_window | 20 | TickEngine._calc_micro_range |
| Tick | min_ticks_for_signal | 20 | TickEngine.compute_metrics.is_valid |
| Signal | min_velocity | 3.0 | MomentumBurst._check_entry |
| Signal | min_acceleration | 1.5 | MomentumBurst._check_entry |
| Signal | micro_breakout_factor | 1.2 | MomentumBurst._check_entry |
| Signal | max_spread_ticks | 5 | MomentumBurst._check_entry |
| Signal | momentum_reversal_factor | 0.7 | MomentumBurst._check_reversal |
| Signal | signal_cooldown_ms | 2000 | StrategyBase._check_cooldown |
| Signal | min_strength | 0.6 | MomentumBurst._check_entry |
| Risk | max_daily_loss | 500.0 | RiskEngine._check_daily_loss, check_close_signal |
| Risk | max_consecutive_losses | 5 | RiskEngine._check_consecutive_losses |
| Risk | cooldown_after_loss_ms | 3000 | RiskEngine._check_cooldown, _check_consecutive_losses |
| Risk | max_trades_per_minute | 30 | RiskEngine._check_trade_rate |
| Risk | max_spread_ticks | 5 | RiskEngine._check_spread |
| Risk | max_latency_ms | 500.0 | RiskEngine._check_latency |
| Risk | auto_stop_trading | True | RiskEngine._auto_stop_check |
| Risk | circuit_breaker_errors | 3 | RiskEngine.register_execution_error |
| Risk | circuit_breaker_cooldown_ms | 60000 | RiskEngine._check_circuit_breaker |
| Risk | risk_per_trade_pct | 0.0 | V2 placeholder — não lido por nenhum módulo |
| Risk | sizing_mode | "fixed" | V2 placeholder — não lido por nenhum módulo |
| Position | max_open_positions | 1 | **Não verificado — hardcode NETTING** |
| Position | trade_timeout_ms | 30000 | PositionManager.should_close_timeout |
| Position | trailing_stop_enabled | True | PositionManager.check_trailing_stop |
| Position | trailing_stop_ticks | 200 | PositionManager.check_trailing_stop |
| Position | allow_reversal | True | main.py._handle_signal |
| Session | enabled | True | MT5Connector.is_session_allowed |
| Session | allowed_start | 9:05 | MT5Connector.is_session_allowed |
| Session | allowed_end | 17:50 | MT5Connector.is_session_allowed |
| Session | block_open_minutes | 5 | MT5Connector.is_session_allowed |
| Session | block_close_minutes | 5 | MT5Connector.is_session_allowed |
| Session | rollover | 16:55-18:05 | MT5Connector.is_session_allowed |
| System | tick_sleep_ms | 5 | main.py sleep entre ciclos |
| System | reconnect_attempts | 10 | MT5Connector.reconnect |
| System | reconnect_delay_ms | 5000 | MT5Connector.reconnect |
| System | heartbeat_interval_ms | 30000 | MT5Connector.heartbeat |
| System | watchdog_tick_timeout_ms | 10000 | Watchdog.check_tick_timeout |
| System | status_report_interval_sec | 60 | main.py._report_status |

### Settings Órfãos (M8 — REMOVIDOS)
- ~~`TradingSettings.trade_timeout_ms` (5000)~~ — removido
- ~~`TickSettings.velocity_threshold` (3.0)~~ — removido
- ~~`TickSettings.acceleration_threshold` (1.5)~~ — removido
- ~~`SignalSettings.position_side` (None)~~ — removido
- ~~`RiskSettings.max_position_size` (5.0)~~ — removido
- ~~`RiskSettings.risk_per_trade_pct` (2.0)~~ — removido M8, re-adicionado como V2 placeholder (default 0.0 = disabled)
- ~~`SystemSettings.log_level` ("DEBUG")~~ — removido

---

## 13. Estrutura de Diretórios

```
hft_bot/
├── __init__.py        # Package init (vazio)
├── __main__.py        # Entry point: python -m hft_bot
├── main.py            # HFTBot class + main()
├── requirements.txt   # MetaTrader5, numpy
├── config/
│ ├── __init__.py
│ ├── settings.py # 8 dataclasses de configuração (defaults)
│ ├── config_loader.py # JSON → dataclass merge, fallback
│ └── user_config.example.json # Exemplo de config do usuário
├── core/
│   ├── __init__.py            # Re-exports
│   ├── utils.py               # DTOs, enums, CircularBuffer, helpers
│   ├── logger.py              # Log singleton, 8 named loggers
│   ├── mt5_connector.py       # MT5 connection, session, heartbeat
│   ├── tick_engine.py         # Tick processing, metrics
│   ├── signal_engine.py       # StrategyBase ABC + dispatcher
│   ├── execution_engine.py    # Thread-safe order execution
│   ├── position_manager.py    # Position state machine
│   ├── risk_engine.py         # Pre/post-trade risk checks
│   └── watchdog.py            # Dead tick/freeze detection
├── strategies/
│   ├── __init__.py
│   └── momentum_burst.py      # Momentum burst strategy
└── logs/                      # Runtime log files
    ├── system.log
    ├── trades.log
    └── errors.log
```
