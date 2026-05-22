"""
Auditoria matemática offline do SpeedFilter — sem alterar config.
Replica fórmulas de core/speed_filter.py e gera estatísticas + contrafactual.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_project = Path(__file__).resolve().parent
sys.path.insert(0, str(_project))

from config.settings import Settings
from core.speed_filter import SpeedFilter, SpeedState
from core.tick_engine import TickEngine
from core.utils import TickData


@dataclass
class RawTick:
    bid: float
    ask: float
    time: int = 0
    time_msc: int = 0
    last: float = 0.0
    volume: int = 0


def make_tick(bid: float, ask: float, time_ms: int, legacy: bool = False) -> RawTick:
    """legacy=True simula bug MT5 antigo (time*1000 + msc%1000)."""
    if legacy:
        t_sec = time_ms // 1000
        msc = time_ms % 1000
        return RawTick(bid=bid, ask=ask, time=t_sec, time_msc=msc)
    return RawTick(bid=bid, ask=ask, time=time_ms // 1000, time_msc=time_ms)


def legacy_raw_speed(te: TickEngine, period: int, point: float) -> tuple[float, int, float]:
    ticks = te.get_recent_ticks(period + 1)
    if len(ticks) < period + 1:
        return 0.0, 0, 0.0
    current, past = ticks[-1], ticks[0]
    span = abs(current.mid - past.mid) / point if point > 0 else 0.0
    elapsed_ms = current.time_ms - past.time_ms
    elapsed_s = max(0.001, elapsed_ms / 1000.0)
    return (span / elapsed_s if elapsed_s > 0 else 0.0), elapsed_ms, span


def evaluate_instrumented(
    sf: SpeedFilter,
    te: TickEngine,
    tick: TickData,
    metrics,
    debug_rows: list,
) -> None:
    """Replica evaluate() expondo variáveis intermediárias."""
    from core.speed_filter import SpeedResult
    from core.utils import TickMetrics

    period = sf._speed_period
    ticks = te.get_recent_ticks(period + 1)
    n = len(ticks)
    point = te.point if te.point > 0 else 1.0

    if n < period + 1:
        debug_rows.append({"note": "warmup", "n_ticks": n, "allowed": True})
        sf.evaluate(te, tick, metrics)
        return

    current = ticks[-1]
    past = ticks[0]
    price_start = past.mid
    price_end = current.mid
    price_span = abs(price_end - price_start)
    elapsed_ms = current.time_ms - past.time_ms
    elapsed_s = max(0.001, elapsed_ms / 1000.0)
    raw_speed = (price_span / point) / elapsed_s

    # strength components (mirror speed_filter.py)
    recent_window = te.get_recent_ticks(sf._micro_range_window)
    if len(recent_window) >= 2:
        highs = [t.ask for t in recent_window]
        lows = [t.bid for t in recent_window]
        true_range_pts = (max(highs) - min(lows)) / point
        mid_prices = [t.mid for t in recent_window]
    else:
        true_range_pts = metrics.micro_range if metrics.micro_range > 0 else 1.0
        mid_prices = [past.mid, current.mid]

    same_dir = total_dir = 0
    for i in range(1, len(mid_prices)):
        d = mid_prices[i] - mid_prices[i - 1]
        if d != 0.0:
            total_dir += 1
            if (d > 0 and current.mid >= past.mid) or (d < 0 and current.mid < past.mid):
                same_dir += 1
    dir_cons = same_dir / total_dir if total_dir > 0 else 0.0

    direction = current.mid - past.mid
    if true_range_pts > 0 and len(recent_window) >= 2:
        if direction >= 0:
            directional_range = max(1.0, (max(highs) - past.mid) / point)
        else:
            directional_range = max(1.0, (past.mid - min(lows)) / point)
        range_strength = min(abs(price_span / point) / directional_range, 2.0)
    else:
        range_strength = 0.0

    accel = metrics.acceleration
    norm_accel = min(max(accel / 10.0, 0.0), 1.0)
    strength = min(
        range_strength * 0.4 + dir_cons * 0.35 + norm_accel * 0.25,
        1.5,
    )

    base = sf._speed_threshold
    spread = tick.spread
    if spread > 8.0:
        spread_mult = 1.25
    elif spread > 5.0:
        spread_mult = 1.10
    else:
        spread_mult = 1.0

    mr = metrics.micro_range
    if mr < 3.0:
        range_mult = 1.30
    elif mr < 6.0:
        range_mult = 1.10
    elif mr > 20.0:
        range_mult = 0.80
    elif mr > 12.0:
        range_mult = 0.90
    else:
        range_mult = 1.0

    avg_vel = abs(metrics.avg_velocity)
    if avg_vel < 3.0:
        vel_mult = 1.15
    elif avg_vel > 15.0:
        vel_mult = 0.85
    else:
        vel_mult = 1.0

    adaptive_raw = base * spread_mult * range_mult * vel_mult

    result = sf.evaluate(te, tick, metrics)

    debug_rows.append({
        "price_start": price_start,
        "price_end": price_end,
        "price_span": price_span,
        "price_span_pts": price_span / point,
        "elapsed_ms": elapsed_ms,
        "elapsed_s": elapsed_s,
        "raw_speed": raw_speed,
        "ema_speed": result.speed,
        "adaptive_threshold": result.adaptive_threshold,
        "adaptive_raw": adaptive_raw,
        "speed_threshold_base": base,
        "spread": spread,
        "spread_mult": spread_mult,
        "micro_range": mr,
        "range_mult": range_mult,
        "avg_velocity": metrics.avg_velocity,
        "vel_mult": vel_mult,
        "directional_consistency": dir_cons,
        "accel": accel,
        "strength": strength,
        "state": result.state.name,
        "allowed": result.allowed,
        "block_reason": result.blocked_reason,
        "n_ticks_window": n,
        "lento_gate": adaptive_raw * 0.5,
        "neutro_gate_speed": adaptive_raw * 0.5,
    })


def simulate_tick_patterns():
    """FASE 2: impacto de speed_period em ticks sintéticos WIN-like."""
    settings = Settings()
    point = 1.0
    te = TickEngine(settings)
    te.set_point(point)
    sf = SpeedFilter(
        speed_period=settings.speed_filter.speed_period,
        speed_threshold=settings.speed_filter.speed_threshold,
        strength_exhaustion=settings.speed_filter.strength_exhaustion,
        micro_range_window=settings.speed_filter.micro_range_window,
        ema_alpha=settings.speed_filter.ema_alpha,
        speed_clamp=settings.speed_filter.speed_clamp,
        chop_consistency_threshold=settings.speed_filter.chop_consistency_threshold,
        chop_speed_cap_factor=settings.speed_filter.chop_speed_cap_factor,
        neutro_min_strength=settings.speed_filter.neutro_min_strength,
    )

    scenarios = []

    def run_scenario(name: str, mids: list[float], dt_ms: int = 50):
        te.reset()
        sf._smoothed_speed = 0.0
        sf._has_previous_speed = False
        sf._prev_adaptive_threshold = sf._speed_threshold
        last = None
        t0 = 1_700_000_000_000
        for i, mid in enumerate(mids):
            bid = mid - 2.5
            ask = mid + 2.5
            raw = make_tick(bid, ask, t0 + i * dt_ms)
            tick = te.process_tick(raw)
            if tick is None:
                continue
            metrics = te.compute_metrics()
            if not metrics.is_valid:
                continue
            r = sf.evaluate(te, tick, metrics)
            last = r
        if last is None:
            scenarios.append((name, 0.0, 0.0, False, "N/A", "no_valid_metrics"))
        else:
            scenarios.append((name, last.speed, last.adaptive_threshold, last.allowed, last.state.name, last.blocked_reason))

    # WIN move 5 pts in N ticks
    for n in (3, 5, 8, 10):
        mids = [178400.0] * (n - 1) + [178405.0]
        run_scenario(f"move_5pts_in_{n}_ticks_50ms", mids, 50)

    # flat 20 ticks
    run_scenario("flat_20_ticks", [178400.0] * 20, 5)

    # oscillation +5 -5 (net flat span)
    osc = []
    p = 178400.0
    for _ in range(10):
        p += 5
        osc.append(p)
        p -= 5
        osc.append(p)
    run_scenario("zigzag_5pt_20_ticks", osc, 30)

    return scenarios


def parse_speed_filter_logs(log_path: Path, t_start: str, t_end: str) -> list[dict]:
    pat = re.compile(
        r"estado=(\w+) speed=([\d.]+) strength=([\d.]+) "
        r"dir_consistency=([\d.]+) accel=([-\d.]+) blocked=(.*)$"
    )
    rows = []
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "[SPEED FILTER]" not in line or "estado=" not in line:
            continue
        ts = line[:23]
        if ts < t_start or ts > t_end:
            continue
        m = pat.search(line)
        if not m:
            continue
        rows.append({
            "ts": ts,
            "state": m.group(1),
            "speed": float(m.group(2)),
            "strength": float(m.group(3)),
            "dir_consistency": float(m.group(4)),
            "accel": float(m.group(5)),
            "blocked": m.group(6).strip(),
        })
    return rows


def percentile(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    k = (len(s) - 1) * p / 100.0
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def histogram_text(vals: list[float], bins: int = 8) -> str:
    if not vals:
        return "  (vazio)"
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return f"  all={lo:.4f} n={len(vals)}"
    step = (hi - lo) / bins or 1.0
    counts = [0] * bins
    for v in vals:
        i = min(int((v - lo) / step), bins - 1)
        counts[i] += 1
    lines = []
    for i, c in enumerate(counts):
        b0 = lo + i * step
        b1 = lo + (i + 1) * step
        bar = "#" * max(1, int(40 * c / max(counts)))
        lines.append(f"  [{b0:6.2f}-{b1:6.2f}): {c:5d} {bar}")
    return "\n".join(lines)


def counterfactual_from_logs(rows: list[dict], scenarios: dict) -> list[dict]:
    """Reclassifica estados com thresholds alternativos (aproximação conservadora)."""
    out = []
    for name, cfg in scenarios.items():
        base = cfg["speed_threshold"]
        neutro_str = cfg.get("neutro_min_strength", 0.20)
        chop = cfg.get("chop_consistency_threshold", 0.45)
        allowed = blocked_lento = 0
        for r in rows:
            speed = r["speed"]
            strength = r["strength"]
            dc = r["dir_consistency"]
            accel = r["accel"]
            # adaptive ~ média observada 6.5 com base 5.5 -> escala linear
            adapt = base * (r.get("adaptive_est", 6.5) / 5.5) if "adaptive_est" in r else base * 1.18
            ok = True
            if speed < adapt * 0.5:
                ok = False
                blocked_lento += 1
            elif speed >= adapt and strength > 0.45 and dc > 0.5 and accel > 0:
                pass
            elif speed >= adapt * 0.65 and dc > 0.55:
                if dc < chop and speed < adapt * 0.8:
                    ok = False
                    blocked_lento += 1
            elif speed >= adapt * 0.5 and accel > 0 and dc >= chop and strength >= neutro_str:
                pass
            else:
                ok = False
                blocked_lento += 1
            if ok:
                allowed += 1
        n = len(rows)
        out.append({
            "scenario": name,
            "allowed_pct": 100.0 * allowed / n if n else 0,
            "blocked_pct": 100.0 * blocked_lento / n if n else 0,
            "est_tpm_factor": allowed / n * 6.0 if n else 0,
        })
    return out


def replay_m0_m3(n_evals: int = 500) -> list[dict]:
    """Replay determinístico: M0 legado, M1 epoch, M2 métrica nova, M3 thresh 4 (só comparativo)."""
    import random
    random.seed(42)
    settings = Settings()
    point = 1.0
    base_cfg = dict(
        speed_period=settings.speed_filter.speed_period,
        strength_exhaustion=settings.speed_filter.strength_exhaustion,
        micro_range_window=settings.speed_filter.micro_range_window,
        ema_alpha=settings.speed_filter.ema_alpha,
        speed_clamp=settings.speed_filter.speed_clamp,
        chop_consistency_threshold=settings.speed_filter.chop_consistency_threshold,
        chop_speed_cap_factor=settings.speed_filter.chop_speed_cap_factor,
        neutro_min_strength=settings.speed_filter.neutro_min_strength,
        speed_window_ms=settings.speed_filter.speed_window_ms,
    )

    def run_mode(name: str, legacy_ts: bool, thresh: float) -> dict:
        te = TickEngine(settings)
        te.set_point(point)
        sf = SpeedFilter(speed_threshold=thresh, **base_cfg)
        t = 1_700_000_000_000
        price = 178400.0
        allowed = lento = elapsed_nonpos = span_zero = 0
        evals = 0
        for _ in range(800):
            r = random.random()
            if r < 0.7:
                pass
            elif r < 0.9:
                price += random.choice([-5, 0, 5])
            else:
                price += random.choice([-15, 15])
            t += random.randint(3, 25)
            tick = te.process_tick(make_tick(price - 2.5, price + 2.5, t, legacy=legacy_ts))
            if tick is None:
                continue
            metrics = te.compute_metrics()
            if not metrics.is_valid:
                continue
            if name == "M0":
                rs, em, span = legacy_raw_speed(te, sf._speed_period, point)
                if em <= 0:
                    elapsed_nonpos += 1
                if span == 0:
                    span_zero += 1
                adapt = sf._speed_threshold * 1.18
                ok = rs >= adapt * 0.5
            else:
                sm = sf._compute_speed_metrics(te, metrics, point)
                if sm["elapsed_ms"] <= 0:
                    elapsed_nonpos += 1
                if sm["price_span_pts"] == 0 and sm["path_pts"] == 0:
                    span_zero += 1
                res = sf.evaluate(te, tick, metrics)
                ok = res.allowed
                if res.state == SpeedState.LENTO:
                    lento += 1
            evals += 1
            if ok:
                allowed += 1
            if evals >= n_evals:
                break
        return {
            "mode": name,
            "evals": evals,
            "allowed_pct": 100.0 * allowed / evals if evals else 0,
            "lento_pct": 100.0 * lento / evals if evals else 0,
            "elapsed_nonpos_pct": 100.0 * elapsed_nonpos / evals if evals else 0,
            "span_zero_pct": 100.0 * span_zero / evals if evals else 0,
            "est_tpm_factor": allowed / evals * 6.0 if evals else 0,
        }

    return [
        run_mode("M0_baseline_legado", legacy_ts=True, thresh=5.5),
        run_mode("M1_epoch_ts", legacy_ts=False, thresh=5.5),
        run_mode("M2_path_window_500ms", legacy_ts=False, thresh=5.5),
        run_mode("M3_thresh4_comparativo", legacy_ts=False, thresh=4.0),
    ]


def main():
    log_path = _project / "logs" / "system.log"
    t_start = "2026-05-21 13:11:08"
    t_end = "2026-05-21 13:11:24"

    print("=" * 70)
    print("FASE 2 — Simulação speed_period (sintético WIN, point=1)")
    print("=" * 70)
    for row in simulate_tick_patterns():
        print(f"  {row[0]:30s} speed={row[1]:6.1f} adapt={row[2]:5.2f} allowed={row[3]} state={row[4]} reason={row[5]}")

    print("\n" + "=" * 70)
    print(f"FASE 4 - Logs reais {t_start} -> {t_end}")
    print("=" * 70)
    rows = parse_speed_filter_logs(log_path, t_start, t_end)
    print(f"  Amostras [SPEED FILTER] no intervalo: {len(rows)}")
    if not rows:
        print("  (sem amostras — logs só a cada 100 ciclos; ver speed_debug.log após instrumentação)")
        t_start = "2026-05-21 12:52:00"
        t_end = "2026-05-21 13:00:00"
        rows = parse_speed_filter_logs(log_path, t_start, t_end)
        print(f"  Fallback 12:52-13:00: {len(rows)} amostras")

    speeds = [r["speed"] for r in rows]
    strengths = [r["strength"] for r in rows]
    adap_est = 6.5
    for r in rows:
        r["adaptive_est"] = adap_est

    if speeds:
        print("\n  speed (log amostrado):")
        print(f"    mean={sum(speeds)/len(speeds):.3f} med={percentile(speeds,50):.3f}")
        print(f"    P75={percentile(speeds,75):.3f} P90={percentile(speeds,90):.3f}")
        print(f"    P95={percentile(speeds,95):.3f} P99={percentile(speeds,99):.3f}")
        print(f"    min={min(speeds):.3f} max={max(speeds):.3f}")
        print(histogram_text(speeds))

        states = {}
        for r in rows:
            states[r["state"]] = states.get(r["state"], 0) + 1
        print(f"\n  estados: {states}")
        lento_pct = 100.0 * states.get("LENTO", 0) / len(rows)
        print(f"  LENTO: {lento_pct:.1f}%")

    print("\n" + "=" * 70)
    print("FASE 5 — Contrafactual (reclassificação aproximada nos logs)")
    print("=" * 70)
    scenarios = {
        "M0_atual_base5.5": {"speed_threshold": 5.5, "neutro_min_strength": 0.20, "chop_consistency_threshold": 0.45},
        "M1_thresh_4.0": {"speed_threshold": 4.0, "neutro_min_strength": 0.20, "chop_consistency_threshold": 0.45},
        "M2_thresh4_neutro0.12": {"speed_threshold": 4.0, "neutro_min_strength": 0.12, "chop_consistency_threshold": 0.45},
        "M3_thresh4_neutro0.12_chop0.40": {"speed_threshold": 4.0, "neutro_min_strength": 0.12, "chop_consistency_threshold": 0.40},
    }
    if rows:
        for c in counterfactual_from_logs(rows, scenarios):
            print(f"  {c['scenario']:28s} allowed={c['allowed_pct']:5.1f}% blocked={c['blocked_pct']:5.1f}% est_tpm~{c['est_tpm_factor']:.2f}")

    # Replay sintético 500 evals
    print("\n" + "=" * 70)
    print("FASE D — Replay determinístico M0/M1/M2/M3 (500 evals, seed=42)")
    print("=" * 70)
    for row in replay_m0_m3(500):
        print(
            f"  {row['mode']:28s} allowed={row['allowed_pct']:5.1f}% "
            f"lento={row['lento_pct']:5.1f}% elapsed<=0={row['elapsed_nonpos_pct']:5.1f}% "
            f"span0={row['span_zero_pct']:5.1f}% tpm~{row['est_tpm_factor']:.2f}"
        )

    print("\n" + "=" * 70)
    print("FASE 3/4 — Replay sintético 500 ticks (mercado típico WIN)")
    print("=" * 70)
    settings = Settings()
    te = TickEngine(settings)
    te.set_point(1.0)
    sf = SpeedFilter(
        speed_period=settings.speed_filter.speed_period,
        speed_threshold=settings.speed_filter.speed_threshold,
        strength_exhaustion=settings.speed_filter.strength_exhaustion,
        micro_range_window=settings.speed_filter.micro_range_window,
        ema_alpha=settings.speed_filter.ema_alpha,
        speed_clamp=settings.speed_filter.speed_clamp,
        chop_consistency_threshold=settings.speed_filter.chop_consistency_threshold,
        chop_speed_cap_factor=settings.speed_filter.chop_speed_cap_factor,
        neutro_min_strength=settings.speed_filter.neutro_min_strength,
    )
    debug = []
    import random
    random.seed(42)
    t = 1_700_000_000_000
    price = 178400.0
    raw_speeds = []
    allowed_n = 0
    for i in range(600):
        # 70% flat, 20% small step, 10% burst
        r = random.random()
        if r < 0.7:
            pass
        elif r < 0.9:
            price += random.choice([-5, 0, 5])
        else:
            price += random.choice([-15, 15])
        bid = price - 2.5
        ask = price + 2.5
        t += random.randint(3, 25)
        tick = te.process_tick(make_tick(bid, ask, t, legacy=False))
        if tick is None:
            continue
        metrics = te.compute_metrics()
        if not metrics.is_valid:
            continue
        evaluate_instrumented(sf, te, tick, metrics, debug)
        if len(debug) >= 500:
            break

    rs = [d["raw_speed"] for d in debug if "raw_speed" in d]
    es = [d["ema_speed"] for d in debug if "ema_speed" in d]
    ad = [d["adaptive_threshold"] for d in debug if "adaptive_threshold" in d]
    al = sum(1 for d in debug if d.get("allowed"))
    print(f"  evals={len(debug)} allowed={al} ({100*al/len(debug):.1f}%)")
    print(f"  raw_speed: mean={sum(rs)/len(rs):.3f} P50={percentile(rs,50):.3f} P90={percentile(rs,90):.3f} max={max(rs):.1f}")
    print(f"  ema_speed: mean={sum(es)/len(es):.3f} P50={percentile(es,50):.3f} P90={percentile(es,90):.3f} max={max(es):.1f}")
    print(f"  adaptive_threshold: mean={sum(ad)/len(ad):.3f} P50={percentile(ad,50):.3f}")
    print(f"  escape_LENTO (adapt*0.5) P50={percentile(ad,50)*0.5:.3f}")

    out_path = _project / "logs" / "speed_debug_replay.txt"
    out_path.parent.mkdir(exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for d in debug[:500]:
            f.write("[SPEED DEBUG]\n")
            for k, v in d.items():
                f.write(f"{k}={v}\n")
            f.write("\n")
    print(f"  salvo: {out_path}")


if __name__ == "__main__":
    main()
