"""aff_policy — glue between the live writer and the description-attribute work (D-090; I-090..I-092).

One object, every method safe to call from the serving loop: on any internal error the caller keeps its own logic.
    AP = aff_policy.AffPolicy.load(DATA)          # in initialize(); needs cold_prior.json + data/user_item_all.parquet
    AP.add(u, i, views)                           # refresh_events(), under the writer's feature_lock
    AP.refresh(query, cat, base_item, live_item)  # refresher(): new-product descriptions + cold table
    AP.candidates(req, cat, unavail)              # extra GBM candidates: products matching the shopper's phrases
    AP.boost(X)                                   # multiplier for GBM rows (columns sid, u, i, rv)
    AP.qrank_slates(QR, reqs)                     # qrank scores x affinity -> slates (None = caller decides)
No RawTree writes. Plain numpy on the request path (about 1 ms per request)."""
from __future__ import annotations
from pathlib import Path
import numpy as np
if __package__:
    from . import cold_items, attr_affinity
    from .qrank import feature_rows
else:
    import cold_items, attr_affinity
    from qrank import feature_rows

N_AFF = 60     # affinity candidates added per request


class AffPolicy:
    def __init__(self, cold, aff):
        self.cold, self.aff = cold, aff
        self.cold_tables = None        # extra fe table for new products (pseudo-counts), rebuilt every refresh

    @classmethod
    def load(cls, data_dir, beta=attr_affinity.BETA):
        cold = cold_items.ColdStart()
        return cls(cold, attr_affinity.AttrAffinity(cold, ui_path=Path(data_dir) / "user_item_all.parquet", beta=beta))

    # ---- refresher thread ----
    def add(self, u, i, v): self.aff.add(u, i, v)

    def refresh(self, query, cat, base_item, live_item=None, organic_item=None):
        self.cold.sync(query); self.aff.sync_products()
        self.cold_tables = self.cold.tables(cat, base_item, live_item, organic_item)

    # ---- serving thread ----
    def candidates(self, req, cat, unavail, category=None):
        return self.aff.candidates(req["user_id"], req["rv"], cat, unavail, n=N_AFF, category=category)

    def boost(self, X): return self.aff.boost_frame(X)

    def qrank_slates(self, QR, reqs, n=10):
        """Same candidates and context model as qrank (slot 0, live calibration), plus this shopper's best-matching
        products of the category, ranked by qrank probability x exp(beta * affinity).
        reqs: dicts with user_id, rv, page, bought (set, already including out-of-stock)."""
        out = [None] * len(reqs)
        for k, r in enumerate(reqs):
            rv = [x for x in r.get("rv", []) if x in QR.cat]
            if not rv or rv[-1] != r["rv"][-1]: continue
            bought = r.get("bought", ()); category = QR.cat.get(rv[-1])
            cand = QR.candidates(rv, bought); have = set(cand)
            aff = self.aff.affinity_all(r["user_id"], rv); ids = list(self.aff.pid)
            for j in np.argsort(-aff)[:400]:
                if aff[j] < 0.15 or len(cand) >= len(have) + N_AFF: break
                p = ids[j] if j < len(ids) else None
                if p is not None and p not in have and p in QR.ok and p not in bought and QR.cat.get(p) == category: cand.append(p)
            if len(cand) < n: continue
            p0 = QR._predict(feature_rows(cand, rv, r.get("page", "product"), 0, QR.lq, QR.sub, QR.brand, QR.price), calibrated=True)
            s = p0 * self.aff.boost(r["user_id"], cand, rv)
            slate = [cand[j] for j in np.argsort(-s)[:n]]
            if len(set(slate)) == n: out[k] = slate
        return out
