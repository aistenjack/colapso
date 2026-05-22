# Colapso — HFT Micro-Scalper para WIN (B3)

Bot de micro-scalping tick-a-tick para MetaTrader 5, focado no mini índice brasileiro (WIN), conta NETTING na Clear DEMO. Single-strategy, single-thread, zero IA/ML.

**Versão atual:** V12.14 — MicroStructureEngine (7-score probabilistic reentry)

---

## Sumário

- [Visão Geral](#visão-geral)
- [Arquitetura](#arquitetura)
- [Fluxo do Main Loop](#fluxo-do-main-loop)
- [Estrutura do Projeto](#estrutura-do-projeto)
- [Módulos Core](#módulos-core)
- [Estratégia — MomentumBurst](#estratégia--momentumburst)
- [SpeedFilter](#speedfilter)
- [MicroStructureEngine (Reentry V12.14)](#microstructureengine-reentry-v1214)
- [Configuração](#configuração)
- [Como Executar](#como-executar)
- [Testes](#testes)
- [Métricas Históricas](#métricas-históricas)
- [Roadmap](#roadmap)
- [Documentação](#documentação)
- [Segurança](#segurança)
- [Licença](#licença)

---

## Visão Geral

Prioridades do sistema (em ordem):

1. Baixa latência
2. Estabilidade de execução
3. Proteção de risco
4. Thread safety
5. Suporte NETTING (posição líquida única, reversão direta)
6. Simplicidade

**Explicitamente fora do escopo:** IA, ML, RSI/MACD, velas, dashboard web, multi-estratégia, DB, pandas, otimizador automático.

| Dimensão | Status |
|----------|--------|
| Instrumento | WINM26 (mini índice B3) |
| Conta | Clear DEMO, NETTING |
| Lote | 1.0 (fixo) |
| Magic | 123456 |
| Versão | V12.14 |
| Testes | 92/92 passando |
| Validação | Aguardando 50+ trades DEMO pós-V12.14 |

---

## Arquitetura

```
main.py (HFTBot) — orquestrador, single-thread principal
│
├─ MT5Connector ──── connect/reconnect/heartbeat/get_tick/session/account_snapshot
├─ TickEngine ────── process_tick → compute_metrics (numpy, arrays <200 elem)
├─ SpeedFilter ───── regime filter (LENTO/NEUTRO/ACELERANDO/FORTE/EXAUSTÃO)
├─ SignalEngine ──── dispatcher → StrategyBase.evaluate()
│   └─ MomentumBurst ── entry/reversal/close + MicroStructureEngine reentry
├─ RiskEngine ─────── 7 pre-trade gates + circuit breaker + latency trimmed mean
├─ ExecutionEngine ── order_send com _lock, requote retry (3x), slippage
├─ PositionManager ── sync_with_mt5, trailing broker + trailing virtual, loss exits
├─ Watchdog ───────── daemon thread, dead tick/freeze detection, threading.Event
└─ Log ────────────── 8 named loggers, console=INFO, file=DEBUG, 5MB rotation
```

### Thread Model

| Thread | Função | Daemon |
|--------|--------|--------|
| Main | Loop: get_tick → process → metrics → signal → execute | Não |
| Watchdog | Monitora dead tick e freeze | Sim |

---

## Fluxo do Main Loop

```
Tick MT5
  │
  ├─ Heartbeat / reconexão MT5 (cold path, 30s)
  ├─ Filtro de sessão (09:05–17:50, bloqueio abertura/rollover)
  ├─ TickEngine.process_tick → métricas
  ├─ PositionManager: timeout, PnL, trailing virtual, trailing broker
  ├─ SpeedFilter ─── bloqueado? → continue (pula estratégia)
  ├─ SignalEngine → MomentumBurst.evaluate()
  │     ├─ NONE → continue
  │     ├─ BUY/SELL → RiskEngine.check_pre_trade (7 gates)
  │     │     └─ ok → ExecutionEngine.execute_signal_async
  │     └─ CLOSE → close_position (urgente, bypass cooldown)
  └─ Sleep 5ms (idle)
```

---

## Estrutura do Projeto

```
colapso/
├── hft_bot/                    # Aplicação principal
│   ├── main.py                 # Orquestrador HFTBot (~606 linhas)
│   ├── __init__.py
│   ├── __main__.py             # Entry point: python -m hft_bot
│   ├── core/
│   │   ├── mt5_connector.py    # Conexão MT5, NETTING, heartbeat, sessão
│   │   ├── tick_engine.py      # Buffer de ticks, velocity, acceleration, micro_range
│   │   ├── signal_engine.py    # Dispatcher + StrategyBase ABC
│   │   ├── execution_engine.py # order_send com lock, requote, slippage, stops
│   │   ├── position_manager.py # Estado de posição, trailing broker + virtual, loss exits
│   │   ├── risk_engine.py      # Pre/post-trade, rate limit, latency, circuit breaker
│   │   ├── speed_filter.py     # Filtro de regime de velocidade/força
│   │   ├── micro_structure.py  # MicroStructureEngine — reentry V12.14
│   │   ├── watchdog.py         # Dead tick, freeze, shutdown via Event
│   │   ├── utils.py            # DTOs, enums, CircularBuffer
│   │   └── logger.py           # 8 loggers, rotação 5MB
│   ├── strategies/
│   │   └── momentum_burst.py   # MomentumBurst — estratégia única
│   ├── config/
│   │   ├── settings.py         # 11 dataclasses de configuração
│   │   ├── config_loader.py    # JSON → dataclass merge, BOM-safe
│   │   └── user_config.example.json
│   ├── tests/
│   │   ├── test_speed_filter.py              # 49 testes
│   │   ├── test_speed_filter_timestamp.py    # 8 testes (regressão timestamp)
│   │   ├── test_reentry_gate.py              # 8 testes
│   │   ├── test_micro_structure_reentry.py   # 17 testes
│   │   └── bench_micro_structure.py          # Benchmark performance
│   ├── audit_speed_filter_math.py            # Replay M0–M3 determinístico
│   ├── audit_mt5_deals.py                    # Scripts de auditoria pós-sessão
│   ├── requirements.txt                      # MetaTrader5, numpy
│   └── *.md                                   # Documentação de governança
├── requirements.txt                           # Deps amplas (não reflete só o bot)
├── venv/                                      # Python 3.14 (não versionado)
└── .gitignore
```

---

## Módulos Core

| Módulo | Arquivo | Responsabilidade |
|--------|---------|------------------|
| MT5Connector | `core/mt5_connector.py` | Conexão, NETTING validation, reconnect, heartbeat, sessão, tick, account_snapshot |
| TickEngine | `core/tick_engine.py` | Buffer circular, velocity signed, velocity_fast/very_fast, acceleration, micro_range, displacement, trend_bars |
| SignalEngine | `core/signal_engine.py` | StrategyBase ABC + dispatcher |
| ExecutionEngine | `core/execution_engine.py` | `order_send` com lock, requote retry (3x), slippage, validação de stops com auto-detecção broker |
| PositionManager | `core/position_manager.py` | Estado de posição, trailing broker + **trailing virtual**, loss exits, deactivation gate |
| RiskEngine | `core/risk_engine.py` | 7 pre-trade gates + circuit breaker, rate limit, cooldown, spread, latency (trimmed mean) |
| SpeedFilter | `core/speed_filter.py` | 5 estados de regime, EMA-smoothed speed, composite strength, adaptive threshold, chop gate, path efficiency |
| MicroStructureEngine | `core/micro_structure.py` | 7-score probabilistic reentry, MicroCandle, anti-echo, adaptive threshold |
| Watchdog | `core/watchdog.py` | Dead tick (20s grace), freeze detection, shutdown via `threading.Event` |
| Utils | `core/utils.py` | DTOs (TickData, Signal, TradeResult, TickMetrics), enums, CircularBuffer |
| Logger | `core/logger.py` | 8 named loggers, console=INFO, file=DEBUG, RotatingFileHandler 5MB/5 backups |

---

## Estratégia — MomentumBurst

**Arquivo:** `strategies/momentum_burst.py` (~422 linhas)

### Entrada HFT

- Velocidade adaptativa (3 thresholds por `avg_velocity`)
- Displacement ≥ 4.0 pts
- Micro_range ≥ 2.0 pts
- Spread ≤ 5 ticks
- Cooldown 200ms entre sinais
- `trend_bars` e `acceleration` como boosters de força (não filtros)

### Saídas

- **loss_exit**: adverso > 18 pts (urgente, bypass cooldown)
- **loss_max**: adverso > 35 pts (urgente)
- **Trailing virtual**: offset 8 pts, ativação 6 pts (sem broker modify)
- **Trailing broker**: offset 200 pts (compatível com stops_level)

### Reversão NETTING

- `|vel_fast| ≥ adaptive_threshold × 1.2`
- `|displacement| ≥ loss_min_pts (18)` — NOT `reversal_min_disp` (óbsoleto no fluxo real)
- `min_hold_seconds = 5.0`
- `post_close_cooldown_s = 0.3`

---

## SpeedFilter

**Arquivo:** `core/speed_filter.py`

Gate de regime antes da estratégia. 5 estados:

| Estado | Condição | Ação |
|--------|----------|------|
| LENTO | speed < threshold × 0.5 | BLOQUEADO |
| NEUTRO | speed ≥ 0.5×thresh, strength ≥ 0.20 | PERMITIDO |
| ACELERANDO | speed ≥ 0.65×thresh, consist > 0.55 | PERMITIDO |
| FORTE | speed ≥ thresh, strength > 0.45 | PERMITIDO |
| EXAUSTÃO | speed > 1.3×thresh, strength < 0.30 | BLOQUEADO |

**Chop sub-check:** consistency < 0.45 E speed < 0.8×threshold → LENTO

**Path efficiency (V12.14 fix):** `price_span / path < 0.35` com `path ≥ 4` → bloqueio `chop:path_eff`. Resolve zigzag com alta path-speed mas zero progresso líquido.

**Adaptive threshold:** EMA 70/30 com multiplicadores por micro_range e velocity.

### Correção Estrutural (Fase 4)

Bug de causa raiz: `time_ms = time*1000 + time_msc%1000` tratava `time_msc` MT5 como sub-segundo, mas é epoch ms completo → 54% `elapsed_ms ≤ 0` → LENTO em massa.

**Correções aplicadas (sem alterar thresholds):**

1. `time_msc` inteiro quando `> 1e12`; fallback legado para testes antigos
2. Janela `speed_window_ms=500` (alinhada ao TickEngine), path-speed
3. Path efficiency gate para chop

| Métrica | Antes | Depois |
|---------|-------|--------|
| `elapsed_ms ≤ 0` | ~54% | ~0% |
| `raw_speed` médio | ~0 | 133.7 pts/s |
| Estados em sessão real | 244/244 LENTO | Misto (NEUTRO/ACEL/FORTE) |
| Signals / REENTRY | 0 | Executável |

---

## MicroStructureEngine (Reentry V12.14)

**Arquivo:** `core/micro_structure.py` (552 linhas)

Scoring probabilístico de 7 componentes para reentrada após loss na mesma direção:

| Componente | Peso | Descrição |
|------------|------|-----------|
| retrace_score | 0.30 | Pullback saudável (candle na direção oposta, body_ratio > 0.3) |
| breakout_score | 0.20 | Rompimento real (candle breaking previous high/low) |
| structure_score | 0.15 | 2/3 candles alinhados na direção do sinal |
| consistency_score | 0.15 | dir_align×0.6 + vel_ratio×0.2 + disp_score×0.2 |
| velocity_score | 0.10 | vel_fast vs speed_threshold do SpeedFilter |
| chop_penalty | -0.10 max | LENTO/EXAUSTÃO no SpeedFilter |
| spread_penalty | -0.05 max | Spread > max_spread |

**Score final:** `raw = retrace×0.30 + breakout×0.20 + structure×0.15 + consistency×0.15 + velocity×0.10 - chop_pen - spread_pen`

**Anti-echo hard gate:** preço < 3 pts do último close + sem retrace (>0.3) + sem breakout (>0.5) + sem consistência (>0.4) → score ×0.1

**Adaptive threshold:**

| Frequência | Ajuste | Efeito |
|------------|--------|--------|
| < 1.5 trades/min | threshold −0.15 (min 0.30) | Relaxa em baixa freq |
| > 7.5 trades/min | threshold +0.15 (max 0.80) | Aperta em alta freq |
| else | threshold_base = 0.55 | Default |

**MicroCandle:** 15 ticks/candle (~150–300ms em WINM26), ring buffer 3 candles.

---

## Configuração

### Defaults em `config/settings.py` (11 dataclasses)

| Grupo | Principais Parâmetros |
|-------|-----------------------|
| MT5Settings | login, password, server, path, timeout |
| TradingSettings | symbol=WINM26, lot=1.0, hft_sl=4000, hft_tp=0 |
| TickSettings | buffer_size=200, velocity_window_ms=1000, micro_range_window=30 |
| SignalSettings | hft_min_velocity=6.0, hft_min_displacement=4.0, hft_max_spread=5, hft_cooldown_ms=200 |
| HFTSettings | enabled=True, idle_timeout_ms=3000, adaptive thresholds (5/7/10) |
| RiskSettings | max_daily_loss=500, max_consecutive_losses=8, max_trades_per_minute=30 |
| PositionSettings | loss_min_pts=18, loss_max_pts=35, trailing_virtual_offset=8, trailing_activation=6 |
| SessionSettings | 09:05–17:50, bloqueio abertura/rollover |
| SpeedFilterSettings | speed_threshold=5.5, speed_period=5, strength_exhaustion=0.30, chop_consistency=0.45, speed_window_ms=500 |
| ReentrySettings | threshold_base=0.55, candle_ticks=15, echo_proximity=3.0, freq_target=3.0 |
| SystemSettings | loop_sleep_ms=5, log_level, etc. |

### Override via JSON

```bash
# Criar config local (NÃO commitar com credenciais reais)
cp hft_bot/config/user_config.example.json hft_bot/config/user_config.json
# Editar com suas credenciais MT5
```

Seções suportadas pelo loader: `account`, `trading`, `risk`, `execution`, `strategy`, `position`, `session`, `system`, `hft`.

> **Nota:** `speed_filter` e `reentry` não têm seção no loader JSON — só via `settings.py` ou estendendo o loader.

---

## Como Executar

### Pré-requisitos

- Python 3.14+
- MetaTrader 5 instalado e logado
- Conta NETTING (Clear DEMO ou real)
- Símbolo WINM26 disponível

### Instalação

```bash
cd projetos/colapso
python -m venv venv
# Windows:
venv\Scripts\activate
pip install -r hft_bot/requirements.txt
```

### Execução

```bash
# Da pasta hft_bot
cd hft_bot
python main.py

# Ou como pacote (a partir do pai)
cd projetos/colapso
python -m hft_bot
```

### Debug do SpeedFilter

```powershell
$env:HFT_SPEED_DEBUG = "1"
cd hft_bot
python main.py
# Verificar: elapsed_ms > 0, reject_class diverso, REENTRY rodando
```

---

## Testes

| Suite | Arquivo | Testes | Versão |
|-------|---------|--------|--------|
| SpeedFilter | `tests/test_speed_filter.py` | 49 | V12.10 |
| SpeedFilter Timestamp | `tests/test_speed_filter_timestamp.py` | 8 | V12.14 fix |
| Reentry Gate | `tests/test_reentry_gate.py` | 8 | V12.13 |
| Micro Structure | `tests/test_micro_structure_reentry.py` | 17 | V12.14 |
| Benchmark | `tests/bench_micro_structure.py` | perf | V12.14 |
| **Total** | | **82+** | |

### Executar testes

```bash
cd hft_bot
python tests/test_speed_filter.py
python tests/test_speed_filter_timestamp.py
python tests/test_reentry_gate.py
python tests/test_micro_structure_reentry.py
```

### Checklist de Regressão (pré-deploy)

1. Todos os testes passando (82+)
2. Settings compilam: `python -c "from config.settings import Settings; s=Settings(); print(s.reentry)"`
3. Imports OK: MomentumBurst, MicroStructureEngine, RiskEngine, HFTBot
4. `set_position_side` sem bug
5. `notify_close_pnl` wired em ambos close paths
6. `on_tick` wired no main loop
7. Reentry diagnostics em HFT metrics

---

## Métricas Históricas

| Versão | Data | Duração | Trades | WR | PnL (pts) | R:R | TPM | sf_reject | Mudança Principal |
|--------|------|---------|--------|-----|-----------|-----|-----|-----------|-------------------|
| V12.7 | 18/05 | ~60min | 155 | 72.9% | +35 | 0.37 | 2.63 | 97% | Baseline |
| V12.8 | 18/05 | ~55min | 177 | 62.7% | -193 | 0.39 | 3.22 | — | — |
| V12.10 | 19/05 | ~15min | 210 | 68.6% | -27 | 0.39 | ~14 | 91% | SpeedFilter rewrite |
| V12.11 | 19/05 | ~44min | 201 | 61.7% | +99 | 0.62 | 4.57 | 91.5% | loss_min=18, trailing_act=6, reversal_disp=9 |
| V12.12 | 19/05 | ~14min | 109 | 60.6% | -12 | 0.54 | 6.99 | 88-90% | Latency trimmed mean, loss_exit urgent |
| V12.13 | — | — | — | — | — | — | — | — | Reentry displacement gate, bug fix |
| V12.14 | — | — | — | — | — | — | — | — | MicroStructureEngine 7-score, anti-echo, adaptive threshold |

**Gap principal:** R:R consistentemente baixo (~0.37–0.62). Ganhos médios ~4 pts vs perdas ~8-10 pts. V12.11 foi a melhor sessão (R:R=0.62, PnL=+99).

**SpeedFilter fix (Fase 4):** eliminou bloqueio 244/244 LENTO causado por bug de timestamp. Esperado: mais trades, estados mistos, REENTRY funcional.

---

## Roadmap

### V1–V4 — Concluído

Todos os módulos core implementados, M1-M8 bugs corrigidos, DEMO-ready.

### V12.7–V12.14 — Evolução Contínua

- V12.10: SpeedFilter rewrite + calibração
- V12.11: Trailing virtual, loss_min=18, reversal filter
- V12.12: Latency trimmed mean, loss_exit urgent
- V12.13: Reentry displacement gate, set_position_side bug fix
- V12.14: MicroStructureEngine (7-score reentry), anti-echo, adaptive threshold
- V12.14 Fase 4: Correção estrutural SpeedFilter (timestamp bug, path-speed, path efficiency)

### V2 — Candidatos Pós-DEMO

1. `_calc_velocity` sem lista temporária
2. `CircularBuffer.__getitem__` direto
3. numpy → manual math em arrays pequenos
4. Risk sizing por % risco (risk_per_trade_pct)
5. Trailing min_step adjustment

### NÃO Implementar

- IA / machine learning
- Dashboards / GUI / web API
- Multi-strategy framework
- Databases / pandas / TensorFlow
- Otimizador automático

---

## Documentação

| Arquivo | Conteúdo |
|---------|----------|
| `ARCHITECTURE.md` | Princípios, regras de performance/execução/netting/risco |
| `STATE.md` | Estado atual detalhado (~1769 linhas), mudanças V12.14, invariants |
| `HANDOFF.md` | Arquitetura, inventário IPC, thread model, 11 invariants |
| `TEST_MATRIX.md` | 82+ testes, métricas por versão, checklist regressão |
| `ROADMAP.md` | V1-V4, V2 candidatos, DO NOT IMPLEMENT |
| `RELATORIO_SPEED_FILTER_FASE4.md` | Causa raiz SpeedFilter, evidência, replay M0-M3, correção |
| `Leia_primeiro.md` | Regras de ouro antes de implementar |

---

## Segurança

- `user_config.json` (credenciais MT5) está no `.gitignore` — **NÃO** commitar
- `user_config.example.json` contém credenciais de exemplo em texto claro — usar apenas como template
- Preferir variáveis de ambiente ou arquivo local ignorado pelo git para credenciais reais
- GitHub PAT foi usado apenas para push inicial — rotacionar se necessário

---

## Licença

Projeto privado. Todos os direitos reservados.
