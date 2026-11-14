"""Read-only, independently cached K27 diagnostic replay. Never submits or fits.

prepare exports bounded recent returning-home feedback, earlier organic history,
organic events and timestamped metadata. evaluate replays those inputs strictly
before each request; observed logged purchases are diagnostics, not IPS/causal lift.
"""
import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
import pandas as pd
from types import SimpleNamespace
from tools.league_data import sql
from tools.local_league import stamp, sqltime, digest
from recsys import lfm, k27, attr_affinity, cold_items, home_cands

ROOT = Path(__file__).resolve().parent.parent


def save(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')


def prepare(directory, limit):
    if (directory/'manifest.json').exists():
        raise ValueError('Immutable cache exists; evaluate it instead')
    directory.mkdir(parents=True, exist_ok=True)
    team = os.environ['TEAM_ID']
    import re
    if not re.fullmatch(r'team_[A-Za-z0-9_]+', team): raise ValueError('Invalid team')
    coef = json.loads(lfm.ART.read_text())
    fitted_end = coef['meta']['fitted_on'].split(' .. ')[1].replace(' UTC', '')
    rows = sql(f"""SELECT r.request_id::String request_id, r.ts::String ts, r.user_id::String user_id,
        r.is_new_user::Bool is_new_user, r.context.page::String page, toJSONString(r.recent_views) rv,
        f.purchased::String purchased, toJSONString(f.shown) shown
        FROM shop.requests r INNER JOIN {team}.feedback f ON r.request_id::String=f.request_id::String
        WHERE f.served_by::String='team' AND r.context.page::String='home' AND NOT r.is_new_user::Bool
        AND r.ts::DateTime64(3) > toDateTime64('{fitted_end}', 3)
        ORDER BY r.ts::DateTime64(3) DESC, r.request_id::String LIMIT {limit}""")
    if not rows: raise ValueError('No requests after frozen model fitting cutoff')
    for row in rows:
        row['rv'] = [x['product_id'] for x in json.loads(row['rv'])]
        row['shown'] = json.loads(row['shown'])
    rows = sorted([r for r in rows if not r['rv']], key=lambda r: (stamp(r['ts']), r['request_id']))
    if not rows: raise ValueError('No target requests')
    start, end = rows[0]['ts'], rows[-1]['ts']
    users = sorted({r['user_id'] for r in rows})
    literals = ','.join("'"+u.replace("'", "''")+"'" for u in users)
    history = sql(f"""SELECT user_id::String u, product_id::String i,
        countIf(event_type::String='view') v, countIf(event_type::String='add_to_cart') a,
        countIf(event_type::String='purchase') p FROM shop.history_events
        WHERE user_id::String IN ({literals}) AND ts::DateTime64(3) < toDateTime64('{sqltime(start)}',3)
        GROUP BY u,i""")
    events = sql(f"""SELECT user_id::String u, product_id::String i, event_type::String e, ts::String ts
        FROM shop.events WHERE user_id::String IN ({literals})
        AND ts::DateTime64(3) < toDateTime64('{sqltime(end)}',3)
        ORDER BY ts::DateTime64(3) LIMIT 200001""")
    if len(events) >= 200001: raise ValueError('Event export truncated; reduce --limit')
    fields = 'product_id::String product_id, category::String category, subcategory::String sub, brand::String brand, price_eur::Float64 price, description::String description, created_at::String created, is_active::Bool active'
    base = sql('SELECT '+fields+' FROM shop.catalog')
    updates = sql(f"SELECT {fields}, ts::String ts, change::String change FROM shop.catalog_updates WHERE ts::DateTime64(3) <= toDateTime64('{sqltime(end)}',3) ORDER BY ts::DateTime64(3)")
    files = dict(requests=rows, history=history, events=events, base=base, updates=updates, coef=coef)
    for name, value in files.items(): save(directory/(name+'.json'), value)
    manifest = dict(start=start, end=end, fitted_end=fitted_end, requests=len(rows), users=len(users),
                    files={name:digest(value) for name,value in files.items()})
    save(directory/'manifest.json', manifest)
    print(json.dumps(manifest, indent=2))


def evaluate(directory):
    import joblib
    manifest = json.loads((directory/'manifest.json').read_text())
    data = {name:json.loads((directory/(name+'.json')).read_text()) for name in manifest['files']}
    for name, value in data.items():
        if digest(value) != manifest['files'][name]: raise ValueError('Checksum mismatch: '+name)
    rows = data['requests']
    if any(stamp(r['ts']) <= stamp(manifest['fitted_end']) for r in rows):
        raise ValueError('Frozen coefficient lookahead')
    hist = pd.DataFrame(data['history'], columns=['u','i','v','a','p'])
    # These are already timestamp-bounded organic history counts, not outcome labels.
    hp = directory/'history.parquet'
    # Consume verified JSON counts, not an unverified preexisting derived parquet.
    hist.to_parquet(hp)
    base = {r['product_id']:r.copy() for r in data['base']}
    cat0 = pd.DataFrame(list(base.values())).set_index('product_id')
    cold = SimpleNamespace(attr={p:cold_items.attrs(r['description']) for p,r in base.items()})
    aff = attr_affinity.AttrAffinity(cold, ui_path=hp)
    lf = lfm.LiveFit(data['coef'], hist)
    hc = home_cands.HomeCands(hist, cat0)
    quality_path = ROOT/'recsys/data/qrank.joblib'
    q = joblib.load(quality_path)['q']
    lq = {p:float(np.log(max(v,1e-6))) for p,v in q.items()}
    updates = sorted(data['updates'], key=lambda r: stamp(r['ts']))
    events = sorted(data['events'], key=lambda r: stamp(r['ts']))
    ui = ei = 0
    metrics = dict(N=len(rows), changed=0, control_invalid=0, treatment_invalid=0,
                   control_cart_slots=0, treatment_cart_slots=0, logged_purchases=0,
                   control_logged_purchase_hits=0, treatment_logged_purchase_hits=0)
    lat = {'control':[], 'treatment':[]}
    predictions = []
    for r in rows:
        t = stamp(r['ts'])
        while ui < len(updates) and stamp(updates[ui]['ts']) <= t:
            update = updates[ui]; p=update['product_id']
            if p in base and cold_items.attrs(update['description']) != cold.attr.get(p):
                raise ValueError('Changing description attributes need a versioned affinity reconstruction')
            base[p] = update.copy(); cold.attr[p] = cold_items.attrs(update['description']); ui += 1
        aff.sync_products()
        while ei < len(events) and stamp(events[ei]['ts']) < t:
            e=events[ei]; u,p,kind=e['u'],e['i'],e['e']
            if kind=='view': aff.add(u,p,1)
            lf.add(u,p,a=int(kind=='add_to_cart'),p=int(kind=='purchase'))
            ei += 1
        cat = pd.DataFrame([v for v in base.values() if stamp(v['created']) <= t]).set_index('product_id')
        unavail = set(cat.index[~cat.active.astype(bool)])
        unavail |= {p for p,v in base.items() if v.get('change')=='out_of_stock'}
        sub_med = pd.Series(lq).reindex(cat.index).groupby(cat['sub']).transform('median')
        quality = {p:lq.get(p, float(sub_med[p]) if pd.notna(sub_med[p]) else lf.lq0) for p in cat.index}
        lf.set_catalog(cat, unavail, aff, quality, hc)
        st = lf.user_state(r['user_id'])
        control = treatment = None
        for label, variant in [('control','k27a'),('treatment','k27b')]:
            begin=time.perf_counter_ns()
            slate,_=k27.slate(lf,r,st,aff,exclude=unavail,variant=variant)
            lat[label].append((time.perf_counter_ns()-begin)/1e6)
            invalid = slate is None or len(set(slate))!=10 or bool(set(slate)&unavail)
            metrics[label+'_invalid'] += int(invalid)
            metrics[label+'_cart_slots'] += len(set(slate or []) & set(st[2]))
            if r.get('purchased'): metrics[label+'_logged_purchase_hits'] += int(r['purchased'] in (slate or []))
            if label=='control': control=slate
            else: treatment=slate
        metrics['changed'] += int(control != treatment)
        metrics['logged_purchases'] += int(bool(r.get('purchased')))
        predictions.append([r['request_id'],control,treatment])
    metrics['latency_ms'] = {k:{f'p{p}':float(np.percentile(v,p)) for p in (50,95,99)} for k,v in lat.items()}
    metrics['prediction_sha256'] = digest(predictions)
    metrics['manifest_sha256'] = digest(manifest)
    metrics['qrank_sha256'] = hashlib.sha256(quality_path.read_bytes()).hexdigest()
    metrics['source_sha256'] = {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ('recsys/k27.py','recsys/lfm.py','recsys/attr_affinity.py','tools/k27_replay.py')}
    metrics['limitations'] = [
        'OBSERVED DATA / OFFLINE DIAGNOSTIC: no policy fitted or tuned; no conversion-lift estimate.',
        'Logged purchase coverage is selection/position biased; no propensities or counterfactual purchases available.',
        'Replay uses prior organic events, not asynchronous refresh delays or private carousel-purchase exclusions.',
        'Initial catalogue field history is unverified; available timestamped changes applied as of each request.',
        'Frozen coefficients postdate their fitting window only; runtime local config/weights on Javi host may differ.',
        'Local timing excludes metadata replay, feature copying locks, polling, network, journal and writes.']
    save(directory/'report.json',metrics)
    print(json.dumps(metrics,indent=2))


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['prepare','evaluate'])
    p.add_argument('--cache',type=Path,default=ROOT/'data/local_eval/k27')
    p.add_argument('--limit',type=int,default=400)
    a=p.parse_args()
    if not 1 <= a.limit <= 2000: p.error('limit must be 1..2000')
    if a.command=='prepare': prepare(a.cache,a.limit)
    else: evaluate(a.cache)
