"""T-021: independent, network-free content retrieval and purchase logistic policy.

Only fit() consumes labels. No product/user ID is a regression feature. Organic
events are replayed strictly before each training impression; inference freezes
history at the training cutoff. Caller supplies an eligible catalogue snapshot.
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
import hashlib
import math

import numpy as np
from scipy import sparse
from sklearn.feature_extraction import DictVectorizer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import normalize

from tools.league_policies import register


def timestamp(value):
    t = datetime.fromisoformat(str(value).replace("Z", "+00:00").replace(" ", "T"))
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)


def price(row):
    try:
        value = float(row.get("price_eur", 0))
        return value if math.isfinite(value) and value > 0 else 0.0
    except (ValueError, TypeError):
        return 0.0


def active(row, when):
    if row.get("is_active", True) not in (True, 1, "true"):
        return False
    return not row.get("created_at") or timestamp(row["created_at"]) <= when


def heldout_ids(catalog, seed=20261114):
    """Predeclared 20% product mask, chosen without validation outcomes."""
    return {p for p in catalog if int(hashlib.sha256(f"{seed}:{p}".encode()).hexdigest()[:8], 16) % 5 == 0}


class ContentLinear:
    def __init__(self, learned=True, regularization=1.0, candidates=150):
        self.learned = learned
        self.regularization = regularization
        self.candidates = candidates

    @staticmethod
    def _metadata_features(row):
        return {f"{key}={row.get(key) or '__missing__'}": weight
                for key, weight in (("category", .8), ("subcategory", 1.0), ("brand", .5))}

    def _encode(self, rows):
        text = self.text.transform([str(r.get("description") or "") for r in rows])
        meta = self.metadata.transform([self._metadata_features(r) for r in rows])
        prices = np.array([math.log1p(price(r)) for r in rows])
        # Smooth price neighbourhoods, with centres/scaling fit on initial TRAIN catalogue.
        z = (prices - self.price_mean) / self.price_scale
        bands = .25 * np.exp(-.5 * (z[:, None] - np.array([-2., -1., 0., 1., 2.])) ** 2)
        return normalize(sparse.hstack([text, meta, sparse.csr_matrix(bands)], format="csr"))

    def _embedding(self, row):
        key = tuple(str(row.get(k) or "") for k in
                    ("description", "category", "subcategory", "brand", "price_eur"))
        if key not in self.embeddings:
            self.embeddings[key] = self._encode([row])
        return self.embeddings[key]

    def _views(self, request):
        when = timestamp(request.get("ts", self.end))
        return [v for v in (request.get("recent_views") or []) if isinstance(v, dict)
                and (not self._fitting or v.get("product_id") not in self.mask)
                and (not v.get("ts") or timestamp(v["ts"]) <= when)][-20:]

    def _profile(self, request, state):
        views = self._views(request)
        recent, weights = [], []
        for j, view in enumerate(views):
            row = state.get(view.get("product_id"))
            if row is not None:
                recent.append(self._embedding(row))
                weights.append(.8 ** (len(views) - j - 1))
        history = self.history.get(str(request.get("user_id", "")), ())
        organic = None
        if history:
            when = timestamp(request.get("ts", self.end))
            hs, hw = [], []
            for observed_at, weight, vector in history:
                age = max(0., (when - observed_at).total_seconds() / 86400)
                hs.append(vector)
                hw.append(weight * 2 ** (-age / 14.))
            organic = sparse.csr_matrix(np.asarray(sparse.vstack(hs).multiply(np.array(hw)[:, None]).sum(axis=0)))
            organic = normalize(organic)
        session = None
        if recent:
            session = normalize(sparse.csr_matrix(np.asarray(sparse.vstack(recent).multiply(np.array(weights)[:, None]).sum(axis=0))))
        if session is not None and organic is not None:
            profile = normalize(.7 * session + .3 * organic)
        else:
            profile = session if session is not None else organic
        if profile is None:
            profile = sparse.csr_matrix((1, self.dimension))
        last = state.get(views[-1].get("product_id"), {}) if views else {}
        last_vector = self._embedding(last) if last else sparse.csr_matrix((1, self.dimension))
        return profile, last_vector, last, views, bool(history)

    def _design(self, request, ids, state, vectors, slots=None):
        profile, last_vector, last, views, known = self._profile(request, state)
        # Sparse item content and per-coordinate user/content interactions share
        # coefficients across products, including products absent during fitting.
        interactions = vectors.multiply(profile).tocsr()
        last_interactions = vectors.multiply(last_vector).tocsr()
        similarity = np.asarray(vectors @ profile.T.toarray()).ravel()
        last_similarity = np.asarray(vectors @ last_vector.T.toarray()).ravel()
        context = request.get("context") or {}
        counts = Counter(v.get("product_id") for v in views)
        dictionaries = []
        for j, p in enumerate(ids):
            row = state[p]
            lp = math.log1p(price(row))
            delta = (lp - math.log1p(price(last))) / self.price_scale if price(last) else 0.
            d = {"similarity": float(similarity[j]), "last_similarity": float(last_similarity[j]),
                 "log_price_z": (lp - self.price_mean) / self.price_scale,
                 "missing_price": float(not price(row)), "price_delta": delta,
                 "abs_price_delta": abs(delta), "in_recent": float(counts[p] > 0),
                 "recent_count": math.log1p(counts[p]), "is_last": float(bool(views) and p == views[-1].get("product_id")),
                 "has_history": float(known), "n_recent": math.log1p(len(views)),
                 "new_user": float(bool(request.get("is_new_user", False))),
                 f"slot={slots[j] if slots is not None else 0}": 1.}
            for field in ("category", "subcategory", "brand"):
                d[f"same_{field}"] = float(bool(last.get(field)) and row.get(field) == last[field])
            for field in ("page", "device", "region"):
                value = str(context.get(field) or "__missing__")
                d[f"context:{field}={value}"] = 1.
                d[f"category_context:{field}={value}|{row.get('category') or '__missing__'}"] = 1.
                d[f"price_context:{field}={value}"] = (lp - self.price_mean) / self.price_scale
                d[f"similarity_context:{field}={value}"] = float(similarity[j])
            dictionaries.append(d)
        return sparse.hstack([.4 * vectors, 4 * interactions, 2 * last_interactions], format="csr"), dictionaries

    def fit(self, training_snapshot):
        t = training_snapshot
        self._fitting = True
        self.start, self.end = timestamp(t["start"]), timestamp(t["end"])
        self.mask = set(t.get("withheld_product_ids", ()))
        state = {p: dict(r) for p, r in t["catalog"].items() if p not in self.mask and active(r, self.start)}
        if not state:
            raise ValueError("No metadata available at training start")
        self.best = list(dict.fromkeys(p for p in t.get("best", ()) if p not in self.mask))
        self.text = TfidfVectorizer(max_features=5000, ngram_range=(1, 2), sublinear_tf=True,
                                   strip_accents="unicode", dtype=np.float64)
        descriptions = [str(r.get("description") or "") for r in state.values()]
        try:
            self.text.fit(descriptions)
        except ValueError as exc:
            if "empty vocabulary" not in str(exc):
                raise
            self.text.fit(["missingdescriptiontoken"])
        self.metadata = DictVectorizer(sparse=True).fit([self._metadata_features(r) for r in state.values()])
        logs = np.array([math.log1p(price(r)) for r in state.values() if price(r)])
        self.price_mean = float(logs.mean()) if len(logs) else 0.
        self.price_scale = max(float(logs.std()), .5) if len(logs) else 1.
        self.embeddings = {}
        self.dimension = self._encode([{}]).shape[1]
        self.history = {}
        self.item_counts = Counter()
        updates = sorted(t.get("catalog_updates", ()), key=lambda r: timestamp(r["ts"]))
        events = sorted(t.get("organic_events", ()), key=lambda r: timestamp(r["ts"]))
        rows = sorted(t["requests"], key=lambda r: (timestamp(r["ts"]), r["request_id"]))
        for r in [*rows, *events, *updates]:
            if not self.start <= timestamp(r["ts"]) < self.end:
                raise ValueError("Training input outside half-open training period")
        ei = ui = 0
        matrices, dictionaries, labels = [], [], []
        self.diagnostics = {"exposed_rows": 0, "purchase_positives": 0, "skipped_exposures": 0,
                            "organic_events_used": 0, "unexposed_purchase_labels": 0,
                            "training_weight": "uniform per exposed item; no IPS/class balancing",
                            "historical_metadata": t.get("metadata_limitation", "Initial catalogue state assumed; field history unreconstructable")}

        def update_catalog(when):
            nonlocal ui
            while ui < len(updates) and timestamp(updates[ui]["ts"]) <= when:
                update = updates[ui]
                p = update["product_id"]
                if p not in self.mask:
                    state[p] = {**state.get(p, {}), **update}
                    if update.get("change") == "out_of_stock":
                        state[p]["is_active"] = False
                    elif update.get("change") in ("new_product", "back_in_stock"):
                        state[p]["is_active"] = True
                ui += 1

        def consume_events(when):
            nonlocal ei
            while ei < len(events) and timestamp(events[ei]["ts"]) < when:
                event = events[ei]
                et = timestamp(event["ts"])
                update_catalog(et)
                p = event.get("product_id")
                row = state.get(p)
                weight = {"view": 1., "add_to_cart": 3., "purchase": 2.}.get(event.get("event_type"), 0.)
                if row and weight and active(row, et):
                    # Preserve event-time content/price representation, not future metadata.
                    vector = self._embedding({**row, **({"price_eur": event["price_eur"]} if price(event) else {})})
                    self.history.setdefault(str(event.get("user_id", "")), deque(maxlen=40)).append((et, weight, vector))
                    self.item_counts[p] += 1
                    self.diagnostics["organic_events_used"] += 1
                ei += 1

        for request in rows:
            when = timestamp(request["ts"])
            consume_events(when)
            update_catalog(when)
            shown = request.get("shown") or []
            if request.get("purchased") not in (None, "", *shown):
                self.diagnostics["unexposed_purchase_labels"] += 1
            seen, ids, slots = set(), [], []
            for slot, p in enumerate(shown):
                if p not in seen and p in state and active(state[p], when):
                    ids.append(p)
                    slots.append(slot)
                    seen.add(p)
                else:
                    self.diagnostics["skipped_exposures"] += 1
            if not ids:
                continue
            y = [int(p == request.get("purchased")) for p in ids]
            self.diagnostics["exposed_rows"] += len(y)
            self.diagnostics["purchase_positives"] += sum(y)
            if self.learned:
                vector = sparse.vstack([self._embedding(state[p]) for p in ids], format="csr")
                matrix, ds = self._design(request, ids, state, vector, slots)
                matrices.append(matrix)
                dictionaries.extend(ds)
                labels.extend(y)
        consume_events(self.end)
        update_catalog(self.end)
        self.training_metadata = state
        self.model = None
        if self.learned and len(set(labels)) == 2:
            self.context = DictVectorizer(sparse=True)
            x = sparse.hstack([sparse.vstack(matrices, format="csr"), self.context.fit_transform(dictionaries)], format="csr")
            self.model = LogisticRegression(C=self.regularization, solver="liblinear", max_iter=400,
                                            random_state=20261114, tol=1e-5)
            self.model.fit(x, labels)
            self.diagnostics.update({"features": x.shape[1], "solver_iterations": int(self.model.n_iter_[0]),
                                     "converged": bool(self.model.n_iter_[0] < self.model.max_iter)})
        self._catalog_signature = None
        self._fitting = False
        return self

    def _index(self, catalog, when):
        # Inspect current metadata on every call, even for a mutated mapping. A new
        # ID, description, price or stock flag invalidates cached retrieval vectors.
        ids = sorted(p for p, r in catalog.items() if isinstance(p, str) and active(r, when))
        if len(ids) < 10:
            raise ValueError("Fewer than ten eligible real products; a valid slate is impossible")
        signature = tuple((p, tuple(str(catalog[p].get(k) or "") for k in
                                    ("description", "category", "subcategory", "brand", "price_eur"))) for p in ids)
        if signature != self._catalog_signature:
            self._ids = ids
            self._vectors = self._encode([catalog[p] for p in ids])
            self._positions = {p: j for j, p in enumerate(ids)}
            self._best = [p for p in self.best if p in self._positions]
            best_set = set(self.best)
            self._best += [p for p in ids if p not in best_set]
            self._catalog_signature = signature
        return self._ids, self._vectors

    def recommend(self, request, features, catalog):
        when = timestamp(request.get("ts", self.end))
        if when < self.end:
            raise ValueError("Frozen training profiles cannot score a pre-cutoff request")
        ids, vectors = self._index(catalog, when)
        # Recent views of a now inactive item can still carry interests. Incoming
        # metadata wins over training state; neither adds it to eligible outputs.
        state = {**self.training_metadata, **catalog}
        profile, _, _, views, _ = self._profile(request, state)
        scores = np.asarray(vectors @ profile.T.toarray()).ravel()
        if not profile.nnz:
            candidates = self._best[:self.candidates]
        else:
            ix = np.lexsort((np.arange(len(ids)), -scores))[:self.candidates]
            candidates = [ids[j] for j in ix]
            candidates += [v["product_id"] for v in views if v.get("product_id") in self._positions]
            candidates += self._best[:30]
        candidates = list(dict.fromkeys(candidates))
        ix = [self._positions[p] for p in candidates]
        if self.model is not None:
            matrix, ds = self._design(request, candidates, state, vectors[ix])
            x = sparse.hstack([matrix, self.context.transform(ds)], format="csr")
            ranking = self.model.decision_function(x)
        else:
            ranking = scores[ix]
        # Stable popularity ties; popularity is a fallback, never an item-ID coefficient.
        pop = {p: j for j, p in enumerate(self._best)}
        ordered = sorted(zip(candidates, ranking), key=lambda pair: (-float(pair[1]), pop[pair[0]], pair[0]))
        return [p for p, _ in ordered][:10]


register("content_only")(lambda: ContentLinear(learned=False))
register("content_linear")(ContentLinear)
register("content_linear_c01")(lambda: ContentLinear(regularization=.1))
register("content_linear_c10")(lambda: ContentLinear(regularization=10.))
