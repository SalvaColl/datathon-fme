"""attr_policy — glue between the live writer and attr_model (T-017, D-170). No RawTree writes.

One object; every method is safe to call from the writer: on any internal error the caller keeps its own logic.
    ATP = attr_policy.AttrPolicy.load(DATA, cold=AP.cold, aff=AP.aff)   # initialize(); reuses aff_policy's objects if given
    ATP.refresh(query, cat, unavail, live_item)                         # refresher(): new-product phrases + live counts -> quality
    ATP.slates(reqs, history=[True, False, ...])                        # serving: list of 10 ids or None per request
`history[k]` adds the stored-taste boost for request k (shoppers with organic history or live views); without it
the slate depends only on the request's recent_views and the catalogue, which is all a first-time shopper has."""
from __future__ import annotations
from pathlib import Path
if __package__:
    from . import attr_model, cold_items, attr_affinity
else:
    import attr_model, cold_items, attr_affinity


class AttrPolicy:
    def __init__(self, ranker, cold=None, aff=None):
        self.ranker, self.cold, self.aff = ranker, cold, aff

    @classmethod
    def load(cls, data_dir, cold=None, aff=None, with_history=True):
        data_dir = Path(data_dir)
        ranker = attr_model.Ranker.load(data_dir / "attr_model.joblib")
        if cold is None:
            try: cold = cold_items.ColdStart()
            except Exception as e: print("attr_policy: cold_items not loaded, new products get no phrases:", type(e).__name__, flush=True)
        if aff is None and with_history and cold is not None:
            try: aff = attr_affinity.AttrAffinity(cold, ui_path=data_dir / "user_item_all.parquet")
            except Exception as e: print("attr_policy: history affinity not loaded, attr_aff acts as attr:", type(e).__name__, flush=True)
        return cls(ranker, cold, aff)

    @property
    def ok(self): return bool(self.ranker.ok)

    # ---- refresher thread ----
    def refresh(self, query, cat, unavail=(), live_item=None, sync=True):
        """sync=False when aff_policy already called ColdStart.sync() / AttrAffinity.sync_products() this cycle."""
        attrs = None
        if self.cold is not None:
            if sync:
                try: self.cold.sync(query)
                except Exception as e: print("attr_policy: new-product sync failed:", type(e).__name__, flush=True)
                if self.aff is not None: self.aff.sync_products()
            attrs = self.cold.attr
        self.ranker.set_catalog(cat, unavail, live_item=live_item, attrs=attrs)

    # ---- serving thread ----
    def slates(self, reqs, history=None, n=10):
        """reqs: dicts with user_id, rv, page, bought (set, already including out-of-stock)."""
        rr = []
        for k, r in enumerate(reqs):
            r = dict(r)
            if history is not None and history[k] and self.aff is not None and r.get("user_id") is not None:
                r["uvec"] = self.aff.user_vec(r["user_id"])           # history + live views, not this request's recent_views
            rr.append(r)
        out = self.ranker.slates(rr, n=n)
        return [s if s is not None and len(set(s)) == n else None for s in out]
