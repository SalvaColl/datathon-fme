"""T-047 / E-471: what ONE ConnectTimeout retry does to the retried batch AND to the requests behind it.

A discrete-time simulation that runs the REAL `serving.serve` and the REAL `live.send_answers` (claim, deadline
re-check, retry rule, journal) on a virtual clock. Only three things are fake: the request stream, the model
(5 ms per request) and `live.post_batch`, which takes a sampled time and fails by an injected schedule. Nothing
touches the network; nothing is written anywhere (journal in memory).

    python tools/connect_retry_sim.py [--minutes 120] [--seed 7] [--out file.json]

Calibration (Mac log, 14 Nov 23:00-24:00 UTC, read by the deploy thread): POST p50 321 / p95 447 / p99 516 ms;
age of the oldest request at the acknowledgement p50 1198 / p95 1843 / p99 2297 ms; 3 requests per second.
The stream's visibility lag is the free parameter, tuned so the simulated ages match those three numbers.

Fault models, all on the connect phase (a failed connect costs the connect timeout, min(0.3, remaining/2)):
  none      no fault (what the Mac saw after 21:54 UTC: 0 ConnectTimeout in 11,861 batches)
  iid       every attempt fails independently with probability p
  outage    the network is down for windows of `dur` seconds (every attempt inside a window fails)
  backlog   outage windows plus a slow POST (x1.6), so requests queue behind every batch
This is a model, not the Mac: it sizes the trade-off and checks the threshold; it does not predict conversion.
"""
import argparse, contextlib, io, json, math, os, sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('RAWTREE_DRY_RUN', '0')
from requests.exceptions import ConnectTimeout, ReadTimeout
from recsys import live, serving

ITEMS = [f'p{k:02d}' for k in range(12)]
SNAP = ({}, set(), pd.DataFrame(index=ITEMS), None, ITEMS)
T0 = 1_800_000_000.0


def run(minutes, seed, retry_age, fault, p=0.0, dur=0.0, every=60.0, slow=1.0, lag_med=0.66, lag_sig=0.45, rate=3.0, urgent=2.2):
    rng = np.random.default_rng(seed)
    horizon = minutes * 60.0
    n = rng.poisson(rate * horizon)
    ts = np.sort(rng.uniform(0, horizon, n))
    visible = ts + rng.lognormal(math.log(lag_med), lag_sig, n)                 # when the request shows up in shop.requests
    post = rng.lognormal(math.log(0.321), 0.20, 4 * n) * slow                    # p95 447 ms, p99 ~510 ms at slow = 1
    coin = rng.uniform(0, 1, 8 * n)
    starts = np.cumsum(rng.exponential(every, int(horizon / every) + 5)) if fault in ('outage', 'backlog') else np.array([])
    down = lambda t: bool(len(starts)) and bool(np.any((starts <= t) & (t < starts + dur)))
    clock = [0.0]; k_post = [0]; k_coin = [0]
    reqs = [dict(request_id=str(k), ts=datetime.fromtimestamp(T0 + ts[k], timezone.utc).isoformat(), user_id='u', rv=[], page='home', k=k) for k in range(n)]
    arrived, guard, attempts_of, faults_at, uncertain = {}, set(), {}, [], {}

    def post_batch(batch, remaining):
        ids = [a['request_id'] for a in batch]
        for i in ids: attempts_of[i] = attempts_of.get(i, 0) + 1
        k_coin[0] += 1
        if (fault == 'iid' and coin[k_coin[0]] < p) or down(clock[0]):
            clock[0] += min(0.3, remaining / 2); faults_at.append(clock[0]); raise ConnectTimeout()
        k_post[0] += 1; took = post[k_post[0]]
        if took > max(0.05, remaining - 0.3) + 0.0:                              # the writer's own read timeout
            clock[0] += max(0.05, remaining - 0.3)
            for i in ids: uncertain[i] = 'ReadTimeout'
            raise ReadTimeout()
        clock[0] += took
        for a in batch:
            arrived[a['request_id']] = clock[0]
            if a['model_version'].endswith('-guard'): guard.add(a['request_id'])

    def predict(rs):
        clock[0] += 0.005 * len(rs)
        return [dict(request_id=r['request_id'], items=ITEMS[:10], model_version='m') for r in rs]
    fallback = lambda rs: [dict(request_id=r['request_id'], items=ITEMS[:10], model_version='x-guard') for r in rs]
    age = lambda r, now=None: clock[0] - ts[r['k']]
    saved = (live.snapshot, live.post_batch, live.age, live.CONNECT_RETRY_AGE, serving.age, live.public_label)
    live.snapshot = lambda: SNAP; live.post_batch = post_batch; live.age = age; live.CONNECT_RETRY_AGE = retry_age
    serving.age = lambda r, now=None: age(r); live.public_label = lambda v: v
    journal = serving.Journal(':memory:'); seen = set(); nxt = 0; pending = []; order = np.argsort(visible, kind='stable')
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            while clock[0] < horizon:
                started = clock[0]
                clock[0] += 0.06 + 0.04 * coin[(k_coin[0] * 7 + 3) % len(coin)]   # pull: 60-100 ms
                while nxt < n and visible[order[nxt]] <= clock[0]: pending.append(reqs[order[nxt]]); nxt += 1
                batch = [r for r in pending if r['request_id'] not in seen][-60:]
                pending = [r for r in pending if r['request_id'] not in seen and r not in batch]
                for r in batch:
                    if age(r) > 2.5: seen.add(r['request_id'])
                serving.serve(batch, predict, fallback, lambda rs, ans: live.send_answers(rs, ans, journal, seen), now=lambda: T0 + clock[0], urgent_age=urgent)
                clock[0] += max(0.0, 0.1 - (clock[0] - started))
    finally:
        live.snapshot, live.post_batch, live.age, live.CONNECT_RETRY_AGE, serving.age, live.public_label = saved
        journal.close()
    ok = np.array([str(k) in arrived and arrived[str(k)] - ts[k] <= 3.0 for k in range(n)])
    late = np.array([str(k) in arrived and arrived[str(k)] - ts[k] > 3.0 for k in range(n)])
    g = np.array([str(k) in guard for k in range(n)])
    retried = np.array([attempts_of.get(str(k), 0) == 2 for k in range(n)])
    fa = np.array(sorted(faults_at))
    # "behind a fault": requests that became visible in the 2 s after a failed connect and were not themselves in a failed batch
    after = np.zeros(n, bool)
    if len(fa):
        j = np.searchsorted(fa, visible, side='right') - 1
        after = (j >= 0) & (visible - fa[np.clip(j, 0, None)] <= 2.0) & np.array([attempts_of.get(str(k), 0) <= 1 and str(k) not in uncertain for k in range(n)])
        hit = np.array([str(k) in attempts_of and str(k) not in arrived and str(k) not in uncertain or attempts_of.get(str(k), 0) == 2 for k in range(n)])
        after &= ~hit
    ages = np.array([arrived[str(k)] - ts[k] for k in range(n) if str(k) in arrived])
    pct = lambda a: round(100.0 * float(np.mean(a)), 3) if len(a) else None
    return dict(requests=int(n), on_time=pct(ok), model_on_time=pct(ok & ~g), guard=pct(g & ok), late=int(late.sum()),
                connect_faults=len(fa), retried_requests=int(retried.sum()), retried_recovered=int((retried & ok).sum()), retried_late=int((retried & late).sum()),
                behind_n=int(after.sum()), behind_on_time=pct(ok[after]), behind_model_on_time=pct((ok & ~g)[after]),
                age_p50=round(float(np.percentile(ages, 50)), 3), age_p95=round(float(np.percentile(ages, 95)), 3), age_p99=round(float(np.percentile(ages, 99)), 3))


SCENARIOS = [('none', dict(fault='none')),
             ('iid 0.035% (Mac, 13:19-20:20 UTC)', dict(fault='iid', p=15 / 42416)),
             ('iid 1%', dict(fault='iid', p=0.01)),
             ('iid 5%', dict(fault='iid', p=0.05)),
             ('outage 0.5 s every ~60 s', dict(fault='outage', dur=0.5, every=60.0)),
             ('outage 2 s every ~60 s', dict(fault='outage', dur=2.0, every=60.0)),
             ('backlog: outage 1 s every ~30 s, POST x1.6', dict(fault='backlog', dur=1.0, every=30.0, slow=1.6))]
AGES = [0.0, 1.6, 2.0, 2.2]

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--minutes', type=float, default=120); ap.add_argument('--seed', type=int, default=7); ap.add_argument('--out')
    a = ap.parse_args()
    out = {}
    for name, kw in SCENARIOS:
        print(f'\n{name}')
        print('  retry age  on_time  model_on_time  guard   late  faults  retried  recovered  retried_late  behind_n  behind_on_time  behind_model  age p50/p95/p99')
        for ra in AGES:
            r = run(a.minutes, a.seed, ra, **kw); out[f'{name} | {ra}'] = r
            print(f"  {('off' if ra == 0 else ra)!s:>9}  {r['on_time']:7.3f}  {r['model_on_time']:13.3f}  {r['guard']:5.3f}  {r['late']:5d}  {r['connect_faults']:6d}  {r['retried_requests']:7d}  "
                  f"{r['retried_recovered']:9d}  {r['retried_late']:12d}  {r['behind_n']:8d}  {r['behind_on_time']!s:>14}  {r['behind_model_on_time']!s:>12}  {r['age_p50']}/{r['age_p95']}/{r['age_p99']}")
    if a.out: Path(a.out).write_text(json.dumps(out, indent=1))
