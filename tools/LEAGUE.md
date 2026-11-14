# Chronological offline league

Run from the repository root with the existing team environment (no installs):

```powershell
$py = 'C:\Projects\datathonFME\datathon-env\Scripts\python.exe'
& $py tools/local_league.py prepare --sample 10000
& $py tools/local_league.py validation --bootstrap 500
& $py -m unittest discover -s tests -v
# After selecting policies/configuration using validation ONLY:
& $py tools/local_league.py freeze --policies baseline,mixed_category
# Deliberately opens final test ONCE; do not run during model development:
& $py tools/local_league.py test --policies baseline,mixed_category --bootstrap 1000
```

`prepare` only queries shared tables; this code never writes submissions or starts the live starter. Cached evaluation needs no network. The default directory is `data/local_eval/league_v2`; use `--cache PATH` on every command for another experiment. Never create a new split to evade a disappointing final result. The test period has been downloaded and checksummed, but has NOT been scored during framework development.

Coverage is queried before cutoffs are chosen. The overlapping sessions/events range is divided chronologically 70%/15%/15%, with half-open intervals [start,end). `manifest.json` records coverage, boundaries, deterministic seed, and SHA256 hashes. Hash-order sampling followed by chronological sorting is repeatable against the same source data. `train.json`, `validation.json`, `test.json`, and `catalog.json` are independently cached. Completed snapshots are immutable; partial preparation resumes cached periods under an identical plan. Keep caches private and backed up; source database changes can prevent bit-identical reconstruction after deletion. Existing legacy holdout IDs are excluded from every period and their count/hash recorded, since those rewards were already inspected. Preserve that legacy file for future preparations.

`fit(training_snapshot)` receives ONLY sampled training sessions and organic popularity aggregated within the training interval. Every registered policy is freshly fit per invocation. Validation/test rewards, logged items and propensities are withheld from `recommend(request, features, catalog) -> list[str]`. Features currently are an empty mapping. Catalog is a read-only eligible as-of mapping; requests use an explicit field allowlist and omit future recent views. The training snapshot includes the catalog immediately before training starts. A richer trainer must construct its own within-training as-of features; do not use end-of-training state for earlier training examples. No unshown item is labeled a negative by this harness.

To add an independent implementation, make an importable module such as `tools/my_policy.py`:

```python
from tools.league_policies import register

@register('my_policy')
class MyPolicy:
    def fit(self, training):
        self.best = list(training['best'])

    def recommend(self, request, features, catalog):
        return [p for p in self.best if p in catalog][:10]
```

Run `python -m tools.local_league validation --plugin tools.my_policy --policies baseline,my_policy`. Use the same plugin/policy arguments for freeze/test. Missing or duplicate registrations fail. Keep deterministic hyperparameters/seeds in versioned module code. Plugins are trusted local Python, not a security sandbox: no external data reads, network, or validation/test access inside plugins. Freeze hashes tools modules and plugin entry modules plus snapshot manifest; external dependencies, transitive modules, external config and weights must be separately versioned/audited. Do not mutate configuration after freeze. Test access writes `TEST_OPENED.json` before evaluation, prevents reruns and closes validation tuning. Reuse `test_report.json` thereafter. This is a procedural safeguard, not protection against manually reading files.

Reports preserve clicked-item `hit@10` (denominator: logged clicks), IPS/SNIPS slot-1 purchase and click estimates, match counts and ESS. Inverse weights are unmodified/unclipped; maximum weight and malformed propensity rows are reported. IPS uses all impressions as denominator; rows without usable slot-1 propensity contribute zero. Investigate missingness before interpreting IPS. Invalid outputs also contribute zero action and disqualify a policy; their proxy metrics must not be used for selection. Validity checks exact length, unique real string IDs and eligibility against reconstructed catalog. Exceptions are counted. Latency p50/p95/p99/max measures local inference plus request copying; it excludes catalogue replay, polling, network and submission and cannot establish the live three-second SLA.

Seeded paired UTC-hour block bootstrap percentile 95% intervals are reported for proxy metrics and differences versus the first listed reference policy. These approximate temporal-dependence intervals are not guarantees: users can recur across blocks, rare purchases/matches can give degenerate intervals, low ESS is unreliable, and repeated tuning/multiple comparisons inflate selection bias. No support means null SNIPS/intervals, not zero evidence of benefit. More bootstrap replicates do not fix weak support or bias.

The as-of catalogue excludes products created after the request and applies available full-state updates up through its timestamp, including prices and stock changes. Base catalogue is assumed to be initial state as documented. Its field history is unavailable, so past category/price/stock correctness cannot be verified; missing pre-base updates are unrecoverable. Equal-timestamp conflicting updates have no documented sequence. Validity is therefore conditional on reconstructed metadata, not proven historical inventory. Historical new-user/cold flags are not reliably supplied and official cold-start performance is not established.

These are OFFLINE ESTIMATES on exposure-/position-biased logged impressions. Slot-1 IPS assumes correct logging propensity and support for the first action; other slots and slate interactions remain uncontrolled. They do not identify actual full-slate conversion or the hidden expected-purchase score. No model promotion or live change follows automatically. Rollback: keep the existing live champion; discard offline changes/cache if necessary.
