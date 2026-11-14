"""Training-defined masked-item validation; never reads a final test or writes submissions."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import platform

import numpy
import scipy
import sklearn

from tools.content_linear import ContentLinear, heldout_ids
from tools.league_metrics import evaluate
from tools.league_policies import Popularity
from tools.local_league import Catalog, check_period, digest, load, save


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cache', type=Path, default=Path('data/local_eval/content_t021'))
    p.add_argument('--bootstrap', type=int, default=500)
    a = p.parse_args()
    if (a.cache / 'TEST_OPENED.json').exists():
        raise ValueError('Validation tuning closed')
    manifest = json.loads((a.cache / 'manifest.json').read_text())
    training = load(a.cache, 'train.json', manifest)
    validation = load(a.cache, 'validation.json', manifest)
    metadata = load(a.cache, 'catalog.json', manifest)
    check_period(training['requests'], *manifest['boundaries'][:2])
    check_period(validation['requests'], *manifest['boundaries'][1:3])
    mask = heldout_ids(training['catalog'])
    cold = copy.deepcopy(training)
    cold['withheld_product_ids'] = sorted(mask)
    cold['best'] = [pid for pid in cold['best'] if pid not in mask]
    cold['organic_events'] = [e for e in cold['organic_events'] if e['product_id'] not in mask]
    models = {'masked_baseline': Popularity(), 'masked_content_only': ContentLinear(False),
              'masked_content_linear': ContentLinear()}
    for name, model in models.items():
        print(f'Fitting {name}', flush=True)
        model.fit(copy.deepcopy(cold))
    report = evaluate(models, validation['requests'], Catalog(metadata), a.bootstrap)
    subset = [r for r in validation['requests'] if any(v.get('product_id') in mask for v in (r.get('recent_views') or []) if isinstance(v, dict))]
    report['masked_view_subset'] = evaluate(models, subset, Catalog(metadata), a.bootstrap)
    report['mask_count'] = len(mask)
    report['mask_sha256'] = digest(sorted(mask))
    report['manifest_sha256'] = digest(manifest)
    report['training_diagnostics'] = {k: m.diagnostics for k, m in models.items() if hasattr(m, 'diagnostics')}
    report['environment'] = {'python': platform.python_version(), 'numpy': numpy.__version__,
                             'scipy': scipy.__version__, 'sklearn': sklearn.__version__}
    report['sources'] = {str(f): hashlib.sha256(f.read_bytes()).hexdigest() for f in
                         [Path('tools/content_linear.py'), Path('tools/content_validate.py')]}
    report['simulation_limitation'] = ('TRAINING-defined deterministic 20% item mask: removed from vocabulary, '
        'organic profiles, popularity and supervised exposures; available with content only during validation. '
        'Not actual launches or official cold requests; remaining products may share attributes and users. '
        'Mask selected without validation outcomes; no final test read. Historical metadata remains conditional.')
    save(a.cache / 'masked_validation_report.json', report)
    print(json.dumps({k: {m: r[m] for m in ['SNIPS_slot1_buy', 'ESS', 'hit@10', 'valid_top10_rate']}
                      for k, r in report['results'].items()}, indent=2))


if __name__ == '__main__':
    main()
