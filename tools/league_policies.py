"""Offline policy plugin contract. No serving/network code.

Register a factory with register(name). factory() returns an object implementing
fit(training_snapshot) and recommend(request, features, catalog). fit receives
ONLY training data; recommend receives no shown/propensity/reward fields.
Use deterministic seeds internally. Never perform data access from a plugin.
"""
from copy import deepcopy

REGISTRY = {}


def register(name):
    def decorate(factory):
        if name in REGISTRY:
            raise ValueError(f"Duplicate policy: {name}")
        REGISTRY[name] = factory
        return factory
    return decorate


class Popularity:
    def __init__(self, mode="baseline"):
        self.mode = mode

    def fit(self, training):
        self.best = list(training["best"])
        self._catalog = None

    def recommend(self, request, features, catalog):
        if catalog is not self._catalog:
            best = [p for p in self.best if p in catalog]
            best += sorted(set(catalog) - set(best))
            self._best = best
            self._groups = {'category': {}, 'subcategory': {}}
            for p in best:
                for field, groups in self._groups.items():
                    groups.setdefault(catalog[p].get(field), []).append(p)
            self._catalog = catalog
        best = self._best
        views = request.get("recent_views") or []
        last = catalog.get(views[-1].get("product_id"), {}) if views else {}
        sub, cat = last.get("subcategory"), last.get("category")
        def first_matching(field, target, limit):
            if not target:
                return []
            return self._groups[field].get(target, [])[:limit]
        preferred = []
        if self.mode == 'same_category':
            preferred = first_matching('category', cat, 10)
        elif self.mode == 'same_subcategory':
            preferred = first_matching('subcategory', sub, 10)
        elif self.mode == 'mixed_category':
            preferred = first_matching('subcategory', sub, 5) + first_matching('category', cat, 10)
        output, seen = [], set()
        from itertools import chain
        for p in chain(preferred, best):
            if p not in seen:
                seen.add(p)
                output.append(p)
                if len(output) == 10:
                    break
        return output


for _name in ("baseline", "same_category", "same_subcategory", "mixed_category"):
    register(_name)(lambda mode=_name: Popularity(mode))


def train(names, snapshot):
    models = {}
    for name in names:
        model = REGISTRY[name]()
        model.fit(deepcopy(snapshot))
        models[name] = model
    return models
