"""attr_model — attribute-based ranker for pages with recent views (T-017, D-170). No RawTree calls, no writes.

Plain version. qrank ranks by a per-product number learned from that product's own history, so it has little to
say about a product launched an hour ago or about a shopper we have never seen. This ranker describes products by
what they ARE and shoppers by what they are LOOKING AT right now:

  quality(product) = attribute prior x count corrections
      attribute prior   : category, the 2 description phrases (20-phrase vocabulary, I-090), brand, price bucket and
                          price relative to the subcategory -> expected purchases per view and expected share of views
      count corrections : how much more it is viewed / bought than its attributes predict, and how it did in the
                          old carousel, each SHRUNK towards the prior. A brand-new product has no counts, so it
                          starts exactly at the prior and moves as live events arrive.
  score(shopper, product) = small model(quality, viewed in session, same subcategory/brand, relative price,
                          phrases shared with the last view, share of the session's views with the same phrases, slot)

Nothing in the shopper side uses a user id or stored history: only `recent_views` of the request, so a first-time
shopper is scored exactly like a known one. Candidates are ALL in-stock products of the category being viewed
(~500) plus the viewed ones; products already bought are excluded (I-082).

    AM = attr_model.Ranker.load()                                  # data/attr_model.joblib (attr_model_build.py)
    AM.set_catalog(cat, unavail, live_item=frame, attrs=dict)      # after every catalogue refresh
    AM.slates([{"rv": [...], "page": "product", "bought": set()}, ...])   # list of 10 ids, or None

Same contract as qrank.Ranker (`None` = not my case: home, no views, unknown last product), so the writer can
route to either with one line.
"""
from __future__ import annotations
import math
import numpy as np, pandas as pd, joblib

FE = ["slot", "lq", "last", "inrv", "cnt", "rpos", "nrv", "ssub", "sbrand", "pcat", "prel", "shl", "aff"]
N_ATTR = 20
K_CR, K_POP, KAPPA = 100.0, 20.0, 1000.0   # prior strength: views (conversion), views (popularity), slot-1 impressions (carousel)
SHORT = 25                                 # shortlist size for the slot-aware second stage
# Optional boost for shoppers we know beyond this request (attr_affinity: history + live views, WITHOUT recent_views,
# which the model already uses). Live feedback (E-172): best log-likelihood at 15-25; 40 with recent_views included
# over-boosts shoppers without history.
BETA_HIST, NEUTRAL, SHRINK, CAP = 20.0, 0.10, 20.0, 0.35
REL_EDGES = (-0.5, -0.15, 0.15, 0.5)       # buckets of log(price / median price of the subcategory)


def tokens(category, sub, brand, price, sub_median, at) -> list:
    """One-hot tokens of the two attribute priors. Every token is computable for a product never seen before;
    an unknown brand / phrase / subcategory simply has weight 0."""
    pb = int(min(7, max(0, math.floor(math.log2(max(float(price), 2.0) / 2)))))
    rel = math.log(max(float(price), 0.01) / sub_median) if sub_median else 0.0
    rb = sum(rel > e for e in REL_EDGES)
    t = [f"c={category}", f"s={sub}", f"b={brand}", f"pb={pb}", f"c={category}|pb={pb}", f"rb={rb}", f"c={category}|rb={rb}"]
    for k in at: t += [f"a={k}", f"c={category}|a={k}", f"s={sub}|a={k}"]
    if len(at) == 2: t.append(f"a2={min(at)}_{max(at)}")
    return t


class Quality:
    """Product quality = attribute prior x shrunk count corrections. Parameters are plain dicts (JSON-like)."""

    def __init__(self, p: dict):
        self.p = p                      # coef_cr, b_cr, coef_pop, b_pop, cat (intercepts), beta (la_cr, la_v, r_v, r_cr), b0,
        self._cache = {}                # sub_median, hist (DataFrame v,p,E,b), V_hist

    def prior(self, pid, category, sub, brand, price, at):
        """(log expected purchases per view, log expected share of all views) from attributes only."""
        key = (pid, price)
        r = self._cache.get(key)
        if r is None:
            t = tokens(category, sub, brand, price, self.p["sub_median"].get(sub), at)
            cr, pop = self.p["coef_cr"], self.p["coef_pop"]
            r = (self.p["b_cr"] + sum(cr.get(x, 0.0) for x in t), self.p["b_pop"] + sum(pop.get(x, 0.0) for x in t))
            self._cache[key] = r
        return r

    def compute(self, cat: pd.DataFrame, attrs: dict, live_item: pd.DataFrame | None = None, live_frac=None,
                use_counts=True, masked=()) -> pd.DataFrame:
        """-> DataFrame indexed like cat: lq (log quality) and its parts.
        cat: category, sub, brand, price.  attrs: product -> tuple of phrase indices.
        live_item: optional frame it_v, it_p (live organic totals per product).  live_frac: optional Series, fraction
        of the live window each product existed (new products). masked: products treated as brand new (evaluation)."""
        pr = np.array([self.prior(i, c, s, b, p, attrs.get(i, ())) for i, c, s, b, p in
                       zip(cat.index, cat.category, cat["sub"], cat.brand, cat.price.astype(float))])
        la_cr, la_v = pr[:, 0], pr[:, 1]
        h = self.p["hist"].reindex(cat.index)
        known = h.v.notna().values
        h = h.fillna(0.0)
        v, p, E, b = h.v.values.copy(), h.p.values.copy(), h.E.values.copy(), h.b.values.copy()
        V = np.where(known, self.p["V_hist"], 0.0)
        if live_item is not None and len(live_item):
            lv = live_item.reindex(cat.index).fillna(0.0)
            f = np.ones(len(cat)) if live_frac is None else live_frac.reindex(cat.index).fillna(1.0).values
            v += lv.it_v.values; p += lv.it_p.values; V = V + float(live_item.it_v.sum()) * f
        if not use_counts: v[:] = 0; p[:] = 0; E[:] = 0; b[:] = 0; V[:] = 0
        if len(masked):
            m = cat.index.isin(list(masked)); v[m] = 0; p[m] = 0; E[m] = 0; b[m] = 0; V[m] = 0
        r_v = np.log((v + K_POP) / (np.exp(la_v) * V + K_POP))
        r_cr = np.log((p + K_CR * np.exp(la_cr)) / (v + K_CR)) - la_cr
        be = self.p["beta"]; ci = self.p["cat"]
        lq0 = self.p["b0"] + np.array([ci.get(c, 0.0) for c in cat.category]) + be[0] * la_cr + be[1] * la_v + be[2] * r_v + be[3] * r_cr
        q = (b + KAPPA * np.exp(lq0)) / (E + KAPPA)
        return pd.DataFrame({"lq": np.log(np.maximum(q, 1e-9)), "lq0": lq0, "la_cr": la_cr, "la_v": la_v, "r_v": r_v, "r_cr": r_cr}, index=cat.index)


class Index:
    """Global arrays aligned to a list of product ids, shared by training and serving feature code."""

    def __init__(self, cat: pd.DataFrame, lq, attrs: dict):
        self.ids = list(cat.index); self.ix = {p: k for k, p in enumerate(self.ids)}
        self.lq = np.asarray(lq, dtype=np.float64)
        self.sub = pd.factorize(cat["sub"])[0]; self.brand = pd.factorize(cat.brand)[0]
        self.catname = cat.category.to_numpy(dtype=object); self.cat = pd.factorize(cat.category)[0]
        self.price = cat.price.astype(float).values
        self.A = np.zeros((len(self.ids), N_ATTR), dtype=np.float32)
        for k, p in enumerate(self.ids):
            a = [x for x in attrs.get(p, ()) if x < N_ATTR]
            if a: self.A[k, a] = 1.0

    def features(self, items: np.ndarray, rv: list, page: str, slot=0) -> np.ndarray:
        """One row per candidate. items: array of product positions; rv: positions of the session views, oldest first."""
        n = len(rv); last = rv[-1]
        cnt = np.zeros(len(items)); rpos = np.full(len(items), -1.0)
        for j, r in enumerate(rv):
            m = items == r; cnt += m; rpos[m] = n - 1 - j
        is_last = items == last
        vec = self.A[rv].sum(0)
        X = np.empty((len(items), len(FE)))
        X[:, 0] = slot; X[:, 1] = self.lq[items]; X[:, 2] = is_last; X[:, 3] = (cnt > 0) & ~is_last; X[:, 4] = cnt; X[:, 5] = rpos
        X[:, 6] = n; X[:, 7] = self.sub[items] == self.sub[last]; X[:, 8] = self.brand[items] == self.brand[last]
        X[:, 9] = 1.0 if page == "category" else 0.0
        X[:, 10] = np.log(self.price[items] / self.price[last])
        X[:, 11] = self.A[items] @ self.A[last]                       # phrases shared with the last view: 0, 1, 2
        X[:, 12] = (self.A[items] @ vec) / max(float(vec.sum()), 1.0)  # share of the session's phrase mass on this product's phrases
        return X


class Ranker:
    def __init__(self, model, quality: Quality, base_attrs: dict, meta=None, viewed_factor=0.65, live_start="2026-11-14 09:00:00"):
        self.model, self.quality, self.base_attrs, self.meta = model, quality, base_attrs, meta or {}
        # Live recalibration (E-172, 14 Nov, 75.7k eligible live impressions): against the history-trained prediction,
        # viewed items buy 0.66x as often as non-viewed ones (30 vs 101 purchases; 90% interval 0.46-1.44), so viewed
        # scores are scaled by 0.65. qrank uses 0.45 from an earlier, smaller sample. Set 1.0 to trust history.
        self.viewed_factor = viewed_factor
        self.live_start = pd.Timestamp(live_start)
        self.index = None; self.by_cat = {}; self.ok = set(); self.cat = {}; self.table = None

    @classmethod
    def load(cls, path="data/attr_model.joblib", **kw):
        d = joblib.load(path)
        return cls(d["model"], Quality(d["quality"]), d["attrs"], d.get("meta"), **kw)

    def set_catalog(self, cat: pd.DataFrame, unavail=(), live_item=None, attrs=None, now=None):
        """Call after every catalogue refresh (refresher thread). live_item: frame it_v, it_p of live organic counts
        (LiveTables.item_frame()); attrs: phrases of products missing from the base catalogue (ColdStart.attr)."""
        A = self.base_attrs if not attrs else {**attrs, **self.base_attrs}
        frac = None
        if live_item is not None and "created" in cat.columns:
            now = pd.Timestamp(now) if now is not None else pd.Timestamp.now("UTC").tz_localize(None)
            cr = pd.to_datetime(cat.created, errors="coerce")
            span = max((now - self.live_start).total_seconds(), 1.0)
            frac = ((now - cr).dt.total_seconds() / span).clip(0.02, 1.0).fillna(1.0)
        table = self.quality.compute(cat, A, live_item, frac)
        index = Index(cat, table.lq.values, A)
        un = set(unavail); active = np.array([p not in un for p in index.ids])
        by_cat = {c: np.flatnonzero((index.catname == c) & active) for c in pd.unique(index.catname)}
        # one step, so a serving thread never sees a half-updated catalogue
        self.__dict__.update(index=index, by_cat=by_cat, ok={p for p, a in zip(index.ids, active) if a},
                             cat=dict(zip(index.ids, index.catname)), table=table)

    def _predict(self, X):
        p = self.model.predict_proba(X)[:, 1]
        return np.where((X[:, 2] + X[:, 3]) > 0, p * self.viewed_factor, p)

    def hist_boost(self, cand, uvec, beta=BETA_HIST):
        """Multiplier per candidate from a 20-dim phrase-mass vector of the shopper's past views (None -> 1)."""
        if uvec is None or beta == 0: return 1.0
        uvec = np.asarray(uvec, dtype=np.float32); tot = float(uvec.sum())
        if tot <= 0: return 1.0
        aff = (self.index.A[cand] @ uvec + SHRINK * NEUTRAL) / (tot + SHRINK)
        return np.exp(beta * np.minimum(aff, CAP))

    def slates(self, reqs, n=10, with_scores=False):
        """reqs: list of dicts with rv (product ids, oldest first), page, optional bought (set of ids to exclude),
        optional uvec (phrase mass of the shopper's stored views, see hist_boost)."""
        I = self.index; out = [None] * len(reqs)
        if I is None: return out
        todo, blocks, boosts = [], [], []
        for k, r in enumerate(reqs):
            raw = r.get("rv") or []
            rv = [I.ix[x] for x in raw if x in I.ix]
            if not rv or raw[-1] not in I.ix: continue             # home, or last viewed product unknown -> caller decides
            bought = r.get("bought") or ()
            pool = self.by_cat.get(I.catname[rv[-1]], np.empty(0, dtype=int))
            extra = [x for x in dict.fromkeys(rv) if I.ids[x] in self.ok and I.catname[x] != I.catname[rv[-1]]]
            cand = np.concatenate([pool, np.array(extra, dtype=int)]) if extra else pool
            if bought: cand = cand[[I.ids[x] not in bought for x in cand]]
            if len(cand) < n: continue
            todo.append((k, cand)); blocks.append(I.features(cand, rv, r.get("page", "product"), 0))
            boosts.append(self.hist_boost(cand, r.get("uvec")))
        if not todo: return out
        p0 = self._predict(np.vstack(blocks))
        shorts, blocks2, mult, off = [], [], [], 0
        for (k, cand), b, bo in zip(todo, blocks, boosts):   # stage 2: shortlist x 10 slots, greedy fill (slot effect differs for viewed items)
            idx = np.argsort(-(p0[off:off + len(cand)] * bo))[:SHORT]; off += len(cand)
            rep = np.repeat(b[idx], n, axis=0); rep[:, 0] = np.tile(np.arange(n), len(idx))
            shorts.append(cand[idx]); blocks2.append(rep); mult.append(bo[idx] if isinstance(bo, np.ndarray) else np.ones(len(idx)))
        p = self._predict(np.vstack(blocks2)); off = 0
        for (k, cand), sh, mu in zip(todo, shorts, mult):
            m = p[off:off + len(sh) * n].reshape(len(sh), n) * mu[:, None]; off += len(sh) * n
            slate, ps = [], []
            for s in range(n):
                j = int(np.argmax(m[:, s])); slate.append(I.ids[sh[j]]); ps.append(float(m[j, s])); m[j, :] = -1
            out[k] = (slate, ps) if with_scores else slate
        return out
