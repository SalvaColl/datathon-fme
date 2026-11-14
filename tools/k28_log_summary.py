"""Summarize copied writer JSON logs locally. No network or model imports."""
import argparse
import collections
import json
from pathlib import Path


def percentile(values,q):
    if not values:return None
    a=sorted(values); x=(len(a)-1)*q; i=int(x)
    return a[i]+(a[min(i+1,len(a)-1)]-a[i])*(x-i)


def summarize(lines, last=2000):
    rows=collections.deque(maxlen=last)
    for line in lines:
        try:
            r=json.loads(line[line.index('{'):])
            if isinstance(r,dict) and r.get('event') in ('loop','push_ack','push_uncertain','reader_error','delivery','event_apply'): rows.append(r)
        except (ValueError,TypeError): pass
    def stats(event,key,nested=None):
        values=[r.get(nested,{}).get(key) if nested else r.get(key) for r in rows if r.get('event')==event]
        values=[v for v in values if isinstance(v,(int,float))]
        return dict(n=len(values),p50=percentile(values,.5),p95=percentile(values,.95),p99=percentile(values,.99),maximum=max(values,default=None))
    clocks=[r['ts_utc'] for r in rows if isinstance(r.get('ts_utc'),(int,float))]
    return dict(log_rows=len(rows),first_utc_epoch=min(clocks,default=None),last_utc_epoch=max(clocks,default=None),
        delivery_modes=dict(collections.Counter(r.get('delivery','legacy') for r in rows if r.get('event')=='loop')),
        poll_ms=stats('loop','last_poll_ms','reader'),wait_ms=stats('loop','wait_ms'),
        source_age_ms=stats('loop','source_age_ms'),predict_ms=stats('loop','predict_ms'),
        prepare_ms=stats('push_ack','prepare_ms'),post_ms=stats('push_ack','post_ms'),
        journal_finish_ms=stats('push_ack','journal_finish_ms'),age_at_post_ms=stats('push_ack','age_at_post_ms'),
        event_max_lock_ms=stats('event_apply','max_lock_ms'),event_apply_ms=stats('event_apply','elapsed_ms'),
        expired=sum(r.get('expired',0) for r in rows if r.get('event')=='loop'),
        deadline_guarded=sum(r.get('deadline_guarded',0) for r in rows if r.get('event')=='loop'),
        uncertain_batches=sum(r.get('event')=='push_uncertain' for r in rows),
        reader_error_log_rows=sum(r.get('event')=='reader_error' for r in rows),
        limitations=['Client diagnostics only: acknowledgements do not prove server on-time acceptance.',
        'loop/reader figures are per log row, not independent per-request samples. Compare fixed time windows with team feedback.',
        'Reader error logs are throttled; the last reader.poll_errors value is cumulative, not the log-row count.'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('logfile',type=Path)
    p.add_argument('--last',type=int,default=2000)
    a=p.parse_args()
    if a.last<1:p.error('last must be positive')
    with a.logfile.open(encoding='utf-8',errors='replace') as f: print(json.dumps(summarize(f,a.last),indent=2))
