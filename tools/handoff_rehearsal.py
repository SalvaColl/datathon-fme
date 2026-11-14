"""Rehearse a zero-downtime writer restart against the real stream WITHOUT writing a single submission.

Both processes run the real recsys/live.py (real pull, real models, real lock + journal code) but:
  * live.post_batch is replaced by a recorder (one JSON line per answer in <dir>/posts.jsonl),
  * any HTTP POST to a /v1/tables/ URL raises (second guard),
  * lock + journal live in their own directory (RAWTREE_LOCK_DIR), never the real writer's.

    python tools/handoff_rehearsal.py writer   &     # "old" writer; wait for its 'ready LIVE'
    python tools/handoff_rehearsal.py takeover &     # "new" writer: warms up, then takes over
    python tools/handoff_rehearsal.py report         # after a minute: answered once / twice / never, per process

Do not run it on the machine that hosts the live writer: it competes for CPU.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIR = Path(os.environ.get('RAWTREE_LOCK_DIR') or Path(tempfile.gettempdir()) / 'rawtree-rehearsal')
POSTS = DIR / 'posts.jsonl'
POST_MS = float(os.environ.get('REHEARSAL_POST_MS', '300'))     # the Mac's median POST on 14 Nov was 295 ms


def run(mode):
    os.environ['RAWTREE_LOCK_DIR'] = str(DIR)
    DIR.mkdir(parents=True, exist_ok=True)
    os.chdir(ROOT / 'recsys'); sys.path.insert(0, str(ROOT / 'recsys'))
    sys.argv = ['live.py'] + (['--takeover'] if mode == 'takeover' else []) + sys.argv[2:]
    assert '--dry-run' not in sys.argv
    import requests
    real_post = requests.Session.post

    def guarded_post(self, url, *a, **k):
        if '/v1/tables/' in str(url):
            raise RuntimeError('rehearsal: refusing to write to RawTree')
        return real_post(self, url, *a, **k)
    requests.Session.post = guarded_post
    import live

    def record(batch, remaining):
        time.sleep(POST_MS / 1000)
        now = time.time()
        with open(POSTS, 'a') as f:
            f.write(''.join(json.dumps(dict(request_id=a['request_id'], t=now, pid=os.getpid(), mode=mode,
                                            n_items=len(set(a['items'])), version=a['model_version'])) + '\n' for a in batch))
    live.post_batch = record
    assert live.post_batch is record and not live.DRY
    live.main()


def report():
    os.chdir(ROOT / 'recsys'); sys.path.insert(0, str(ROOT / 'recsys'))
    import pandas as pd
    from rt import q
    posts = pd.DataFrame([json.loads(line) for line in POSTS.read_text().splitlines()])
    first, last = posts.t.min(), posts.t.max() - 4          # requests of the last seconds may still be in flight
    fmt = lambda t: pd.Timestamp(t, unit='s').strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    reqs = q(f"""SELECT request_id::String request_id, toUnixTimestamp64Milli(ts::DateTime64(3))/1000 ts FROM shop.requests
                 WHERE ts::DateTime64(3) > toDateTime64('{fmt(first)}',3) AND ts::DateTime64(3) <= toDateTime64('{fmt(last)}',3)""")
    reqs['ts'] = reqs.ts.astype(float)
    n = posts.groupby('request_id').agg(times=('t', 'size'), t=('t', 'min'), pid=('pid', 'first'), mode=('mode', 'first'))
    m = reqs.merge(n, left_on='request_id', right_index=True, how='left')
    m['times'] = m.times.fillna(0).astype(int); m['lat'] = m.t - m.ts
    switch = posts[posts['mode'] == 'takeover'].t.min() if (posts['mode'] == 'takeover').any() else None
    print(f"requests in window: {len(m)} | answered once: {(m.times == 1).sum()} | never: {(m.times == 0).sum()} "
          f"| more than once: {(m.times > 1).sum()} | over 2.5 s at POST: {(m.lat > 2.5).sum()}")
    print('answers per process:', posts.groupby(['mode', 'pid']).size().to_dict(), '| invalid slates:', int((posts.n_items != 10).sum()))
    print('POST age p50/p95/max (s):', [round(float(x), 2) for x in m.lat.dropna().quantile([.5, .95, 1.0])])
    if switch is not None:
        w = m[(m.ts > switch - 10) & (m.ts < switch + 10)]
        old_after = posts[(posts['mode'] == 'writer') & (posts.t > switch)]
        print(f"handoff at {fmt(switch)} UTC | requests within ±10 s: {len(w)}, never answered: {(w.times == 0).sum()}, "
              f"twice: {(w.times > 1).sum()}, worst POST age {w.lat.max():.2f} s | old-writer answers after the switch: {len(old_after)}")
        gap = posts.sort_values('t').t.diff()
        print(f"longest silence between answers in the whole run: {gap.max():.2f} s")
    return m


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    if mode in ('writer', 'takeover'): run(mode)
    elif mode == 'report': report()
    else: sys.exit(__doc__)
