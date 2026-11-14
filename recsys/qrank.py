"""qrank — slate builder for product/category pages (T-014, I-082..I-084, E-081). No RawTree calls, no writes.

Plain version: every product has a "quality" q = how often it is bought when shown in slot 1 to somebody who
has NOT viewed it (measured on the old carousel, which showed products semi-randomly, so q is not distorted by
who chose to look at it). A small model then adjusts q for the context of this shopper: did they view this
product in the session (about x10), is it the same subcategory, which slot. We take the products of the
category the shopper is looking at, score them, and fill the 10 slots best-first.

    QR = qrank.Ranker.load()                       # data/qrank.joblib, built by qrank_build.py
    QR.set_catalog(cat, unavail)                   # live catalog DataFrame (index product_id; category, sub, brand, price)
    slates = QR.slates([{"rv": [...], "page": "product", "bought": set()}, ...])   # list of 10 ids, or None

`None` means "not my case" (home / no views / unknown last product): the caller keeps its own logic.
"""
from __future__ import annotations
import numpy as np, pandas as pd, joblib

FE = ["slot", "lq", "last", "inrv", "cnt", "rpos", "nrv", "ssub", "sbrand", "pcat", "prel"]
N_CAT, N_SUB, SHORT = 80, 30, 25   # candidates: top-80 of the category + top-30 of the subcategory + viewed; shortlist 25


def feature_rows(items, rv, page, slot, lq, sub, brand, price):
    """One row per item (same code for training and serving). lq/sub/brand/price are dicts keyed by product id."""
    last = rv[-1]; ls, lb, pl = sub.get(last), brand.get(last), price.get(last)
    pos = {}
    for j, x in enumerate(rv): pos[x] = j           # last occurrence
    n = len(rv); pc = 1.0 if page == "category" else 0.0
    out = np.empty((len(items), len(FE)))
    for k, i in enumerate(items):
        j = pos.get(i)
        pi = price.get(i)
        out[k] = (slot, lq.get(i, np.nan), i == last, j is not None and i != last, rv.count(i) if j is not None else 0,
                  (n - 1 - j) if j is not None else -1, n, sub.get(i) == ls, brand.get(i) == lb, pc,
                  np.log(pi / pl) if (pi and pl) else np.nan)
    return out


class Ranker:
    def __init__(self, model, q: dict, meta=None, viewed_factor=0.45):
        self.model, self.q, self.meta = model, q, meta or {}
        # Live recalibration (E-081, 14 Nov): on v1's live impressions viewed items bought 0.35x what the history-trained
        # model predicts and non-viewed ones 0.80x, so viewed scores are scaled by 0.35/0.80 ~ 0.45. Set 1.0 to trust history.
        self.viewed_factor = viewed_factor
        self.lq, self.sub, self.brand, self.price, self.cat = {}, {}, {}, {}, {}
        self.by_cat, self.by_sub, self.ok = {}, {}, set()

    @classmethod
    def load(cls, path="data/qrank.joblib"):
        d = joblib.load(path)
        return cls(d["model"], d["q"], d.get("meta"))

    def set_catalog(self, cat: pd.DataFrame, unavail=()):
        """Call after every catalog refresh. Products without history (new) get the median q of their subcategory."""
        unavail = set(unavail)
        qs = pd.Series(self.q).reindex(cat.index)
        qs = qs.fillna(qs.groupby(cat["sub"]).transform("median")).fillna(qs.groupby(cat.category).transform("median")).fillna(qs.median())
        qs = qs.clip(lower=1e-6)
        self.lq = np.log(qs).to_dict(); self.sub = cat["sub"].to_dict(); self.brand = cat.brand.to_dict()
        self.price = cat.price.astype(float).to_dict(); self.cat = cat.category.to_dict()
        live = qs[~qs.index.isin(unavail)].sort_values(ascending=False)
        self.ok = set(live.index)
        self.by_cat = {c: g.index[:N_CAT].tolist() for c, g in live.groupby(cat.category.reindex(live.index).values, sort=False)}
        self.by_sub = {s: g.index[:N_SUB].tolist() for s, g in live.groupby(cat["sub"].reindex(live.index).values, sort=False)}

    def _predict(self, X, calibrated=False):
        p = self.model.predict_proba(X)[:, 1]
        return np.where((X[:, 2] + X[:, 3]) > 0, p * self.viewed_factor, p) if calibrated else p

    def candidates(self, rv, bought=()):
        last = rv[-1]
        c = list(dict.fromkeys(list(rv[::-1]) + self.by_sub.get(self.sub.get(last), []) + self.by_cat.get(self.cat.get(last), [])))
        return [i for i in c if i in self.ok and i not in bought]

    def slates(self, reqs, n=10, with_scores=False):
        """reqs: list of dicts with rv (list of product ids, oldest first), page, optional bought (set)."""
        todo, blocks = [], []
        for k, r in enumerate(reqs):
            rv = [x for x in r.get("rv", []) if x in self.cat]
            if not rv or rv[-1] != r["rv"][-1]: continue          # home, or last viewed product unknown -> caller decides
            cand = self.candidates(rv, r.get("bought", ()))
            if len(cand) < n: continue
            todo.append((k, rv, r.get("page", "product"), cand))
            blocks.append(feature_rows(cand, rv, r.get("page", "product"), 0, self.lq, self.sub, self.brand, self.price))
        out = [None] * len(reqs)
        if not todo: return out
        p0 = self._predict(np.vstack(blocks), calibrated=True)
        # stage 2: shortlist x 10 slots in one predict call, then fill slots greedily (the slot effect differs for viewed items)
        shorts, blocks2, off = [], [], 0
        for (k, rv, page, cand), b in zip(todo, blocks):
            idx = np.argsort(-p0[off:off + len(cand)])[:SHORT]; off += len(cand)
            rows = b[idx]; rep = np.repeat(rows, n, axis=0); rep[:, 0] = np.tile(np.arange(n), len(idx))
            shorts.append([cand[j] for j in idx]); blocks2.append(rep)
        p = self._predict(np.vstack(blocks2), calibrated=True); off = 0
        for (k, rv, page, cand), sh in zip(todo, shorts):
            m = p[off:off + len(sh) * n].reshape(len(sh), n).copy(); off += len(sh) * n
            slate, ps = [], []
            for s in range(n):
                j = int(np.argmax(m[:, s])); slate.append(sh[j]); ps.append(float(m[j, s])); m[j, :] = -1
            out[k] = (slate, ps) if with_scores else slate
        return out
