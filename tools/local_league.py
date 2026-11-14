"""Read-only league: prepare, validation, freeze, test. See LEAGUE.md."""
from __future__ import annotations
import argparse
import hashlib
import importlib
import json
import sys
from bisect import bisect_right
from datetime import datetime, timedelta, timezone
from pathlib import Path
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.league_data import sql, ROOT
from tools.league_policies import train
from tools.league_metrics import evaluate


def stamp(value):
    t = datetime.fromisoformat(str(value).replace('Z', '+00:00').replace(' ', 'T'))
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)


def iso(t):
    return stamp(t).isoformat(timespec='milliseconds')


def sqltime(t):
    return stamp(t).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')


def boundaries(coverage):
    lo, hi = (stamp(coverage['sessions'][k]) for k in ('lo', 'hi'))
    elo, ehi = (stamp(coverage['events'][k]) for k in ('lo', 'hi'))
    lo, hi = max(lo, elo), min(hi, ehi)
    if hi-lo < timedelta(days=3):
        raise ValueError('Insufficient overlapping history coverage')
    span = hi-lo
    return [iso(lo), iso(lo+span*.70), iso(lo+span*.85), iso(hi+timedelta(milliseconds=1))]


def check_period(rows, start, end):
    ids = set()
    for row in rows:
        if not stamp(start) <= stamp(row['ts']) < stamp(end):
            raise ValueError('Split leakage: timestamp outside period')
        if row['request_id'] in ids:
            raise ValueError('Duplicate request ID')
        ids.add(row['request_id'])


def prepare(directory, sample, seed):
    directory.mkdir(parents=True, exist_ok=True)
    if (directory/'manifest.json').exists():
        raise ValueError('Immutable snapshot exists: choose a new --cache directory')
    coverage = {}
    for name, table in [('sessions', 'history_sessions'), ('events', 'history_events')]:
        coverage[name] = sql(f'SELECT min(ts::DateTime64(3)) AS lo, max(ts::DateTime64(3)) AS hi, count() AS n FROM shop.{table}')[0]
    cuts = boundaries(coverage)
    legacy = ROOT/'data/local_eval/holdout.json'
    excluded = {r['request_id'] for r in json.loads(legacy.read_text())['requests']} if legacy.exists() else set()
    plan = {'boundaries': cuts, 'sample': sample, 'seed': seed, 'excluded_ids_sha256': digest(sorted(excluded)), 'excluded_count': len(excluded)}
    plan_path = directory/'plan.json'
    if plan_path.exists() and json.loads(plan_path.read_text()) != plan:
        raise ValueError('Partial snapshot plan changed: choose a new directory')
    save(plan_path, plan)
    print(json.dumps({'coverage': coverage, 'boundaries': cuts}), flush=True)
    save(directory/'coverage.json', coverage)
    files, seen = {}, set()
    for i, name in enumerate(('train', 'validation', 'test')):
        start, end = cuts[i:i+2]
        path = directory/f'{name}.json'
        if path.exists():
            snapshot = json.loads(path.read_text())
            check_period(snapshot['requests'], start, end)
            ids = {r['request_id'] for r in snapshot['requests']}
            if ids & (seen | excluded):
                raise ValueError('Overlapping split IDs or legacy holdout exposure')
            seen.update(ids)
            files[f'{name}.json'] = digest(snapshot)
            continue
        qstart, qend = sqltime(start), sqltime(end)
        rows = sql(f"""SELECT request_id::String AS request_id, ts::String AS ts,
            user_id, context, recent_views, shown, propensity, clicked, purchased
            FROM shop.history_sessions WHERE ts::DateTime64(3) >= '{qstart}'
            AND ts::DateTime64(3) < '{qend}'
            ORDER BY cityHash64(concat(request_id::String, '{seed}')), request_id::String LIMIT {sample+len(excluded)}""")
        rows = [r for r in rows if r['request_id'] not in excluded][:sample]
        rows.sort(key=lambda r: (stamp(r['ts']), r['request_id']))
        check_period(rows, start, end)
        ids = {r['request_id'] for r in rows}
        if ids & seen:
            raise ValueError('Overlapping split IDs')
        seen.update(ids)
        if not rows:
            raise ValueError(f'Empty {name} period')
        snapshot = {'start': start, 'end': end, 'requests': rows}
        if name == 'train':
            snapshot['best'] = [r['product_id'] for r in sql(f"""SELECT product_id::String AS product_id,
                count() AS n FROM shop.history_events WHERE event_type = 'purchase'
                AND ts::DateTime64(3) >= '{qstart}' AND ts::DateTime64(3) < '{qend}'
                GROUP BY product_id ORDER BY n DESC, product_id DESC LIMIT 10000""")]
        save(directory/f'{name}.json', snapshot)
        files[f'{name}.json'] = digest(snapshot)
    if (directory/'catalog.json').exists():
        metadata = json.loads((directory/'catalog.json').read_text())
    else:
        catalog = sql('SELECT product_id::String AS product_id, category, subcategory, brand, price_eur, created_at, is_active FROM shop.catalog')
        updates = sql(f"SELECT * FROM shop.catalog_updates WHERE ts::DateTime64(3) < '{sqltime(cuts[-1])}' ORDER BY ts::DateTime64(3), product_id::String")
        metadata = {'base': catalog, 'updates': updates, 'limitation':
            'Base catalog lacks field-level history: pre-event category/price/stock changes cannot be verified or reconstructed. Initial base state is assumed; no current merged catalog used. Unknown created_at excluded.'}
    save(directory/'catalog.json', metadata)
    files['catalog.json'] = digest(metadata)
    save(directory/'manifest.json', {'version': 2, 'coverage': coverage, 'boundaries': cuts,
        'sample_per_period': sample, 'seed': seed, 'exclusions': plan, 'files': files})


def load(directory, filename, manifest):
    value = json.loads((directory/filename).read_text(encoding='utf-8'))
    if digest(value) != manifest['files'][filename]:
        raise ValueError(f'Snapshot checksum mismatch: {filename}')
    return value


class Catalog:
    def __init__(self, metadata):
        self.base = metadata['base']
        self.updates = sorted(metadata['updates'], key=lambda r: stamp(r['ts']))
        self.revisions = sorted({stamp(r['created_at']) for r in self.base if r.get('created_at')}
                                | {stamp(r['ts']) for r in self.updates})
        self.cached_key, self.cached_state = None, None

    def at(self, ts):
        t = stamp(ts)
        key = bisect_right(self.revisions, t)
        if key == self.cached_key:
            return self.cached_state
        state = {r['product_id']: dict(r) for r in self.base
                 if r.get('created_at') and stamp(r['created_at']) <= t}
        for update in self.updates:
            if stamp(update['ts']) > t:
                break
            p = update['product_id']
            state[p] = {**state.get(p, {}), **update}
            if update.get('change') == 'out_of_stock':
                state[p]['is_active'] = False
            elif update.get('change') in ('back_in_stock', 'new_product'):
                state[p]['is_active'] = True
        self.cached_key = key
        self.cached_state = {p: r for p, r in state.items() if r.get('is_active') in (True, 1, 'true')}
        return self.cached_state


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['prepare', 'validation', 'freeze', 'test'])
    p.add_argument('--cache', type=Path, default=ROOT/'data/local_eval/league_v2')
    p.add_argument('--sample', type=int, default=10000)
    p.add_argument('--seed', type=int, default=20261114)
    p.add_argument('--policies', default='baseline,same_category,same_subcategory,mixed_category')
    p.add_argument('--plugin', action='append', default=[])
    p.add_argument('--bootstrap', type=int, default=500)
    a = p.parse_args()
    if a.sample < 1 or a.bootstrap < 0:
        p.error('sample must be positive; bootstrap must be nonnegative')
    if a.command == 'prepare':
        prepare(a.cache, a.sample, a.seed)
        return
    for module in a.plugin:
        importlib.import_module(module)
    manifest = json.loads((a.cache/'manifest.json').read_text())
    training = load(a.cache, 'train.json', manifest)
    check_period(training['requests'], *manifest['boundaries'][:2])
    metadata = load(a.cache, 'catalog.json', manifest)
    training['catalog'] = Catalog(metadata).at(iso(stamp(training['start'])-timedelta(milliseconds=1)))
    names = a.policies.split(',')
    fingerprint = {'manifest': digest(manifest), 'policies': names, 'plugins': a.plugin,
        'sources': {str(f.relative_to(ROOT)): hashlib.sha256(f.read_bytes()).hexdigest()
                    for f in sorted((ROOT/'tools').glob('*.py'))},
        'plugin_sources': {m: hashlib.sha256(Path(importlib.import_module(m).__file__).read_bytes()).hexdigest() for m in a.plugin}}
    freeze_path = a.cache/'frozen.json'
    if a.command == 'freeze':
        if freeze_path.exists():
            raise ValueError('Already frozen')
        save(freeze_path, fingerprint)
        print('Frozen code/policies/snapshot; final test remains unopened.')
        return
    if a.command == 'test':
        if json.loads(freeze_path.read_text()) != fingerprint:
            raise ValueError('Frozen policy/code/snapshot mismatch')
        marker = a.cache/'TEST_OPENED.json'
        if marker.exists():
            raise ValueError('Final test already opened: reuse saved report; no retuning')
        save(marker, fingerprint)
    elif (a.cache/'TEST_OPENED.json').exists():
        raise ValueError('Validation tuning closed after final test access')
    models = train(names, training)
    period = load(a.cache, a.command+'.json', manifest)
    idx = 1 if a.command == 'validation' else 2
    check_period(period['requests'], *manifest['boundaries'][idx:idx+2])
    if {r['request_id'] for r in training['requests']} & {r['request_id'] for r in period['requests']}:
        raise ValueError('Request ID leakage')
    report = evaluate(models, period['requests'], Catalog(metadata), a.bootstrap, a.seed)
    report.update({'fingerprint': fingerprint, 'period': a.command, 'catalog_limitation': metadata['limitation']})
    save(a.cache/(a.command+'_report.json'), report)
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
