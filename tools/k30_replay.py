"""Read-only K30 as-of diagnostic. No fitting, policy writes or submissions.

prepare: freeze mature returning product/category feedback and earlier organic
events. evaluate: replay both arms; slate composition/label coverage is NOT lift.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import joblib
import numpy as np
import pandas as pd
from tools.league_data import sql
from tools.local_league import stamp,sqltime,digest
from recsys import lfm,attr_affinity,cold_items,home_cands,qrank

ROOT=Path(__file__).resolve().parent.parent
ARTIFACTS=('recsys/lfm_coef_r2.json','recsys/lfm_coef_k30.json','recsys/data/qrank.joblib','recsys/cold_prior.json')


def save(path,obj):path.write_text(json.dumps(obj,indent=2,allow_nan=False),encoding='utf-8')


def events_before(lf,aff,events,position,t):
    while position<len(events) and stamp(events[position]['ts'])<t:
        e=events[position]; kind=e['e']
        if kind=='view':aff.add(e['u'],e['i'],1)
        lf.add(e['u'],e['i'],a=int(kind=='add_to_cart'),p=int(kind=='purchase'))
        position+=1
    return position


def prepare(directory,limit):
    if (directory/'manifest.json').exists():raise ValueError('Immutable cache exists; evaluate it')
    directory.mkdir(parents=True,exist_ok=True)
    team=os.environ['TEAM_ID']
    if not re.fullmatch(r'team_[A-Za-z0-9_]+',team):raise ValueError('Invalid team')
    coverage=sql('SELECT min(ts::DateTime64(3))::String lo, max(ts::DateTime64(3))::String hi, count() n FROM shop.requests')[0]
    latest=stamp(coverage['hi']); end=latest.replace(minute=5*(latest.minute//5),second=0,microsecond=0)
    start=end-timedelta(minutes=30)
    coef=json.loads((ROOT/ARTIFACTS[0]).read_text())
    fitted_end=coef['meta']['fitted_on'].split(' .. ')[1].replace(' UTC','')
    if start<=stamp(fitted_end) or start<=stamp(coverage['lo']):raise ValueError('Insufficient post-fit request coverage')
    rows=sql(f"""SELECT r.request_id::String request_id, r.ts::String ts, r.user_id::String user_id,
      r.is_new_user::Bool is_new_user, r.context.page::String page, r.context.device::String device,
      r.context.region::String region, toJSONString(r.recent_views) rv,
      f.purchased::String purchased, toJSONString(f.shown) shown
      FROM shop.requests r INNER JOIN {team}.feedback f ON r.request_id::String=f.request_id::String
      WHERE f.served_by::String='team' AND NOT r.is_new_user::Bool AND r.context.page::String IN ('product','category')
      AND r.ts::DateTime64(3) >= toDateTime64('{sqltime(start)}',3)
      AND r.ts::DateTime64(3) < toDateTime64('{sqltime(end)}',3)
      ORDER BY cityHash64(r.request_id::String),r.request_id::String LIMIT {limit}""")
    for row in rows:
        row['rv']=[x['product_id'] for x in json.loads(row['rv'])]; row['shown']=json.loads(row['shown'])
    rows=sorted([r for r in rows if r['rv']],key=lambda r:(stamp(r['ts']),r['request_id']))
    if not rows:raise ValueError('No eligible requests')
    users=sorted({r['user_id'] for r in rows}); literals=','.join("'"+u.replace("'","''")+"'" for u in users)
    history=sql(f"""SELECT user_id::String u, product_id::String i, countIf(event_type::String='view') v,
      countIf(event_type::String='add_to_cart') a, countIf(event_type::String='purchase') p FROM shop.history_events
      WHERE user_id::String IN ({literals}) AND ts::DateTime64(3) < toDateTime64('{sqltime(start)}',3) GROUP BY u,i""")
    events=sql(f"""SELECT user_id::String u, product_id::String i, event_type::String e, ts::String ts
      FROM shop.events WHERE user_id::String IN ({literals}) AND ts::DateTime64(3) < toDateTime64('{sqltime(end)}',3)
      ORDER BY ts::DateTime64(3) LIMIT 200001""")
    if len(events)>=200001:raise ValueError('Event export truncated; reduce limit')
    fields='product_id::String product_id, category::String category, subcategory::String sub, brand::String brand, price_eur::Float64 price, description::String description, created_at::String created, is_active::Bool active'
    base=sql('SELECT '+fields+' FROM shop.catalog')
    updates=sql(f"SELECT {fields}, ts::String ts, change::String change FROM shop.catalog_updates WHERE ts::DateTime64(3) < toDateTime64('{sqltime(end)}',3) ORDER BY ts::DateTime64(3)")
    files=dict(requests=rows,history=history,events=events,base=base,updates=updates,coef=coef)
    for name,obj in files.items():save(directory/(name+'.json'),obj)
    manifest=dict(coverage=coverage,start=start.isoformat(),end=end.isoformat(),fitted_end=fitted_end,
        requests=len(rows),users=len(users),files={n:digest(v) for n,v in files.items()},
        artifacts={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ARTIFACTS})
    save(directory/'manifest.json',manifest); print(json.dumps(manifest,indent=2))


def evaluate(directory):
    from threadpoolctl import threadpool_limits
    manifest=json.loads((directory/'manifest.json').read_text())
    data={n:json.loads((directory/(n+'.json')).read_text()) for n in manifest['files']}
    for n,value in data.items():
        if digest(value)!=manifest['files'][n]:raise ValueError('Cache changed: '+n)
    for n,sha in manifest['artifacts'].items():
        if hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=sha:raise ValueError('Artifact changed: '+n)
    rows=data['requests']
    if any(stamp(r['ts'])<=stamp(manifest['fitted_end']) for r in rows):raise ValueError('Coefficient lookahead')
    hist=pd.DataFrame(data['history'],columns=['u','i','v','a','p']); hp=directory/'history.parquet'; hist.to_parquet(hp)
    base={r['product_id']:r.copy() for r in data['base']}; cat0=pd.DataFrame(list(base.values())).set_index('product_id')
    cold=SimpleNamespace(attr={p:cold_items.attrs(r['description']) for p,r in base.items()})
    aff=attr_affinity.AttrAffinity(cold,ui_path=hp); lf=lfm.LiveFit(data['coef'],hist)
    hc=home_cands.HomeCands(hist,cat0); qr=qrank.Ranker(None,joblib.load(ROOT/'recsys/data/qrank.joblib')['q'])
    arms=json.loads((ROOT/'recsys/arms_k30.json').read_text())['lfm_arms']; lf.set_arms(arms)
    if arms!=[{'tag':'q7a','file':'lfm_coef_r2.json'},{'tag':'q7b','file':'lfm_coef_k30.json'}]:
        raise ValueError('Replay expects frozen original arms; use a new cache for other configurations')
    updates=sorted(data['updates'],key=lambda r:stamp(r['ts'])); events=sorted(data['events'],key=lambda r:stamp(r['ts']))
    ui=ei=0; predictions=[]; timing={'control':[],'candidate':[]}
    totals={k:dict(invalid=0,cart_slots=0,taste_cart_slots=0,omitted_cart_requests=0,logged_purchase_hits=0) for k in timing}
    changed=offtarget=logged=0; cat=None
    with threadpool_limits(limits=1):
        for j,r in enumerate(rows):
            t=stamp(r['ts']); update_catalog=cat is None
            while ui<len(updates) and stamp(updates[ui]['ts'])<=t:
                u=updates[ui]; p=u['product_id']; attrs=cold_items.attrs(u['description'])
                if p in cold.attr and attrs!=cold.attr[p]:raise ValueError('Description changes need versioned affinity')
                base[p]=u.copy(); cold.attr[p]=attrs; ui+=1; update_catalog=True
            if update_catalog:
                aff.sync_products()
                cat=pd.DataFrame([r for r in base.values() if stamp(r['created'])<=t]).set_index('product_id')
                unavail=set(cat.index[~cat.active.astype(bool)])|{p for p,v in base.items() if v.get('change')=='out_of_stock'}
                qr.set_catalog(cat,unavail); lf.set_catalog(cat,unavail,aff,qr.lq,hc)
            ei=events_before(lf,aff,events,ei,t)
            st=lf.user_state(r['user_id']); pending=set(st[1])|set(st[2]); tastes=aff.affinity_all(r['user_id'],r['rv'])
            S=lf.snap; stale=S.stale(r['user_id']); eligible=set(cat.index)-unavail-st[0]
            if stale is not None:eligible-={S.ids[k] for k in np.flatnonzero(stale) if S.ids[k] not in pending}
            relevant={p for p in pending if p in S.row and tastes[S.row[p]]>=.15}; pair={}
            for key,arm in ([('control','q7a'),('candidate','q7b')] if j%2 else [('candidate','q7b'),('control','q7a')]):
                begin=time.perf_counter_ns(); out=lf.slate(r,st,aff,model=arm,exclude=unavail)
                elapsed=(time.perf_counter_ns()-begin)/1e6
                if j>=10:timing[key].append(elapsed)
                slate=set(out or ()); m=totals[key]
                m['invalid']+=int(out is None or len(out)!=10 or len(slate)!=10 or not slate<=eligible)
                m['cart_slots']+=len(slate&pending); m['taste_cart_slots']+=len(slate&relevant)
                m['omitted_cart_requests']+=int(bool((pending&eligible)-slate))
                m['logged_purchase_hits']+=int(bool(r.get('purchased')) and r['purchased'] in slate)
                pair[key]=out
            changed+=int(pair['control']!=pair['candidate']); logged+=int(bool(r.get('purchased')))
            for probe in ({**r,'is_new_user':True},{**r,'page':'home','rv':[]}):
                offtarget+=int(lf.slate(probe,st,aff,model='q7a')!=lf.slate(probe,st,aff,model='q7b'))
            predictions.append([r['request_id'],pair['control'],pair['candidate']])
    result=dict(evidence='AS-OF SLATE DIAGNOSTIC, NOT CONVERSION UPLIFT',requests=len(rows),users=manifest['users'],
        start=manifest['start'],end=manifest['end'],changed=changed,offtarget_mismatches=offtarget,logged_purchases=logged,arms=totals,
        latency_ms={k:{f'p{q}':float(np.percentile(v,q)) for q in (50,95,99)} for k,v in timing.items()},
        prediction_sha256=digest(predictions),manifest_sha256=digest(manifest),
        source_sha256={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ('recsys/k30.py','recsys/lfm.py','tools/k30_replay.py')},
        limitations=['Observed requests/outcomes selected by previously served policies; purchase coverage is not IPS or a causal conversion estimate.',
        'No fitting/tuning, held-out league test unopened; fixed bonus was chosen before inspecting these labels.',
        'As-of organic events and timestamped catalogue updates, but initial catalogue field history unverified.',
        'No asynchronous refresh lag or private carousel-purchase exclusions; committed r2 weights, actual writer overrides may differ.',
        'Local one-thread BLAS timing excludes snapshot replay, feature locks, network, journal, concurrent refresh and submissions.'])
    save(directory/'report.json',result); print(json.dumps(result,indent=2))
    if offtarget or any(m['invalid'] for m in totals.values()):raise ValueError('Slate isolation/validity failure')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('command',choices=['prepare','evaluate'])
    p.add_argument('--cache',type=Path,default=ROOT/'data/local_eval/k30'); p.add_argument('--limit',type=int,default=600)
    a=p.parse_args()
    if not 20<=a.limit<=2000:p.error('limit must be 20..2000')
    if a.command=='prepare':prepare(a.cache,a.limit)
    else:evaluate(a.cache)
