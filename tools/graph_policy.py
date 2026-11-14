"""Item-to-item graph policies for the offline league (T-020). Offline only: no serving code, no network.

    python -m tools.local_league validation --plugin tools.graph_policy \\
        --policies baseline,mixed_category,rv_first,graph_A,graph_B,graph_C,graph_B_rv,graph_B_rv_profile

Artifacts come from `python -m tools.graph_build --pin` (training-period organic events only). fit() refuses an artifact
whose SHA256 is not pinned in tools/graph_pins.py or whose training window differs from the league's training snapshot.

recommend(): seeds = eligible-or-not recent views (most recent first, weight DECAY**k, at most MAX_SEEDS) plus, for
*_profile, the user's training-period top products (weight PROFILE_W, normalised). Neighbour scores are summed;
ineligible products are dropped; *_rv puts the eligible recent views first (most recent first). Fallback: training
purchase popularity in the last viewed category, then global, then any eligible product (deterministic). Always 10
distinct eligible ids when the catalog has >= 10 eligible products; otherwise as many as exist (unsatisfiable, and the
league marks it invalid).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.league_policies import register

ARTIFACTS = Path(__file__).resolve().parent.parent / "data" / "graph"
DECAY, MAX_SEEDS, PROFILE_W = 0.7, 5, 0.3


def _load(name: str, training: dict) -> dict:
    from tools import graph_pins  # imported lazily so the module registers even before a build
    path = ARTIFACTS / f"{name}.json"
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != graph_pins.PINS.get(name):
        raise ValueError(f"{path}: SHA256 not pinned in tools/graph_pins.py (rebuild with --pin and review)")
    art = json.loads(raw)
    prov = art["provenance"]
    if (prov["train_start"], prov["train_end"]) != (training["start"], training["end"]):
        raise ValueError(f"{name}: artifact window {prov['train_start']}..{prov['train_end']} != league training "
                         f"{training['start']}..{training['end']} (leakage guard)")
    return art


def _views(request) -> list[str]:
    out = []
    for v in request.get("recent_views") or []:
        p = v.get("product_id") if isinstance(v, dict) else v
        if isinstance(p, str) and p:
            out.append(p)
    return out


class GraphPolicy:
    def __init__(self, graph: str | None, rv_first: bool = False, profile: bool = False):
        self.graph_name, self.rv_first, self.use_profile = graph, rv_first, profile

    def fit(self, training):
        self.best = list(dict.fromkeys(training.get("best") or []))
        self.adj = {a: [(b, s) for b, s, *_ in nbrs] for a, nbrs in _load(self.graph_name, training)["adj"].items()} \
            if self.graph_name else {}
        self.prof = {u: [(i, w) for i, w in items] for u, items in _load("profiles", training)["profiles"].items()} \
            if self.use_profile else {}
        self._catalog = None

    def _prepare(self, catalog):
        """Per-catalog-snapshot cache: popularity order restricted to eligible ids, grouped by category."""
        if catalog is self._catalog:
            return
        best = [p for p in self.best if p in catalog]
        seen = set(best)
        best += sorted(p for p in catalog if p not in seen)
        self._best, self._by_cat = best, {}
        for p in best:
            self._by_cat.setdefault((catalog[p] or {}).get("category"), []).append(p)
        self._catalog = catalog

    def scores(self, request) -> dict[str, float]:
        sc: dict[str, float] = {}
        views = list(dict.fromkeys(reversed(_views(request))))[:MAX_SEEDS]   # most recent first, deduplicated
        seeds = [(p, DECAY ** k) for k, p in enumerate(views)]
        if self.use_profile:
            items = self.prof.get(request.get("user_id"), [])
            tot = sum(w for _, w in items) or 1.0
            seeds += [(i, PROFILE_W * w / tot) for i, w in items]
        for seed, ws in seeds:
            for nb, s in self.adj.get(seed, ()):
                sc[nb] = sc.get(nb, 0.0) + ws * s
        return sc

    def recommend(self, request, features, catalog):
        self._prepare(catalog)
        views = list(dict.fromkeys(reversed(_views(request))))           # most recent first
        out, seen = [], set()
        def take(seq):
            for p in seq:
                if p not in seen and p in catalog:
                    seen.add(p); out.append(p)
                    if len(out) == 10:
                        return True
            return False
        if self.rv_first and take(views):
            return out
        sc = self.scores(request)
        if sc and take(sorted(sc, key=lambda p: (-sc[p], p))):
            return out
        last_cat = next(((catalog[p] or {}).get("category") for p in views if p in catalog), None)
        if last_cat is not None and take(self._by_cat.get(last_cat, [])):
            return out
        take(self._best)
        return out


for _name, _kw in {
    "rv_first": dict(graph=None, rv_first=True),              # simple recent-view policy (no graph) for attribution
    "graph_A": dict(graph="graph_A"),
    "graph_B": dict(graph="graph_B"),
    "graph_C": dict(graph="graph_C"),
    "graph_B_rv": dict(graph="graph_B", rv_first=True),
    "graph_B_rv_profile": dict(graph="graph_B", rv_first=True, profile=True),
}.items():
    register(_name)(lambda kw=_kw: GraphPolicy(**kw))
