"""Robustness rehearsal for the final (T-032): does the real writer code answer ten valid products, fast, when the
world is not the one it was fitted on? NOT a conversion estimate. Nothing is written anywhere.

    python tools/final_rehearsal.py              # ~1,500 logged requests per scenario
    python tools/final_rehearsal.py --n 400

It loads the real recsys/live.py in --dry-run (real models, real catalogue and event refresh), then calls
live.predict() on logged requests rewritten for each scenario. Guards: any HTTP POST to /v1/tables/ raises, and
data/policy.json is only read (if it does not exist, the champion arm is set inside this process only).

Scenarios
  logged          the requests as they arrived (reference)
  new shopper     unknown user id, is_new_user true, recent views kept
  new, no views   unknown user id, no recent views (home)
  new product     the only recent views are products launched during the event (no purchases, no graph edges)
  bad metadata    device / region / page missing or unknown, recent views with unknown ids, is_new_user null
  category flip   every shopper suddenly views 50 products of one other category (category mix changes)
  stock shock     a third of the catalogue goes out of stock, including each request's recent views
  stale refresh   RawTree stops answering queries: served from the last features (also covers "no leaderboard")

Regime-change scenarios (T-064, only with --regime; they run after the ones above, on a frozen refresher, and rebuild
the catalogue state with the writer's own functions: new_products, organic_counts, LiveFit.set_catalog, make_pools)
  old cat dead    every product of the pre-event catalogue inactive; only products launched during the event are left
  tiny catalogue  12 / 10 / 9 active products overall, through the real serve() + send_answers(dry) path: what would be
                  posted and what happens to the batch when serving.repair raises
  empty state     all shopper state gone (carts, purchases, views, earlier requests) and every shopper unknown;
                  blank shopper (no views, unknown page / device / region); restart before the first lfm snapshot
  unknown categ.  recent views only of products moved to categories that no fitted table has seen
  launched cliff  live.new_products() returns None above 25% of the catalogue (newp, newph and newcap go off):
                  lists at the current share, 24% and 26%, per policy given with --cliff-policy (repeatable)
"late events / reconnect": the stale half is the existing "stale refresh" scenario; the burst half is not simulated.
    python tools/final_rehearsal.py --n 400 --regime --policy recsys/policy.rot_uf1.json --cliff-policy recsys/policy.rot_uf1.json

Checks per answer: exactly 10 distinct products, all in the catalogue and in stock as the writer sees it, none the
shopper already bought. Latency is predict() per request, batches of 4 as in the serving loop.
Do not run it on the machine that hosts the live writer: it competes for CPU.
"""
import json
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    n = int(sys.argv[sys.argv.index('--n') + 1]) if '--n' in sys.argv else 1500
    import requests
    real_post = requests.Session.post
    def guarded_post(self, url, *a, **k):
        if '/v1/tables/' in str(url): raise RuntimeError('rehearsal: refusing to write to RawTree')
        return real_post(self, url, *a, **k)
    requests.Session.post = guarded_post
    os.chdir(ROOT / 'recsys'); sys.path.insert(0, str(ROOT / 'recsys')); sys.path.insert(0, str(ROOT / 'tools'))
    sys.argv = ['live.py', '--dry-run', '--lfm']
    import numpy as np
    import live
    assert live.DRY, 'not a dry run'
    src = (ROOT / 'recsys' / 'live.py').read_text() + (ROOT / 'recsys' / 'lfm.py').read_text()
    print('serving code reads the leaderboard:', 'api/state' in src)

    t = time.time(); live.initialize()
    threading.Thread(target=live.refresher, daemon=True).start(); threading.Thread(target=live.stock_refresher, daemon=True).start()
    while live.state['pools'] is None or not (live.LF and live.LF.ok) or live.state['live'] is None or not live.state['stock_checked']: time.sleep(0.5)
    if not (live.DATA / 'policy.json').exists():
        arms = [{'tag': 'r3', 'file': 'lfm_coef_r3.json'}]; live.LF.set_arms(arms); live.POLICY['lfm_arms'] = arms
    if '--policy' in sys.argv and not (live.DATA / 'policy.json').exists():
        conf = json.loads((ROOT / sys.argv[sys.argv.index('--policy') + 1]).read_text())
        live.POLICY['lfm_arms'] = []; live.LF.set_arms([]); live.publish_policy(live.check_policy(conf))     # the writer's own validation path
    print('ready after', round(time.time() - t, 1), 's | policy', json.dumps(live.POLICY), flush=True)

    rows = live.query("SELECT request_id::String request_id, ts::String ts, user_id::String user_id, is_new_user, context.page::String page, "
                      "context.device::String device, context.region::String region, toJSONString(recent_views) rv FROM shop.requests "
                      f"ORDER BY ts DESC LIMIT {n}", timeout=60)
    for r in rows:
        try: r['rv'] = [x['product_id'] for x in (json.loads(r['rv']) or []) if isinstance(x, dict) and x.get('product_id')]
        except (ValueError, TypeError): r['rv'] = []
    _, _, cat, _, _ = live.snapshot()
    launched = list(cat.index[cat.last_change == 'new_product']); cats = sorted(cat.category.unique())
    by_cat = {c: list(cat.index[cat.category == c][:50]) for c in cats}
    print(len(rows), 'logged requests from', rows[-1]['ts'], 'to', rows[0]['ts'], '|', len(cat), 'products,', len(launched), 'launched during the event', flush=True)
    rng = np.random.default_rng(0)

    def run(name, reqs, extra_unavail=()):
        lat, bad, why, vers, changed = [], 0, {}, {}, 0
        for o in range(0, len(reqs), 4):
            g = reqs[o:o + 4]; t0 = time.perf_counter(); ans = live.predict(g); lat.append((time.perf_counter() - t0) * 1000 / len(g))
            _, unav, c, _, _ = live.snapshot(); active = set(c.index) - unav - set(extra_unavail)
            for r, a in zip(g, ans):
                items = a['items']; vers[a['model_version']] = vers.get(a['model_version'], 0) + 1
                bought = live.BOUGHT.get(r['user_id'], set()) | (live.LF.user_state(r['user_id'])[0] if 'lfm' in a['model_version'] else set())
                err = ('not 10 distinct' if len(items) != 10 or len(set(items)) != 10 else 'not in stock / unknown' if not set(items) <= active
                       else 'already bought' if set(items) & bought else None)
                if err: bad += 1; why[err] = why.get(err, 0) + 1
        lat = np.array(lat)
        print(f"{name:15s} n={len(reqs):5d} invalid={bad:4d} {why or ''} ms/request p50={np.median(lat):.1f} p95={np.percentile(lat, 95):.1f} p99={np.percentile(lat, 99):.1f} "
              f"max={lat.max():.0f} | {dict(sorted(vers.items()))}", flush=True)
        return bad

    total = run('warm-up', [dict(r) for r in rows[:200]]); total = 0
    total += run('logged', [dict(r) for r in rows])
    total += run('new shopper', [dict(r, user_id=f'u_rehearsal_{k}', is_new_user=True) for k, r in enumerate(rows)])
    total += run('new, no views', [dict(r, user_id=f'u_rehearsal_h{k}', is_new_user=True, rv=[], page='home') for k, r in enumerate(rows)])
    if launched:
        total += run('new product', [dict(r, user_id=f'u_rehearsal_p{k}', is_new_user=True, rv=[str(x) for x in rng.choice(launched, size=min(3, len(launched)), replace=False)], page='product')
                                     for k, r in enumerate(rows)])
    odd = [None, '', 'smart-fridge', 'ZZ']
    total += run('bad metadata', [dict(r, device=odd[k % 4], region=odd[(k + 1) % 4], page=odd[(k + 2) % 4] or 'unknown-page', is_new_user=None if k % 2 else r['is_new_user'],
                                       rv=(['p_does_not_exist'] + r['rv']) if k % 3 else ['p_does_not_exist']) for k, r in enumerate(rows)])
    flip = []
    for k, r in enumerate(rows[: max(200, n // 3)]):                    # in-process state only: this is a dry process
        home = cat.category.get(r['rv'][-1]) if r['rv'] else None
        other = cats[(cats.index(home) + 1 + k) % len(cats)] if home in cats else cats[k % len(cats)]
        with live.feature_lock:
            for p in by_cat[other]: live.LF.add(r['user_id'], p, 1, 0, 0)
        flip.append(dict(r))
    total += run('category flip', flip)
    _, unav0, _, _, _ = live.snapshot()
    out = set(str(x) for x in rng.choice(list(set(cat.index) - unav0), size=len(cat) // 3, replace=False)) | {p for r in rows for p in r['rv']}
    with live.lock: saved = set(live.state['stock_out']); live.state['stock_out'] = saved | out
    real_query = live.query
    def no_query(*a, **k): raise ConnectionError('rehearsal: RawTree not answering')
    live.query = no_query                                                 # so the stock thread cannot undo the shock
    total += run('stock shock', [dict(r) for r in rows])
    with live.lock: live.state['stock_out'] = saved
    time.sleep(3)
    total += run('stale refresh', [dict(r) for r in rows])
    live.query = real_query
    if '--regime' in sys.argv:
        from final_regime import regime
        total += regime(live, rows, run, rng)
    print('TOTAL invalid answers:', total, '| stock last refreshed', round(time.monotonic() - live.state['stock_checked'], 1), 's ago during the stale scenario')
    return total


if __name__ == '__main__':
    sys.exit(1 if main() else 0)
