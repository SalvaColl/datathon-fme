"""Request-level slot-1 proxies with paired hourly-block bootstrap intervals."""
import math
import hashlib
import json
import random
import time
from collections import defaultdict
from copy import deepcopy
from datetime import datetime
from types import MappingProxyType


def percentile(values, q):
    if not values:
        return None
    v = sorted(values)
    x = (len(v)-1)*q
    lo = int(x)
    return v[lo] + (v[min(lo+1, len(v)-1)]-v[lo])*(x-lo)


def valid(items, catalog):
    return (isinstance(items, list) and len(items) == 10
            and all(isinstance(p, str) and p in catalog for p in items)
            and len(set(items)) == 10)


def ratios(s):
    n, clicks, hits, matches, w, w2, wc, wb = s
    return {'hit@10': hits/clicks if clicks else None,
            'IPS_slot1_click': wc/n if n else None,
            'IPS_slot1_buy': wb/n if n else None,
            'SNIPS_slot1_click': wc/w if w else None,
            'SNIPS_slot1_buy': wb/w if w else None,
            'slot1_matches': matches, 'ESS': w*w/w2 if w2 else 0}


def total(rows):
    return [sum(r[i] for r in rows) for i in range(8)]


def evaluate(models, records, catalog, bootstrap=500, seed=20261114):
    blocks = {name: defaultdict(lambda: [0.0]*8) for name in models}
    times = {name: [] for name in models}
    invalid = defaultdict(int)
    exceptions = defaultdict(int)
    bad_propensity = 0
    max_weight = 0
    agreement = defaultdict(int)
    errors = {name: [] for name in models}
    prediction_hashes = {name: hashlib.sha256() for name in models}
    previous_catalog, readonly_catalog = None, None
    for row in records:
        eligible = catalog.at(row['ts'])
        if eligible is not previous_catalog:
            readonly_catalog = MappingProxyType({p: MappingProxyType(r) for p, r in eligible.items()})
            previous_catalog = eligible
        # Explicit allowlist: no reward, logged action, propensity, or future views.
        request = {k: deepcopy(row[k]) for k in ('request_id', 'ts', 'user_id', 'context', 'recent_views', 'is_new_user') if k in row}
        views = request.get('recent_views') or []
        def parse(t):
            return datetime.fromisoformat(str(t).replace('Z', '+00:00').replace(' ', 'T')).replace(tzinfo=None)
        request['recent_views'] = [v for v in views if isinstance(v, dict) and (not v.get('ts') or parse(v['ts']) <= parse(row['ts']))]
        outputs = {}
        for name, model in models.items():
            start = time.perf_counter_ns()
            try:
                items = model.recommend(deepcopy(request), {}, readonly_catalog)
            except Exception as exc:
                exceptions[name] += 1
                if len(errors[name]) < 5:
                    errors[name].append(type(exc).__name__)
                items = None
            times[name].append((time.perf_counter_ns()-start)/1e6)
            ok = valid(items, eligible)
            invalid[name] += int(not ok)
            outputs[name] = items if ok else []
            prediction_hashes[name].update(json.dumps([row['request_id'], outputs[name]], separators=(',', ':')).encode())
        names = list(models)
        for i, name in enumerate(names):
            for other in names[i+1:]:
                if outputs[name] and outputs[other] and outputs[name][0] == outputs[other][0]:
                    agreement[name+' / '+other] += 1
        shown, prop = row.get('shown') or [], row.get('propensity') or []
        try:
            p = float(prop[0])
            usable = bool(shown) and math.isfinite(p) and 0 < p <= 1
        except (IndexError, TypeError, ValueError):
            usable = False
        bad_propensity += int(not usable)
        for name, items in outputs.items():
            clicked = row.get('clicked') not in (None, '')
            match = bool(usable and items and items[0] == shown[0])
            w = 1/p if match else 0.0
            max_weight = max(max_weight, w)
            contribution = [1, int(clicked), int(clicked and row['clicked'] in items), int(match), w, w*w,
                            w*int(match and row.get('clicked') == shown[0]),
                            w*int(match and row.get('purchased') == shown[0])]
            # UTC hour blocks preserve short-range dependence; paired draws across policies.
            block = parse(row['ts']).strftime('%Y-%m-%dT%H')
            blocks[name][block] = [a+b for a, b in zip(blocks[name][block], contribution)]
    keys = sorted(set(k for values in blocks.values() for k in values))
    rng = random.Random(seed)
    draws = [[rng.choice(keys) for _ in keys] for _ in range(bootstrap)] if keys else []
    report = {}
    metrics = ['hit@10', 'IPS_slot1_click', 'IPS_slot1_buy', 'SNIPS_slot1_click', 'SNIPS_slot1_buy']
    boot_results = {}
    for name in models:
        result = ratios(total(list(blocks[name].values())))
        samples = [ratios(total([blocks[name][k] for k in draw])) for draw in draws]
        boot_results[name] = samples
        result['CI95_hour_block_percentile'] = {m: [percentile([r[m] for r in samples if r[m] is not None], q) for q in (.025, .975)] for m in metrics}
        result['valid_top10_rate'] = 1-invalid[name]/len(records) if records else None
        result['invalid_outputs'] = invalid[name]
        result['exceptions'] = exceptions[name]
        result['exception_examples'] = errors[name]
        result['latency_ms'] = {k: percentile(times[name], q) for k, q in [('p50', .5), ('p95', .95), ('p99', .99), ('max', 1)]}
        result['eligible_for_comparison'] = invalid[name] == 0
        result['prediction_sha256'] = prediction_hashes[name].hexdigest()
        report[name] = result
    paired = {}
    names = list(models)
    if names:
        ref = names[0]
        for name in names[1:]:
            paired[name+' minus '+ref] = {m: [percentile([a[m]-b[m] for a, b in zip(boot_results[name], boot_results[ref]) if a[m] is not None and b[m] is not None], q) for q in (.025, .975)] for m in metrics}
    return {'N': len(records), 'hour_blocks': len(keys), 'bootstrap_replicates': bootstrap,
        'results': report, 'paired_delta_CI95': paired,
        'first_slot_agreement_counts': dict(agreement), 'invalid_propensity_rows': bad_propensity,
        'max_unclipped_weight': max_weight,
        'limitations': ['OFFLINE ESTIMATE: no full-slate conversion identification; conditional logging support assumed only for slot 1.',
            'No weight clipping. Missing/invalid propensity contributes zero weight with full N IPS denominator; inspect missingness.',
            'Hourly block bootstrap is approximate, does not remove selection bias, user dependence across hours, or repeated-tuning bias.',
            'Latency includes request copy and inference, excludes catalog replay/wrapping, polling, RawTree, network and writes; not serving E2E.',
            'Validity refers to reconstructed eligible catalog; base historical stock is unverified. Invalid output disqualifies policy; proxy values then include zero-action failures.']}
