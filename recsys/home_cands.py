"""T-013 — candidates + ordering for requests WITHOUT session views (`home`, 20% of traffic) and for new users.

Why (see ../insights.md I-130…I-132, ../experiments.md E-130…E-132):
  * live feedback: items the user ALREADY BOUGHT are dead in the carousel (1.4 buys / 10k impressions vs 8 for
    unrelated items); carted-but-not-bought items are the hottest thing we can show without session views.
  * items viewed in the organic history but never carted get clicks but no purchases (0 / 9.7k impressions).
  * the user's category share of organic views and the item's organic purchase-per-view rate carry the rest.

The score is a 6-weight logistic model fitted on historical `home` impressions (already-bought rows excluded,
train < 2026-11-04) by `home_eval.py`; weights are hard-coded below so serving needs no model file:

    score(u, i) = 2.16*carted_not_bought + 0.37*user_bought_in_subcat + 4.00*user_view_share_of_category
                  + 1.49*log_cr(i) + 0.29*log_pop(i)                       (unknown user: item terms only)

Usage from the single live writer (no I/O here, pure in-memory, ~0.1 ms per request):

    import home_cands
    HC = home_cands.HomeCands(pd.read_parquet("data/user_item_all.parquet"), catalog_df)   # once, at start
    HC.add(u, i, v, a, p)                  # for every live (user, item) delta — same call as LiveTables.add
    HC.refresh(catalog_df, unavail)        # after each catalog/stock refresh (every ~20 s)
    items = HC.slate(user_id)              # 10 ordered ids for a request with no recent_views
    cands = HC.drop_dead(user_id, cands)   # any page: remove items the user already purchased, or viewed in the
                                           # 60-day history without carting (0 buys in 9.7k live impressions)

`catalog_df` is indexed by product_id with columns `category`, `sub` (as in fe.C / live.py's `cat`).
"""
from __future__ import annotations
import math
from collections import defaultdict
import numpy as np, pandas as pd

W = dict(carted=2.16, sub_b=0.37, ucs=4.00, lcr=1.49, lpop=0.29)   # fitted by home_eval.py (E-130)
HIST_DAYS = 60.0
N_CAT, N_SUB, N_GLOB, TOP_CATS = 40, 10, 40, 4


class HomeCands:
    def __init__(self, ui: pd.DataFrame, catalog: pd.DataFrame):
        """ui: organic history aggregates with columns u, i, v, a, p (one row per user-item)."""
        self.cat_of = catalog["category"].to_dict(); self.sub_of = catalog["sub"].to_dict()
        ui = ui[ui.i.isin(catalog.index)]
        it = ui.groupby("i")[["v", "p"]].sum()
        self.it_v = defaultdict(float, it.v.to_dict()); self.it_p = defaultdict(float, it.p.to_dict())
        b = ui[ui.p > 0]
        self.bought = defaultdict(set, b.groupby("u").i.agg(set).to_dict())
        c = ui[(ui.a > 0) & (ui.p == 0)]
        self.carted = defaultdict(dict)                       # user -> {item: cart count}, bought items removed
        for u, i, a in zip(c.u.values, c.i.values, c.a.values): self.carted[u][i] = int(a)
        self.sub_b = defaultdict(set)                         # user -> subcategories with a purchase
        for u, s in zip(b.u.values, b.i.map(self.sub_of).values): self.sub_b[u].add(s)
        cv = ui.assign(c=ui.i.map(self.cat_of)).groupby(["u", "c"]).v.sum()
        self.cat_v = defaultdict(dict)                        # user -> {category: organic views}
        for (u, k), v in cv.items(): self.cat_v[u][k] = float(v)
        # history "viewed, never carted" as one bitmap per user (5k items -> ~0.6 kB/user); live views are NOT added:
        # a view in the running stream may be current interest, only stale history views are evidence of rejection
        self.idx = {i: k for k, i in enumerate(catalog.index)}; nb = len(self.idx) // 8 + 1
        w = ui[(ui.a == 0) & (ui.p == 0)]; self.stale = {}
        ks = w.i.map(self.idx).values.astype(np.int64); us = w.u.values; order = np.argsort(us, kind="stable")
        us, ks = us[order], ks[order]; cuts = np.flatnonzero(us[1:] != us[:-1]) + 1
        for lo, hi in zip(np.r_[0, cuts], np.r_[cuts, len(us)]):
            bm = np.zeros(nb * 8, dtype=np.uint8); bm[ks[lo:hi]] = 1
            self.stale[us[lo]] = np.packbits(bm, bitorder="little").tobytes()
        self.pools = None; self.unavail = set()
        self.refresh(catalog, set())

    # ---- incremental live updates -------------------------------------------------------------------------------
    def add(self, u, i, v=0, a=0, p=0):
        if i not in self.cat_of: return
        if v: self.it_v[i] += v; d = self.cat_v[u]; k = self.cat_of[i]; d[k] = d.get(k, 0.0) + v
        if p:
            self.it_p[i] += p; self.bought[u].add(i); self.sub_b[u].add(self.sub_of[i]); self.carted[u].pop(i, None)
        elif a and i not in self.bought[u]:
            self.carted[u][i] = self.carted[u].get(i, 0) + a

    def item_score(self, i):
        v = self.it_v.get(i, 0.0); p = self.it_p.get(i, 0.0)
        return W["lcr"] * (math.log((p + 1.0) / (v + 50.0)) + 2.2) + W["lpop"] * (math.log((v + 10.0) / HIST_DAYS) - 3.0)

    def refresh(self, catalog: pd.DataFrame, unavail: set):
        """Recompute item quality and the per-category / per-subcategory / global top lists. Call after stock refresh."""
        self.cat_of = catalog["category"].to_dict(); self.sub_of = catalog["sub"].to_dict()
        q = {i: self.item_score(i) for i in catalog.index if i not in unavail}
        by_cat, by_sub = defaultdict(list), defaultdict(list)
        for i in sorted(q, key=q.get, reverse=True):
            c, s = self.cat_of[i], self.sub_of[i]
            if len(by_cat[c]) < N_CAT: by_cat[c].append(i)
            if len(by_sub[s]) < N_SUB: by_sub[s].append(i)
        glob = sorted(q, key=q.get, reverse=True)
        self.q, self.unavail = q, set(unavail)
        self.pools = dict(cat=dict(by_cat), sub=dict(by_sub), glob=glob[:N_GLOB], all=glob)

    # ---- serving ---------------------------------------------------------------------------------------------------
    def known(self, u): return u in self.cat_v

    def is_stale(self, u, i):
        bm = self.stale.get(u); k = self.idx.get(i)
        return bool(bm is not None and k is not None and bm[k >> 3] & (1 << (k & 7)))

    def is_dead(self, u, i):
        """True if live evidence says showing i to u cannot convert: already bought, or viewed-never-carted in history."""
        return i in self.bought.get(u, ()) or (i not in self.carted.get(u, ()) and self.is_stale(u, i))

    def drop_dead(self, u, items):
        return [i for i in items if not self.is_dead(u, i)]

    def scored(self, u):
        """All home candidates for user u with their score, best first (already-bought / unavailable removed)."""
        P, q = self.pools, self.q
        cv = self.cat_v.get(u)
        if not cv:                                            # unknown / new user: best items overall
            b = self.bought.get(u, ()); return [(i, q[i]) for i in P["glob"] if i not in b]
        tot = max(sum(cv.values()), 1.0); share = {k: v / tot for k, v in cv.items()}
        bought = self.bought.get(u, ()); carted = self.carted.get(u, {}); subs = self.sub_b.get(u, ())
        cands = set(carted) | set(P["glob"])
        for k in sorted(share, key=share.get, reverse=True)[:TOP_CATS]: cands.update(P["cat"].get(k, ()))
        for s in subs: cands.update(P["sub"].get(s, ()))
        out = []
        for i in cands:
            if i in bought or i not in q or (i not in carted and self.is_stale(u, i)): continue
            sc = q[i] + W["ucs"] * share.get(self.cat_of[i], 0.0)
            if i in carted: sc += W["carted"]
            if self.sub_of[i] in subs: sc += W["sub_b"]
            out.append((i, sc))
        out.sort(key=lambda t: -t[1])
        return out

    def slate(self, u, k=10):
        """k ordered, distinct, in-stock product ids for a request without session views."""
        items = [i for i, _ in self.scored(u)[:k]]
        if len(items) < k:
            seen = set(items)
            items += [i for i in self.pools["all"] if i not in seen and not self.is_dead(u, i)][: k - len(items)]
        return items[:k]
