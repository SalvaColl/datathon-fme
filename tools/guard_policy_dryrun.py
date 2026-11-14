"""T-043 dry rehearsal: the purchase guard and the policy validation on the REAL writer code, real models, real
catalogue and today's stream. Nothing is written to RawTree (--dry-run transport + POST guard). Never run it on the
machine that hosts the live writer.

    python tools/guard_policy_dryrun.py            # 1,500 logged requests
    python tools/guard_policy_dryrun.py --n 400

It needs recsys/data/policy.json NOT to exist (it writes test policies there and removes them at the end).
"""
import json, os, sys, threading, time
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
    from bench_guard import old_repair_for
    assert live.DRY, 'not a dry run'
    pol = live.DATA / 'policy.json'
    assert not pol.exists(), 'recsys/data/policy.json exists: refusing to overwrite it'
    night = json.loads((ROOT / 'recsys' / 'policy.night_1114_x2.json').read_text())
    try:
        pol.write_text(json.dumps(night))
        t = time.time(); live.initialize()
        threading.Thread(target=live.refresher, daemon=True).start(); threading.Thread(target=live.stock_refresher, daemon=True).start()
        while live.state['pools'] is None or not (live.LF and live.LF.ok) or live.state['live'] is None or not live.state['stock_checked']: time.sleep(0.5)
        print('ready after', round(time.time() - t, 1), 's | policy', json.dumps(live.POLICY), flush=True)
        tags = [a['tag'] for a in live.POLICY['lfm_arms']]; assert tags == [a['tag'] for a in night['lfm_arms']], tags

        rows = live.query("SELECT request_id::String request_id, ts::String ts, user_id::String user_id, is_new_user, context.page::String page, "
                          "context.device::String device, context.region::String region, toJSONString(recent_views) rv FROM shop.requests "
                          f"ORDER BY ts DESC LIMIT {n}", timeout=60)
        for r in rows:
            try: r['rv'] = [x['product_id'] for x in (json.loads(r['rv']) or []) if isinstance(x, dict) and x.get('product_id')]
            except (ValueError, TypeError): r['rv'] = []
        print(len(rows), 'logged requests from', rows[-1]['ts'], 'to', rows[0]['ts'], flush=True)

        # ---- 1. purchase guard on the send path ----
        ans = []
        for o in range(0, len(rows), 4): ans += live.predict(rows[o:o + 4])
        _, unav, cat, _, best = live.snapshot(); active = set(cat.index) - unav
        known = sum(1 for r in rows if live.user_bought(r['user_id']))
        stats = dict(requests=len(rows), shoppers_with_purchases=known, untouched=0, repaired_bought=0, repaired_other=0, old_sent_bought=0, invalid=0, bought_after=0)
        t_old, t_new = [], []
        for r, a in zip(rows, ans):
            u = r['user_id']; t0 = time.perf_counter(); old = old_repair_for(u, a['items'], best, active); t1 = time.perf_counter()
            new = live.repair_for(u, a['items'], best, active); t2 = time.perf_counter()
            t_old.append((t1 - t0) * 1e6); t_new.append((t2 - t1) * 1e6)
            b = live.user_bought(u)
            if set(old) & b: stats['old_sent_bought'] += 1
            if new is a['items']: stats['untouched'] += 1
            elif set(a['items'] or ()) & b: stats['repaired_bought'] += 1
            else: stats['repaired_other'] += 1
            if len(new) != 10 or len(set(new)) != 10 or not set(new) <= active: stats['invalid'] += 1
            if set(new) & b: stats['bought_after'] += 1
        print('guard on logged requests:', json.dumps(stats), flush=True)
        print('repair_for per request, µs: before p50=%.1f p99=%.1f max=%.0f | now p50=%.1f p99=%.1f max=%.0f' % (
            np.median(t_old), np.percentile(t_old, 99), max(t_old), np.median(t_new), np.percentile(t_new, 99), max(t_new)), flush=True)

        # a purchase that arrives between ranking and send: the 3rd product of every slate (in-process state only)
        late = dict(n=0, old_sent=0, new_sent=0, invalid=0, order_kept=0); added = []
        for r, a in zip(rows, ans):
            u, items = r['user_id'], a['items']; p = items[2]
            if p in live.user_bought(u): continue
            live.BOUGHT[u].add(p); added.append((u, p)); late['n'] += 1
            old = old_repair_for(u, items, best, active); new = live.repair_for(u, items, best, active)
            late['old_sent'] += p in old; late['new_sent'] += p in new
            late['invalid'] += len(set(new)) != 10 or not set(new) <= active or bool(set(new) & live.user_bought(u))
            b = live.user_bought(u); late['order_kept'] += new[:len(items) - len(set(items) & b)] == [x for x in items if x not in b]
        for u, p in added: live.BOUGHT[u].discard(p)
        print('purchase between ranking and send:', json.dumps(late), flush=True)

        # ---- 2. bad policy updates against the running refresher (it re-reads policy.json every cycle) ----
        def served():
            vers = {}
            for o in range(0, 200, 4):
                for a in live.predict(rows[o:o + 4]): vers[a['model_version']] = vers.get(a['model_version'], 0) + 1
            return sorted(vers)
        def snap(): return (json.dumps(live.POLICY, sort_keys=True), {k: id(v) for k, v in live.LF.alt.items()})
        def wait_refresher(done, limit=120):       # the refresher thread itself must pick the file up (one cycle is ~20 s)
            t0 = time.time()
            while not done() and time.time() - t0 < limit: time.sleep(0.5)
            return done()
        before, labels = snap(), served(); bad = 0
        cases = [('missing weight file', json.dumps({'variant': 'qrank', 'lfm_arms': [{'tag': 'r3', 'file': 'lfm_coef_r3.json'}, {'tag': 'zz', 'file': 'lfm_coef_nope.json'}]})),
                 ('truncated policy.json', json.dumps(night)[:-25]),
                 ('non-finite override', '{"variant": "lfm", "lfm_arms": [{"tag": "r3", "file": "lfm_coef_r3.json", "w": {"known": {"islast": NaN}}}]}'),
                 ('unknown variant', json.dumps(dict(night, variant='lfm2'))),
                 ('cold_new without control', json.dumps({'variant': 'lfm', 'lfm_arms': [{'tag': 'r3'}, {'tag': 'cn1', 'file': 'lfm_coef_r3.json', 'lq': 'cold_new'}]}))]
        for name, text in cases:
            n0 = live.POLICY_REJECTED['n']; pol.write_text(text); seen = wait_refresher(lambda: live.POLICY_REJECTED['n'] > n0)
            same = seen and snap() == before and served() == labels; bad += not same
            print(f'  {name:28s} -> rejected by the refresher: {seen}; policy, weights and served labels unchanged: {same}', flush=True)
        good = {'variant': 'lfm', 'lfm_arms': [{'tag': 'r3', 'file': 'lfm_coef_r3.json'}, {'tag': 'np2', 'file': 'lfm_coef_r3.json', 'w': {'known': {'newp': 2.0}}}]}
        pol.write_text(json.dumps(good))
        ok = wait_refresher(lambda: [a['tag'] for a in live.POLICY['lfm_arms']] == ['r3', 'np2'] and set(live.LF.alt) == {'r3', 'np2'}); bad += not ok
        print('  recovery with a correct file -> arms', [a['tag'] for a in live.POLICY['lfm_arms']], 'labels', served(), 'ok:', ok, flush=True)
        fails = stats['invalid'] + stats['bought_after'] + late['new_sent'] + late['invalid'] + bad
        print('RESULT:', 'OK' if not fails else f'{fails} PROBLEMS', flush=True)
    finally:
        if pol.exists(): pol.unlink()


if __name__ == '__main__':
    main()
