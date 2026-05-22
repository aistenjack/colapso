# Relatório Fase 4 — SpeedFilter (causa raiz + correção estrutural)

**Projeto:** `hft_bot/` — WIN HFT scalper  
**Data:** 2026-05-21  
**Regra cumprida:** `speed_threshold`, `neutro_min_strength` e `chop_consistency_threshold` **não foram alterados**.

---

## 1. Causa raiz comprovada

### 1.1 Bug de timestamp (primário em produção MT5)

Em `tick_engine._raw_to_tick`, a fórmula legada:

`time_ms = int(time)*1000 + (time_msc % 1000)`

trata `time_msc` como fração de segundo. No MT5 real, `time_msc` é **epoch em milissegundos**. Isso gera:

- timestamps **não monotônicos** e repetidos
- `elapsed_ms <= 0` em ~**54%** das avaliações (`logs/speed_debug.log` pré-fix)
- `raw_speed` distorcido ou **zero** → estado **LENTO** em massa → `main.py` `continue` bloqueia `MomentumBurst` / REENTRY

**Correção:** usar `time_msc` inteiro quando `time_msc > 1e12`; fallback legado só para ticks de teste antigos.

### 1.2 Métrica estrutural incompatível (secundário, permanece relevante)

O SpeedFilter antigo usava **6 ticks** (`speed_period+1`) e velocidade **líquida** `|mid_end - mid_start| / elapsed`, enquanto o TickEngine mede `velocity_fast` em **500 ms** com **soma de |Δmid|**.

Efeito observado: `velocity_fast ≈ 10` com `speed ≈ 0` (zigzag / span líquido zero).

**Correção:** janela `speed_window_ms=500`, velocidade por **caminho** (path speed), `past = oldest tick na janela`.

### 1.3 Chop com alta path-speed (terciário)

Após corrigir path-speed, zigzag passava como “rápido” sem progresso líquido.

**Correção estrutural (não é tuning de threshold):** `path_efficiency = price_span_pts / path_pts`; se `path_pts >= 4` e eficiência `< 0.35` → bloqueio `chop:path_eff`.

---

## 2. Evidência matemática

| Métrica | Antes (speed_debug.log) | Depois (replay sintético 500 evals) |
|--------|-------------------------|-------------------------------------|
| `elapsed_ms <= 0` | ~54% | **0%** |
| `raw_speed` médio | ~0 (LENTO dominante) | mean **133.7** pts/s (P50 92.6) |
| `allowed` (replay seed=42) | ~0% em sessão real 244/244 LENTO | **43–56%** conforme modo |
| M3 só threshold 4.0 | — | 38.4% vs M2 43.4% (**Δ pequeno**) |

**Replay determinístico M0–M3** (`audit_speed_filter_math.py`):

| Modo | allowed% | elapsed<=0% | Nota |
|------|----------|--------------|------|
| M0 baseline legado | 55.8% | 0%* | *sintético; produção MT5 quebrava M0 |
| M1 epoch TS | 44.2% | 0% | corrige relógio |
| M2 path 500ms | 43.4% | 0% | métrica alinhada TickEngine |
| M3 thresh=4 (comparativo) | 38.4% | 0% | **não deploy** — ganho marginal |

**Conclusão:** abaixar `speed_threshold` sem corrigir timestamp/métrica é **placebo** em produção real.

---

## 3. Arquivos alterados

| Arquivo | Mudança |
|---------|---------|
| `core/tick_engine.py` | `time_ms` MT5; `get_ticks_in_window()` |
| `core/speed_filter.py` | path-speed 500ms; path_chop; debug `reject_class`; warmup |
| `config/settings.py` | `speed_window_ms=500` (sem mudar thresholds) |
| `main.py` | passa `speed_window_ms` ao `SpeedFilter` |
| `tests/test_speed_filter_timestamp.py` | regressão timestamp + path |
| `audit_speed_filter_math.py` | replay M0–M3 |

---

## 4. Diff exato (resumo)

```bash
git diff --stat hft_bot/core/tick_engine.py hft_bot/core/speed_filter.py \
  hft_bot/config/settings.py hft_bot/main.py \
  hft_bot/tests/test_speed_filter_timestamp.py \
  hft_bot/audit_speed_filter_math.py
```

Pontos-chave do diff:

- `_raw_to_tick`: `time_ms = time_msc` se epoch completo
- `SpeedFilter._compute_speed_metrics`: path sum / `elapsed_ms` monotônico + fallback `recv_timestamp`
- `evaluate`: gate `path_chop` por eficiência de caminho
- **Não alterados:** `speed_threshold=5.5`, `neutro_min_strength=0.20`, `chop_consistency_threshold=0.45`

---

## 5. Benchmark antes / depois

| Cenário | Antes | Depois |
|---------|-------|--------|
| Sessão real (amostra) | 244/244 LENTO, 0 signals | esperado: estados mistos, REENTRY executável |
| Testes automatizados | 84/84 (pré) | **92/92** (49 speed + 8 reentry + 27 micro + 8 timestamp) |
| Replay 500 evals allowed | ~0% real | **43.4%** (M2) |
| `elapsed_ms <= 0` | ~54% | **0%** |

**TPM estimado:** de ~0 (bloqueio total) para fator `allowed_pct/100 * baseline_tpm`. Com M2 ~43% allowed, se baseline fosse 6 TPM → **~2.6 TPM** (ordem de grandeza; validar em sessão MT5 com `HFT_SPEED_DEBUG=1`).

**WR esperado:** neutro/positivo — filtro deixa de zerar sinais por bug; chop estrutural preserva selectividade em zigzag. Risco: mais entradas em mercado ruidoso → monitorar WR 1–2 sessões.

---

## 6. Riscos

- Path-speed pode classificar burst zigzag como rápido antes do gate `path_chop` (mitigado por eficiência < 0.35).
- Fallback `recv_timestamp` se MT5 repetir ms no mesmo segundo (raro com epoch fix).
- Mais evals `allowed` → mais trades → validar risk engine / NETTING.

---

## 7. Rollback

1. `git revert` dos commits desta correção, ou
2. Desligar filtro: `speed_filter.enabled=false` em `user_config.json`, ou
3. Hotfix parcial: reverter só `tick_engine._raw_to_tick` (restaura bug mas comportamento “conhecido”).

Reiniciar bot após rollback. Comparar `logs/speed_debug.log` e `sf_reject%` em `system.log`.

---

## 8. Validação operacional recomendada

```powershell
cd d:\NewWorkspace01\projetos\colapso\hft_bot
$env:HFT_SPEED_DEBUG = "1"
..\venv\Scripts\python.exe main.py
```

Verificar em `logs/speed_debug.log`:

- `elapsed_ms` > 0 na quase totalidade
- `velocity_fast` correlacionado com `raw_speed` / `path_pts`
- `reject_class` distribuído (não 100% `lento_speed` por speed=0)
- REENTRY / `MomentumBurst` executando após `allowed=True`

---

## 9. Próximo passo (somente após validação em conta demo)

Se métrica estiver correta em 1 sessão completa e `elapsed_ms<=0` ~0%, **aí sim** calibrar `speed_threshold` com dados pós-fix — nunca antes.
