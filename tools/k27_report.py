"""Read public per-version results for K27. Never writes policy or submissions."""
import argparse
import json
import urllib.request
from pathlib import Path

URL = 'https://datathon.rawtree.dev/api/state?by=model'


def summarize(state, team_id='team_26'):
    team = next((t for t in state.get('teams', []) if t.get('team_id') == team_id), {})
    versions = {r['model_version']:r for r in team.get('versions', [])}
    arms = {}
    for name, good, guard in [('A','k27a','k27c'),('B','k27b','k27d')]:
        rows = [versions[v] for v in (good,guard) if v in versions]
        n = sum(r['requests'] for r in rows)
        cold_n = sum(r.get('cold_requests',0) for r in rows)
        g = versions.get(guard,{}).get('requests',0)
        def weighted(metric, denominator='requests'):
            count = sum(r.get(denominator,0) for r in rows)
            if not count: return None
            if any(r.get(metric) is None for r in rows if r.get(denominator,0)): return None
            return sum(r.get(metric,0)*r.get(denominator,0) for r in rows)/count
        arms[name] = dict(requests=n, guarded_requests=g, guard_fraction=g/n if n else None,
            conversion_pct=weighted('conversion'), cold_requests=cold_n,
            cold_conversion_pct=weighted('cold_conversion','cold_requests'),
            revenue_per_request=weighted('revenue_per_request'),
            first=min((r['first'] for r in rows),default=None),
            last=max((r['last'] for r in rows),default=None))
    a,b=arms['A'],arms['B']
    delta = b['conversion_pct']-a['conversion_pct'] if a['conversion_pct'] is not None and b['conversion_pct'] is not None else None
    return dict(updated_at=state.get('updated_at'), window=state.get('window'), mode=state.get('mode'),
        team=team_id, team_hour_on_time_pct=team.get('on_time'), arms=arms,
        conversion_delta_pp_B_minus_A=delta,
        status='collect_more_data' if min(a['requests'],b['requests']) < 500 else 'review_concurrent_windows_and_health',
        limitations=[
            'Combines served guard versions with their assigned arms; does not silently discard guarded answers.',
            'Public version rows may omit unsubmitted/expired fallback requests. This is not a complete intention-to-treat estimate; audit all target requests/feedback by the same stable user assignment.',
            '500 per arm is a planning minimum, not a statistical significance guarantee. No confidence interval can be recovered from these aggregate means alone.',
            'Do not count overlapping hourly snapshots as independent trials or compare target-only arms against whole-traffic/new-shopper rows. No automatic promotion.'])


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot',type=Path,help='Read cached public JSON instead of network')
    p.add_argument('--team',default='team_26')
    a=p.parse_args()
    if a.snapshot:
        state=json.loads(a.snapshot.read_text(encoding='utf-8'))
    else:
        with urllib.request.urlopen(URL,timeout=15) as response: state=json.load(response)
    print(json.dumps(summarize(state,a.team),indent=2))
