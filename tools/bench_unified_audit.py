"""Compare the deployed selector with the audited selector. Synthetic; no RawTree or model startup.

Run from the repository root: python tools/bench_unified_audit.py --base 16e14c6
This measures selection only, not inference, ingestion or network latency.
"""
import argparse
import ast
import json
from pathlib import Path
import subprocess
import sys
import textwrap
import time
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from recsys import lfm


def run(base="16e14c6", cases=1000, size=5400, seed=520):
    if cases < 1 or size < 100:
        raise ValueError("cases must be positive and size at least 100")
    source = subprocess.check_output(["git", "show", base + ":recsys/lfm.py"], cwd=ROOT, text=True)
    cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == "LiveFit")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "slate")
    namespace = {"np": np, "x_target": lambda *args: False}
    exec(textwrap.dedent(ast.get_source_segment(source, method)), namespace)
    old = namespace["slate"]
    rng = np.random.default_rng(seed)
    snapshot = SimpleNamespace(n=size, ids=["p" + str(k) for k in range(size)])
    timings = {"before": [], "after": []}
    matches = valid = 0
    for k in range(cases):
        scores = rng.integers(-5, 6, size).astype(float) if k % 3 == 0 else rng.normal(size=size)
        scores[rng.choice(size, 30, replace=False)] = -np.inf
        blocked = set(snapshot.ids[i] for i in
                      (np.argsort(-scores)[:45] if k % 4 == 0 else rng.choice(size, 25, replace=False)))
        ranker = SimpleNamespace(scores=lambda *args: (snapshot, scores), alt_x={})
        calls = {"before": lambda: old(ranker, {}, None, None, exclude=blocked),
                 "after": lambda: lfm.LiveFit.slate(ranker, {}, None, None, exclude=blocked)}
        outputs = {}
        for name in (["before", "after"] if k % 2 else ["after", "before"]):
            start = time.perf_counter_ns()
            outputs[name] = calls[name]()
            timings[name].append((time.perf_counter_ns() - start) / 1e6)
        matches += outputs["before"] == outputs["after"]
        slate = outputs["after"]
        valid += slate is not None and len(slate) == 10 and len(set(slate)) == 10 and not (set(slate) & blocked)
    result = dict(base=base, seed=seed, catalogue_size=size, cases=cases, identical_slates=matches, valid=valid,
                  selector_latency_ms={name: {"p95": round(float(np.quantile(values, .95)), 4),
                                               "p99": round(float(np.quantile(values, .99)), 4)}
                                       for name, values in timings.items()},
                  limitation="Synthetic selector only; not model inference or end-to-end latency")
    print(json.dumps(result))
    if matches != cases or valid != cases:
        raise AssertionError("Selector parity or output validity failed")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="16e14c6")
    parser.add_argument("--cases", type=int, default=1000)
    parser.add_argument("--size", type=int, default=5400)
    parser.add_argument("--seed", type=int, default=520)
    args = parser.parse_args()
    run(args.base, args.cases, args.size, args.seed)
