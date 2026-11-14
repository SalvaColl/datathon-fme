"""Prepare a reviewable K30 policy JSON. Never edits the live policy or starts anything."""
import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from recsys import lfm,live

ROOT=Path(__file__).resolve().parent.parent


def plan(policy,champion_tag=None):
    if policy.get('variant')!='lfm':raise ValueError('Requires the existing lfm variant')
    arms=live.clean_lfm_arms(policy.get('lfm_arms'))
    selected=[a for a in arms if champion_tag is None or a['tag']==champion_tag]
    if len(selected)!=1:raise ValueError('Select exactly one champion with --champion-tag')
    winner=selected[0]
    if winner.get('file')!='lfm_coef_r2.json':
        raise ValueError('This artifact clones r2 only; another champion needs a separately reviewed coefficient clone')
    root=Path(lfm.__file__).parent
    candidate=json.loads((root/'lfm_coef_k30.json').read_text())
    base=json.loads((root/'lfm_coef_r2.json').read_text())
    if any(candidate[k]!=base[k] for k in ('known','new','lq0')) or candidate.get('score_patch')!='k30':
        raise ValueError('Candidate is not an exact coefficient clone')
    if hashlib.sha256((root/'lfm_coef_r2.json').read_bytes()).hexdigest()!=candidate['meta']['k30_base_sha256']:
        raise ValueError('Base artifact changed; review and regenerate the clone first')
    control={**copy.deepcopy(winner),'tag':'q7a'}
    treatment={**copy.deepcopy(winner),'tag':'q7b','file':'lfm_coef_k30.json'}
    result=copy.deepcopy(policy); result['lfm_arms']=[control,treatment]
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--policy',type=Path,default=ROOT/'recsys/data/policy.json')
    p.add_argument('--champion-tag'); p.add_argument('--labels',type=Path,default=ROOT/'recsys/data/labels.json')
    p.add_argument('--out',type=Path,default=ROOT/'data/local_eval/k30_plan.json')
    a=p.parse_args()
    if a.out.resolve()==a.policy.resolve():p.error('Output must differ from the live policy; this tool only prepares a plan')
    if not json.loads(a.labels.read_text()).get('salt'):raise ValueError('Private opaque label mask must exist; do not publish it')
    proposed=plan(json.loads(a.policy.read_text()),a.champion_tag)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(proposed,indent=2)+'\n',encoding='utf-8')
    print('Review-only plan written to',a.out,'; live policy unchanged')
