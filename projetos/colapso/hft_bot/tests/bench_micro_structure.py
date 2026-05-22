import time
import sys

sys.path.insert(0, ".")

from core.micro_structure import MicroStructureEngine
from core.utils import TickData, TickMetrics, OrderSide


def make_tick(bid, ask, time_ms=0):
    if time_ms == 0:
        time_ms = int(time.time() * 1000)
    return TickData(bid=bid, ask=ask, mid=(bid + ask) / 2.0, spread=ask - bid, time_ms=time_ms)


def make_metrics(vel_fast=0.0, disp=0.0, acc=0.0, vel=0.0):
    m = TickMetrics()
    m.velocity_fast = vel_fast
    m.net_displacement = disp
    m.acceleration = acc
    m.velocity = vel
    m.is_valid = True
    return m


eng = MicroStructureEngine(candle_ticks=15, point=1.0)
close_price = 181000.0
for i in range(5):
    for ti in range(15):
        price = close_price + (ti - 7) * 0.5 + i * 2
        tick = make_tick(price, price + 2, time_ms=int(time.time() * 1000) + i * 1000 + ti * 10)
        eng.on_tick(tick)

for _ in range(20):
    eng._ring_push_time(eng._eval_times, time.time() - 1.0)
    eng._eval_times_count += 1

metrics = make_metrics(vel_fast=8.0, disp=5.0, acc=1.0)
tick = make_tick(close_price + 5.0, close_price + 7.0)

n = 10000
for _ in range(1000):
    eng.evaluate_reentry(tick, metrics, close_price, OrderSide.BUY, -5.0)

all_times = []
for _ in range(n):
    start = time.perf_counter()
    eng.evaluate_reentry(tick, metrics, close_price, OrderSide.BUY, -5.0)
    all_times.append((time.perf_counter() - start) * 1_000_000)

all_times.sort()
mean = sum(all_times) / len(all_times)
median = all_times[len(all_times) // 2]
p95 = all_times[int(len(all_times) * 0.95)]
p99 = all_times[int(len(all_times) * 0.99)]
mx = all_times[-1]

print(f"AFTER benchmark ({n} samples, warmed):")
print(f"  mean={mean:.0f}us median={median:.0f}us p95={p95:.0f}us p99={p99:.0f}us max={mx:.0f}us")
print(f"BEFORE was: mean=1078us median=442us p95=4604us p99=10623us max=60214us")
