"""Read-only comparison of K30 returning/non-home labels in one public window.

No promotion, policy edits, training, or submissions. Private labels stay local.
Missing/suppressed rows are unknown, never zero conversion.
"""
import argparse
import json
import math
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from recsys.lfm_tuner import fetch,public_label

ROOT=Path(__file__).resolve().parent.parent


def summarize(state,labels,team='team_26'):
    if not labels or not labels.get('salt'):raise ValueError('Private opaque-label configuration required; do not print or publish it')
    teams=[t for t in state.get('teams',[]) if t.get('team_id')==team]
    if len(teams)!=1:raise ValueError('Team missing or ambiguous')
    row=teams[0]; versions=row.get('versions',[]); reference=state.get('reference',{}).get('conversion')
    if reference is not None and not math.isfinite(float(reference)):reference=None
    arms={}
    for role,tag in [('control','q7a'),('candidate','q7b')]:
        label=public_label('v3-lfm-'+tag+'-k',labels)
        if label.startswith('v3-'):raise ValueError('Public labels must be opaque')
        matches=[v for v in versions if v.get('model_version')==label]
        if len(matches)>1:raise ValueError('Duplicate model rows')
        v=matches[0] if matches else None
        n=int(v.get('requests',0)) if v else 0
        conversion=float(v['conversion']) if v and n else None
        arms[role]=dict(public_label=label,requests=n,conversion=conversion,
                       delta_vs_reference_pp=(conversion-float(reference) if conversion is not None and reference is not None else None),
                       status='observed' if n else 'missing/suppressed; not zero')
    a,b=arms['control'],arms['candidate']
    return dict(mode=state.get('mode'),updated_at=state.get('updated_at'),window=state.get('window'),
        reference_conversion=reference,arms=arms,
        candidate_minus_control_pp=(b['conversion']-a['conversion'] if a['conversion'] is not None and b['conversion'] is not None else None),
        team_on_time=row.get('on_time'),
        limitations=['Returning users with recent views only; exclude home/new-user rows and never average version rows equally.',
          'Reference is for the whole shared traffic, not a matched returning-user cohort; use it as same-window context.',
          'Expected conversion is not a binomial realized-purchase rate; aggregates lack user-level variance and do not prove significance.',
          'Stable-user arms may have different shopper mixes. Predeclare a window, inspect sample sizes, repeat; no automatic promotion.',
          'Only successfully attributed version rows are visible; check private feedback for missing/invalid answers too.'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    source=p.add_mutually_exclusive_group(required=True)
    source.add_argument('--state',type=Path,help='Cached public leaderboard JSON; no network')
    source.add_argument('--from',dest='start',type=int,help='Exact window start in epoch seconds, multiple of 300')
    p.add_argument('--to',dest='end',type=int,help='Exact window end in epoch seconds, multiple of 300')
    p.add_argument('--labels',type=Path,default=ROOT/'recsys/data/labels.json'); p.add_argument('--team',default='team_26')
    a=p.parse_args()
    if a.start is not None and (a.end is None or a.start%300 or a.end%300 or not 900<=a.end-a.start<=10800):
        p.error('Supply --from and --to aligned to 300 seconds, covering 15 minutes to 3 hours')
    if a.state and a.end is not None:p.error('--to requires --from')
    labels=json.loads(a.labels.read_text())
    state=json.loads(a.state.read_text()) if a.state else fetch(a.start,a.end)
    if a.start is not None and (not state.get('custom') or state.get('window')!=[a.start,a.end]):
        raise ValueError('Server returned a different window; do not compare it as the requested block')
    print(json.dumps(summarize(state,labels,a.team),indent=2,allow_nan=False))
