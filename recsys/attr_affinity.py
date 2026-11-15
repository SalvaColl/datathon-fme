"""User x description-attribute affinity (I-091/I-092): the strongest untapped signal we have found.

Every product description carries exactly 2 phrases out of 20 (see cold_items.ATTRS). Shoppers have stable tastes
over those phrases: the share of a user's past organic views that went to products with the SAME phrases as the
candidate ("affinity", neutral value 0.10) predicts purchase far better than category or popularity:

    LIVE feedback (hidden model, 14 Nov, products the user never touched): affinity <0.10 -> 0.7 purchases per
    10,000 impressions; 0.15-0.20 -> 9.9; >0.20 -> 77.   (E-093)
    Offline, within logged slates: v1 score x exp(20*affinity) lifts hit@1 0.472 -> 0.519.   (E-092)
    Organic events (no carousel bias): purchases per first view 1.6% -> 16.7% from affinity <0.10 to >0.20.

Serving API (pure numpy, no model, no RawTree writes):
    AFF = AttrAffinity(cold_items.ColdStart())           # loads data/user_item_all.parquet (history views)
    AFF.add(user, product, n_views)                      # live increments (call from live.refresh_events)
    AFF.sync_products()                                  # after ColdStart.sync(): start scoring newly launched products
    AFF.boost_frame(P)                                   # multiplier per candidate row; P has columns sid,u,i,rv
    AFF.candidates(user, rv, cat, unavail, n=40, category=None, score=None)   # best-matching active products
"""
from __future__ import annotations
import numpy as np, pandas as pd
if __package__:
    from . import cold_items
else:
    import cold_items

NEUTRAL = 0.10     # expected affinity of a random product: each of its 2 phrases appears in ~10% of the catalogue
SHRINK = 20.0      # pseudo attribute-mass (= 10 views) pulling users with little history to NEUTRAL
BETA = 40.0        # score multiplier exp(BETA * affinity). Offline optimum flat 20-30 (E-092); live feedback slope ~40 (E-093)
CAP = 0.35
PENDING_MAX = 2_000_000   # (user, product) pairs held for products not synced yet; beyond it new pairs are dropped, as before


class AttrAffinity:
    def __init__(self, cold: cold_items.ColdStart | None = None, ui_path="data/user_item_all.parquet", beta=BETA):
        self.cold = cold or cold_items.ColdStart(); self.beta = beta
        self.pid = {}; self._rows = []          # product -> row of the attribute matrix
        for p, a in self.cold.attr.items(): self._add_product(p, a)
        self.A = np.array(self._rows, dtype=np.float32)
        self.uix = {}; self.UV = np.zeros((0, 20), dtype=np.float32); self.extra = {}
        self.pending = {}; self.pending_n = 0      # views of products not synced yet: product -> {user: views} (T-046)
        if ui_path is not None:
            ui = pd.read_parquet(ui_path, columns=["u", "i", "v"]); ui = ui[ui.i.isin(self.pid) & (ui.v > 0)]
            codes, uniq = pd.factorize(ui.u)
            self.UV = np.zeros((len(uniq), 20), dtype=np.float32)
            np.add.at(self.UV, codes, self.A[ui.i.map(self.pid).values] * ui.v.values[:, None].astype(np.float32))
            self.uix = {u: k for k, u in enumerate(uniq)}

    def _add_product(self, p, a):
        row = np.zeros(20, dtype=np.float32); row[list(a)] = 1.0
        self.pid[p] = len(self._rows); self._rows.append(row)

    def sync_products(self):
        """Pick up products added to cold.attr by ColdStart.sync() (new products launched during the event).
        Call it from the refresher thread only. Readers take (pid, A) through _view(), and A is swapped before pid
        grows, so a serving thread never indexes past the matrix."""
        if len(self.cold.attr) == len(self.pid): return 0
        new = [(p, a) for p, a in list(self.cold.attr.items()) if p not in self.pid]
        rows = list(self._rows)
        for p, a in new:
            row = np.zeros(20, dtype=np.float32); row[list(a)] = 1.0; rows.append(row)
        self.A = np.array(rows, dtype=np.float32); self._rows = rows
        for k, (p, a) in enumerate(new, start=len(rows) - len(new)): self.pid[p] = k
        for p, _ in new:                                    # T-046: the views that arrived before the product was known
            held = self.pending.pop(p, None)
            if held:
                self.pending_n -= len(held)
                for u, v in held.items(): self.add(u, p, v)
        return len(new)

    # ---- live updates ----
    def add(self, u, i, v=1):
        """Add v organic views of product i by user u (live stream). Views of a product that is not known yet (launched
        during the event, description not synced) are held and applied by sync_products(): the stream is read BEFORE the
        sync in every refresh cycle, and at start-up the whole backlog is read before the first one, so dropping them
        lost every view of a launched product made before the writer started (4.3% of the views of 14 Nov, T-046)."""
        if not v: return
        k = self.pid.get(i)
        if k is None:
            if self.pending_n < PENDING_MAX:
                d = self.pending.setdefault(i, {}); self.pending_n += u not in d; d[u] = d.get(u, 0) + v
            return
        j = self.uix.get(u)
        if j is not None: self.UV[j] += self._rows[k] * v
        else:
            x = self.extra.get(u)
            if x is None: self.extra[u] = self._rows[k] * v
            else: x += self._rows[k] * v

    # ---- scoring ----
    def user_vec(self, u, rv=()):
        """Attribute mass of the user: history + live views + the views of the current request."""
        j = self.uix.get(u)
        vec = self.UV[j].copy() if j is not None else np.zeros(20, dtype=np.float32)
        x = self.extra.get(u)
        if x is not None: vec += x
        for p in rv:
            k = self.pid.get(p)
            if k is not None: vec += self._rows[k]
        return vec

    def affinity_all(self, u, rv=()):
        """Affinity of the user to EVERY product (array aligned with self.pid order), shrunk to NEUTRAL."""
        vec = self.user_vec(u, rv)
        return (self.A @ vec + SHRINK * NEUTRAL) / (vec.sum() + SHRINK)

    def affinity(self, u, items, rv=()):
        aff = self.affinity_all(u, rv); g = self.pid.get; n = len(aff)
        idx = [g(i) for i in items]
        return np.array([aff[k] if k is not None and k < n else NEUTRAL for k in idx], dtype=np.float32)

    def boost(self, u, items, rv=()):
        return np.exp(self.beta * np.minimum(self.affinity(u, items, rv), CAP))

    def boost_frame(self, P: pd.DataFrame) -> np.ndarray:
        """Multiplier for each candidate row of live.predict's frame (columns sid, u, i, rv). One user vector per sid."""
        out = np.ones(len(P), dtype=np.float64); g = self.pid.get
        sid = P.sid.values; items = P.i.values; us = P.u.values; rvs = P.rv.values
        start = 0
        for end in list(np.flatnonzero(sid[1:] != sid[:-1]) + 1) + [len(P)]:
            aff = self.affinity_all(us[start], rvs[start])
            idx = [g(i) for i in items[start:end]]
            n = len(aff); a = np.array([aff[k] if k is not None and k < n else NEUTRAL for k in idx])
            out[start:end] = np.exp(self.beta * np.minimum(a, CAP)); start = end
        return out

    def candidates(self, u, rv, cat, unavail=(), n=40, category=None, score=None, min_aff=0.15) -> list:
        """Active products with the highest affinity for this user (>= min_aff), optionally within one category.
        Products with the same phrase pair tie on affinity; ties are broken by `score` (dict product -> quality)."""
        aff = self.affinity_all(u, rv)
        if float(aff.max()) < min_aff: return []
        order = np.argsort(-aff)[:600]; ids = list(self.pid); seen = set(rv); c = []
        order = order[order < len(ids)]
        for k in order:
            if aff[k] < min_aff: break
            p = ids[k]
            if p in unavail or p in seen or p not in cat.index: continue
            if category is not None and cat.at[p, "category"] != category: continue
            c.append((round(float(aff[k]), 3), float(score.get(p, 0.0)) if score is not None else 0.0, p))
        c.sort(key=lambda x: (-x[0], -x[1]))
        return [p for _, _, p in c[:n]]
