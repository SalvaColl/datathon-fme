"""Regime-change scenarios of tools/final_rehearsal.py (T-064). Imported by it with --regime; nothing is written anywhere.

Every scenario rebuilds the serving state with the writer's own functions (the same calls as live.refresher, minus the
queries) on a frozen refresher, measures live.predict() and, where the answer depends on it, the real send path
(serving.serve + live.send_answers(dry=True)), then puts the original state back."""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def regime(live, rows, run, rng):
    from serving import serve
    lf = live.LF
    # ---- freeze the refresher and the stock thread: a cycle in flight must not overwrite a scenario ----
    real_query, real_refresh = live.query, live.refresh_catalog
    gate = {'hit': 0}
    def frozen_refresh():
        gate['hit'] += 1; raise ConnectionError('rehearsal: refresher frozen')
    def no_query(*a, **k): raise ConnectionError('rehearsal: RawTree not answering')
    live.refresh_catalog = frozen_refresh; live.query = no_query
    real_tb = live.traceback.print_exc; live.traceback.print_exc = lambda *a, **k: None      # one line per frozen cycle is enough
    t0 = time.time()
    while not gate['hit'] and time.time() - t0 < 90: time.sleep(0.5)                          # the cycle in flight has ended
    print('--- regime scenarios | refresher frozen after', round(time.time() - t0, 1), 's', flush=True)

    _, _, cat0, T, _ = live.snapshot()
    with live.lock: unav0, stock0 = set(live.state['unavail']), set(live.state['stock_out'])
    q0 = live.QR.q
    hot0 = set(np.array(lf.snap.ids, dtype=object)[lf.snap.hot > 0]) if lf.snap.hot is not None else None
    launched0 = set(cat0.index) - set(q0)
    print(f'catalogue {len(cat0)} | launched (no 60-day quality) {len(launched0)} = {len(launched0) / len(cat0):.1%} | unavailable {len(unav0 | stock0)} '
          f'| hot products {len(hot0 or ())} | categories {cat0.category.nunique()} (lfm width {lf.NC}) | subcategories {cat0["sub"].nunique()} (width {lf.NS})', flush=True)

    def install(cat, unav):
        """The state a refresher cycle would publish for this catalogue (same calls, same order, no query)."""
        live.QR.set_catalog(cat, unav)
        oq, oq_hist = live.organic_counts(T)
        newp = live.new_products(cat)
        lf.set_catalog(cat, unav, live.AP.aff, live.QR.lq, live.d130.HC, lq_cold=None, newp=newp, hot=hot0, oq=oq, oq_hist=oq_hist)
        pools, best = live.make_pools(cat, unav, T)
        with live.lock:
            live.fe.set_catalog(cat); live.state.update(cat=cat, unavail=set(unav), stock_out=set(), pools=pools, best=best)
        return newp

    def measure(name, reqs, count=None):
        """predict() in batches of 4, the checks of the rehearsal. -> (invalid, {request index: (label, items)})."""
        lat, bad, why, vers, exc, out = [], 0, {}, {}, 0, {}
        _, unav, c, _, _ = live.snapshot(); active = set(c.index) - unav
        for o in range(0, len(reqs), 4):
            g = reqs[o:o + 4]; t = time.perf_counter()
            try: ans = live.predict(g)
            except Exception as e:
                exc += len(g); bad += len(g); why[type(e).__name__] = why.get(type(e).__name__, 0) + len(g); continue
            lat.append((time.perf_counter() - t) * 1000 / len(g))
            for k, (r, a) in enumerate(zip(g, ans)):
                items = a['items']; vers[a['model_version']] = vers.get(a['model_version'], 0) + 1; out[o + k] = (a['model_version'], items)
                bought = live.user_bought(r['user_id'])
                err = ('not 10 distinct' if len(items) != 10 or len(set(items)) != 10 else 'not in stock / unknown' if not set(items) <= active
                       else 'already bought' if set(items) & bought else None)
                if err: bad += 1; why[err] = why.get(err, 0) + 1
        lat = np.array(lat or [0.0])
        print(f"{name:15s} n={len(reqs):5d} valid={100 * (1 - bad / max(1, len(reqs))):5.1f}% invalid={bad:4d} {why or ''} exceptions={exc} ms/request p50={np.median(lat):.1f} "
              f"p95={np.percentile(lat, 95):.1f} max={lat.max():.0f} | {dict(sorted(vers.items()))}", flush=True)
        if count is not None:
            by = {}
            for v, items in out.values(): by.setdefault(v.rsplit('-', 1)[-1] if 'lfm' in v else v, []).append(sum(p in count for p in items))
            print('   launched products per list:', {k: f'mean {np.mean(v):.2f} max {max(v)} lists>=5: {np.mean(np.array(v) >= 5):.1%} (n={len(v)})' for k, v in sorted(by.items())}, flush=True)
        return bad, out

    def send_path(name, reqs, pull=16):
        """The serving loop's own steps on fresh requests: serve(predict, fallback, send_answers(dry)). One `pull` = one loop."""
        sent, posted, errors, loops = 0, [], {}, 0
        real_repair = live.repair_for
        def spy(u, items, best, active):
            res = real_repair(u, items, best, active); posted.append((u, res, set(res) <= active, bool(set(res) & live.user_bought(u)))); return res
        live.repair_for = spy
        try:
            for o in range(0, len(reqs), pull):
                now = datetime.now(timezone.utc).isoformat()
                g = [dict(r, ts=now, request_id=f'rehearsal-{name}-{o + k}') for k, r in enumerate(reqs[o:o + pull])]
                seen = set(); n_before = len(posted); loops += 1
                def deliver(rq, answers):
                    n0 = len(posted)
                    try: live.send_answers(rq, answers, None, seen, dry=True)
                    except Exception:
                        del posted[n0:]; raise                # the group that raised never reaches its POST
                try: serve(g, live.predict, live.fallback_answers, deliver, urgent_age=live.URGENT_AGE)
                except Exception as e:                       # main() prints 'loop error' and goes on to the next pull
                    key = type(e).__name__ + ': ' + str(e)[:60]; errors[key] = errors.get(key, 0) + 1
                sent += len(posted) - n_before
        finally: live.repair_for = real_repair
        ok = sum(1 for _, res, act, _ in posted if len(res) == 10 and len(set(res)) == 10 and act)
        print(f"{name:15s} send path: requests={len(reqs)} loops={loops} answered={sent} ({100 * sent / max(1, len(reqs)):.1f}%) of them 10 distinct active={ok} "
              f"with a bought product={sum(1 for p in posted if p[3])} | loop errors={errors or 0}", flush=True)
        return len(posted) - ok

    def reset():
        """Back to the real state between scenarios, whatever the scenario left behind."""
        live.QR.q = q0; live.repair_for = repair0; lf.snap = lf.snap or snap_real
        if oq_hist0 is not None and len(live.OQ_HIST) != len(oq_hist0): live.OQ_HIST.clear(); live.OQ_HIST.update(oq_hist0)
        for a, v in state0.items(): setattr(lf, a, v)
        if not live.BOUGHT and bought_real: live.BOUGHT.update(bought_real)
        with live.lock: live.state['live'] = T
        install(cat0, unav0)
        with live.lock: live.state['stock_out'] = set(stock0)

    repair0, snap_real, oq_hist0, bought_real = live.repair_for, lf.snap, (dict(live.OQ_HIST) if live.OQ_HIST else None), dict(live.BOUGHT)
    state0 = {a: getattr(lf, a) for a in ('lcart', 'lbought', 'lcart_t', 'lbought_t', 'lmix', 'prv_day', 'prv_last', 'prv_hist', 'hcar', 'hcart', 'hbought')}
    total = 0
    known = [dict(r) for r in rows]
    newv = [dict(r, user_id=f'u_regime_{k}', is_new_user=True) for k, r in enumerate(rows)]
    home = [dict(r, rv=[], page='home') for r in rows[:len(rows) // 2]] + [dict(r, user_id=f'u_regime_h{k}', is_new_user=True, rv=[], page='home') for k, r in enumerate(rows[:len(rows) // 2])]
    try:
        try:
            # ---- 1. old catalogue dead ----
            install(cat0, unav0 | (set(cat0.index) - launched0))
            _, unav, c, _, best = live.snapshot()
            print(f'old cat dead: active products {len(set(c.index) - unav)} (all launched during the event), best list {len(best)}', flush=True)
            for nm, rq in (('dead: logged', known), ('dead: new shop.', newv), ('dead: home', home)): total += measure(nm, rq, launched0)[0]
            total += send_path('dead', known[:160])
        except Exception as e:
            total += 1; print('SCENARIO FAILED (1. old catalogue dead):', type(e).__name__, str(e)[:300], flush=True); real_tb()
        finally: reset()

        try:
            # ---- 2. tiny catalogue ----
            order = [p for p in live.make_pools(cat0, unav0, T)[1]]
            buyer = [dict(r, user_id='u_regime_buyer') for r in rows[:40]]
            for n_act in (12, 10, 9):
                keep = set(order[:n_act]); install(cat0, set(cat0.index) - keep)
                with live.feature_lock:
                    for p in order[:3]: lf.add('u_regime_buyer', p, 0, 0, 1); live.BOUGHT['u_regime_buyer'].add(p)
                measure(f'tiny {n_act}: predict', known[:200] + home[:80])            # characterised, not added to the total
                bad = send_path(f'tiny{n_act}', known[:120] + home[:40]); total += bad
                bad = send_path(f'tiny{n_act}-buyer', buyer); total += bad
            live.BOUGHT.pop('u_regime_buyer', None); lf.lbought.pop('u_regime_buyer', None)
            # one request of the pull cannot be repaired while the others can: does it take its group with it?
            install(cat0, unav0)
            real_repair = live.repair_for
            def one_bad(u, items, best, active):
                if u == 'u_regime_poison': raise ValueError('Fewer than ten eligible products; refusing invalid submission')
                return real_repair(u, items, best, active)
            live.repair_for = one_bad
            mixed = [dict(r, user_id='u_regime_poison') if k % 16 == 5 else dict(r) for k, r in enumerate(rows[:160])]
            send_path('one bad of 16', mixed)
            live.repair_for = real_repair
        except Exception as e:
            total += 1; print('SCENARIO FAILED (2. tiny catalogue):', type(e).__name__, str(e)[:300], flush=True); real_tb()
        finally: reset()

        try:
            # ---- 3. empty state ----
            names = ('lcart', 'lbought', 'lcart_t', 'lbought_t', 'lmix', 'prv_day', 'prv_last', 'prv_hist', 'hcar', 'hcart', 'hbought')
            saved = {a: getattr(lf, a) for a in names}; bought0 = dict(live.BOUGHT); live0 = live.state['live']
            for a in names: setattr(lf, a, {})
            live.BOUGHT.clear()
            with live.lock: live.state['live'] = None
            total += measure('empty: views', newv)[0]
            odd = [None, '', 'smart-fridge', 'ZZ']
            blank = [dict(r, user_id=f'u_regime_b{k}', is_new_user=True, rv=[], page=odd[k % 4] or 'unknown-page', device=odd[(k + 1) % 4], region=odd[(k + 2) % 4]) for k, r in enumerate(rows)]
            total += measure('empty: blank', blank, launched0)[0]
            snap0 = lf.snap; lf.snap = None                                           # restart: before the first lfm snapshot
            total += measure('empty: no snap', blank[:200] + newv[:200])[0]
            total += send_path('empty-nosnap', blank[:80] + newv[:80])
            lf.snap = snap0
            for a in names: setattr(lf, a, saved[a])
            live.BOUGHT.update(bought0)
            with live.lock: live.state['live'] = live0
        except Exception as e:
            total += 1; print('SCENARIO FAILED (3. empty state):', type(e).__name__, str(e)[:300], flush=True); real_tb()
        finally: reset()

        try:
            # ---- 4. unknown category ----
            pool = [str(p) for p in rng.choice(sorted(set(cat0.index) - unav0 - stock0), size=120, replace=False)]
            for label, ncat in (('unk cat: 1', 1), ('unk cat: 30', 30)):
                cat = cat0.copy()
                for k, p in enumerate(pool):
                    cat.loc[p, ['category', 'sub', 'brand']] = [f'Zz Regime {label} {k % ncat}', f'Zz Sub {label} {k % (2 * ncat)}', 'Zz Brand']
                install(cat, unav0)
                rq = [dict(r, rv=[pool[(3 * k + j) % len(pool)] for j in range(3)], page='category') for k, r in enumerate(rows)]
                total += measure(label + ' known', rq)[0]
                total += measure(label + ' new', [dict(r, user_id=f'u_regime_c{k}', is_new_user=True) for k, r in enumerate(rq)])[0]
            install(cat0, unav0)
        except Exception as e:
            total += 1; print('SCENARIO FAILED (4. unknown category):', type(e).__name__, str(e)[:300], flush=True); real_tb()
        finally: reset()

        try:
            # ---- 5. launched-product cliff: new_products() gives None above 25% of the catalogue ----
            files = [sys.argv[k + 1] for k, a in enumerate(sys.argv) if a == '--cliff-policy']
            old = [str(p) for p in rng.permutation(sorted(set(q0) & set(cat0.index) - unav0 - stock0))]
            oqh0 = dict(live.OQ_HIST) if live.OQ_HIST else None
            need = lambda share: max(0, int(np.ceil(share * len(cat0) - len(launched0))))
            print(f'cliff: {len(cat0)} products, {len(launched0)} launched; the 25% limit is passed with {int(np.floor(0.25 * len(cat0) - len(launched0))) + 1} more launched products '
                  f'on a catalogue of this size (new launches also grow the catalogue: {int(np.floor((0.25 * len(cat0) - len(launched0)) / 0.75)) + 1} more)', flush=True)
            mix = known + newv[:len(newv) // 2] + home
            for f in files:
                conf = json.loads((ROOT / f).read_text())
                live.publish_policy(live.check_policy(conf)); tag = live.POLICY['lfm_arms'][0]['tag']
                print('cliff policy', f, '->', json.dumps(live.POLICY['lfm_arms'])[:400], flush=True)
                res = {}
                for share in (None, 0.24, 0.26, 0.40):
                    extra = set(old[:need(share)]) if share else set()
                    # the extra products become "launched" the way the writer sees one: no 60-day quality, no 60-day organic history
                    live.QR.q = {p: v for p, v in q0.items() if p not in extra}
                    if oqh0 is not None: live.OQ_HIST.clear(); live.OQ_HIST.update({p: v for p, v in oqh0.items() if p not in extra})
                    newp = install(cat0, unav0); mine = launched0 | extra
                    S = lf.snap
                    print(f'cliff {tag} share={len(mine) / len(cat0):.1%} (+{len(extra)}): new_products -> {"None (newp / newph / newcap OFF)" if newp is None else len(newp)} | snapshot newp {"off" if S.newp is None else int(S.newp.sum())} '
                          f'| orate of launched: median {np.median(S.orate[[S.row[p] for p in mine if p in S.row]]) if S.orate is not None else float("nan"):.2f}', flush=True)
                    bad, out = measure(f'cliff {tag} {len(mine) / len(cat0):.0%}', mix, mine); total += bad; res[share] = (out, mine)
                a, b = res[0.24][0], res[0.26][0]; both = [k for k in a if k in b]
                by = {}
                for k in both:
                    c = a[k][0].rsplit('-', 1)[-1]; d = by.setdefault(c, [0, 0, 0.0]); d[0] += 1; d[1] += a[k][1] != b[k][1]; d[2] += len(set(a[k][1]) - set(b[k][1]))
                print(f'cliff {tag} 24% -> 26%:', {c: f'lists changed {d[1] / d[0]:.1%}, products replaced per list {d[2] / d[0]:.2f} (n={d[0]})' for c, d in sorted(by.items())}, flush=True)
            live.QR.q = q0
            if oqh0 is not None: live.OQ_HIST.clear(); live.OQ_HIST.update(oqh0)
        except Exception as e:
            total += 1; print('SCENARIO FAILED (5. launched-product cliff: new_products() gives None above 25% of the catalogue):', type(e).__name__, str(e)[:300], flush=True); real_tb()
        finally: reset()

    finally:
        live.QR.q = q0
        install(cat0, unav0)
        with live.lock: live.state['stock_out'] = stock0
        live.refresh_catalog, live.query, live.traceback.print_exc = real_refresh, real_query, real_tb
    print('--- regime scenarios: invalid answers', total, flush=True)
    return total
