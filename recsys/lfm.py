"""lfm — "live-fitted model": one slate policy for every page, fitted on TODAY's carousel feedback (T-018, I-180..I-182).

Plain version. Our own feedback (what we showed, what was clicked / bought) says the hidden shopper behaves very
differently depending on who the shopper is, and neither v1 nor qrank uses that:

  * RETURNING shoppers (is_new_user = false, 70% of requests) convert 3x less than new ones because we fill their
    carousel with generic products. For them a product they have no taste for almost never sells (3 purchases in
    56,000 impressions); what sells is (a) products matching their taste for the description phrases, and
    (b) products they put in the cart in the last 60 days and never bought.
  * NEW shoppers buy what they carted earlier TODAY: 3.7% per impression in slot 1 (12x a generic product), and
    we were showing such a product in only 1 of 9 requests that had one.
  * Products the shopper already bought, or viewed in the history without carting, are dead (4 buys / 76k impressions).

So this module scores EVERY active product for the request with a tiny logistic model (11 weights, one set for
returning shoppers and one for new ones, fitted by lfm_build.py on the live feedback) and returns the best 10,
best first. No candidate lists: 5,100 products x 11 features is one numpy matrix product (~0.3 ms).

    LF = lfm.LiveFit.load(history)                 # history: organic user-item aggregates (u, i, v, a, p)
    LF.add(u, i, v, a, p)                          # every live (user, item) delta, like LiveTables.add
    LF.set_catalog(cat, unavail, AFF, lq, hc)      # after each catalog refresh (AFF = attr_affinity.AttrAffinity)
    st = LF.user_state(user_id)                    # cheap copy, take it under the writer's feature_lock
    items = LF.slate(req, st, AFF, exclude=unavail)   # 10 ids, or None = "not my case", caller keeps its own logic

No RawTree calls, no writes. Weights live in lfm_coef.json (refit: `python lfm_build.py --pull`).
"""
from __future__ import annotations
import json, math
from pathlib import Path
import numpy as np, pandas as pd

HERE = Path(__file__).resolve().parent
ART = HERE / "lfm_coef.json"
FEATS = ["aff10", "chn", "cl", "islast", "oinrv", "ssub2", "scat2", "na", "home", "lq", "sbrand"]
AFF_CAP, NEUTRAL = 0.35, 0.10


class Snap:
    """Arrays aligned with the rows of AttrAffinity.A (one row per product). Built once per catalog refresh."""

    def __init__(self, ids, A, cat: pd.DataFrame, unavail, lq: dict | None, lq0: float, hc=None):
        n = len(ids); self.ids = ids; self.n = n; self.A = A[:n]
        self.row = {p: k for k, p in enumerate(ids)}
        c = cat.reindex(ids)
        self.ok = (c["category"].notna().values) & ~np.isin(np.array(ids, dtype=object), list(unavail))
        self.cat = pd.factorize(c["category"])[0]; self.sub = pd.factorize(c["sub"])[0]; self.brand = pd.factorize(c["brand"])[0]
        g = (lq or {}).get
        self.lq = np.array([g(p, lq0) for p in ids], dtype=np.float64) - lq0
        # home_cands keeps "viewed in the 60-day history, never carted" as one bitmap per user; map its bit order to ours
        self.hc = hc
        self.perm = np.array([hc.idx.get(p, -1) for p in ids], dtype=np.int64) if hc is not None else None

    def stale(self, u):
        """Boolean mask: products this user viewed in the history and never carted (dead in the live carousel)."""
        if self.hc is None: return None
        bm = self.hc.stale.get(u)
        if bm is None: return None
        bits = np.unpackbits(np.frombuffer(bm, dtype=np.uint8), bitorder="little")
        out = np.zeros(self.n, dtype=bool); m = (self.perm >= 0) & (self.perm < len(bits))
        out[m] = bits[self.perm[m]].astype(bool)
        return out


def features(S: Snap, aff, rv, page, hist_cart: dict, live_cart, idx=None) -> np.ndarray:
    """Feature matrix (rows = products `idx`, all of them if None; columns = FEATS). The SAME code builds the
    training rows from the feedback log (lfm_build.py) and the serving rows, so they cannot drift apart.
    aff: affinity of this shopper to every product (AttrAffinity.affinity_all); rv: recent views, oldest first;
    hist_cart: {product: times carted in the 60-day history, never bought}; live_cart: products carted today."""
    n = S.n
    X = np.zeros((n, len(FEATS)))
    a = np.full(n, NEUTRAL); m = min(n, len(aff)); a[:m] = aff[:m]
    X[:, 0] = (np.minimum(a, AFF_CAP) - NEUTRAL) * 10.0
    r = S.row.get
    lc = [k for k in (r(p) for p in live_cart) if k is not None]
    for p, cnt in hist_cart.items():
        k = r(p)
        if k is not None: X[k, 1] = math.log1p(cnt)
    if lc: X[lc, 2] = 1.0; X[lc, 1] = 0.0
    rows = [k for k in (r(p) for p in rv) if k is not None]
    last = r(rv[-1]) if rv else None
    if last is not None:
        X[last, 3] = 1.0
        inrv = np.zeros(n, dtype=bool); inrv[rows] = True
        other = inrv.copy(); other[last] = False; X[other, 4] = 1.0
        ssub = S.sub == S.sub[last]; scat = S.cat == S.cat[last]
        X[:, 5] = ssub & ~inrv
        X[:, 6] = scat & ~ssub & ~inrv
        X[:, 7] = (S.A @ S.A[last]) * ~inrv
        X[:, 10] = S.brand == S.brand[last]
    X[:, 8] = 1.0 if page == "home" else 0.0
    X[:, 9] = S.lq
    return X if idx is None else X[idx]


class LiveFit:
    def __init__(self, coef: dict, history: pd.DataFrame | None = None):
        self.w = {k: np.array([coef[k]["w"][f] for f in FEATS]) for k in ("known", "new")}
        self.b = {k: float(coef[k]["b"]) for k in ("known", "new")}
        self.lq0 = float(coef.get("lq0", 0.0)); self.meta = coef.get("meta", {})
        self.hcart, self.hbought = {}, {}
        if history is not None:
            c = history[(history.a > 0) & (history.p == 0)]
            for u, i, a in zip(c.u.values, c.i.values, c.a.values): self.hcart.setdefault(u, {})[i] = int(a)
            self.hbought = history[history.p > 0].groupby("u").i.agg(set).to_dict()
        self.lcart, self.lbought = {}, {}
        self.snap = None

    @classmethod
    def load(cls, history=None, path=ART):
        return cls(json.loads(Path(path).read_text()), history)

    # ---- refresher thread ----
    def add(self, u, i, v=0, a=0, p=0):
        if p: self.lbought.setdefault(u, set()).add(i)
        if a: self.lcart.setdefault(u, set()).add(i)

    def set_catalog(self, cat, unavail, aff, lq=None, hc=None):
        ids = list(aff.pid); A = aff.A
        ids = ids[:len(A)]
        self.snap = Snap(ids, A, cat, set(unavail), lq, self.lq0, hc)     # one atomic swap

    @property
    def ok(self): return self.snap is not None

    # ---- serving thread ----
    def user_state(self, u):
        """(bought, live carts not bought, history carts not bought). Copies: safe against concurrent add()."""
        b = set(self.lbought.get(u, ())) | self.hbought.get(u, set())
        lc = set(self.lcart.get(u, ())) - b
        hc = {i: a for i, a in (self.hcart.get(u) or {}).items() if i not in b and i not in lc}
        return b, lc, hc

    def scores(self, req, state, aff_obj):
        """(snapshot, score per product with dead / unavailable products at -inf)."""
        S = self.snap; rv = req.get("rv") or []
        bought, lc, hc = state
        aff = aff_obj.affinity_all(req["user_id"], rv)
        seg = "new" if req.get("is_new_user") else "known"
        s = features(S, aff, rv, req.get("page", "product"), hc, lc) @ self.w[seg] + self.b[seg]
        dead = ~S.ok
        st = S.stale(req["user_id"])
        if st is not None:
            keep = [S.row[p] for p in list(hc) + list(lc) if p in S.row]
            st[keep] = False; dead = dead | st
        b = [S.row[p] for p in bought if p in S.row]
        if b: dead[b] = True
        s[dead] = -np.inf
        return S, s

    def slate(self, req, state, aff_obj, n=10, exclude=()):
        S, s = self.scores(req, state, aff_obj)
        top = np.argpartition(-s, min(n + 20, S.n - 1))[: n + 20]
        top = top[np.argsort(-s[top])]
        out = [S.ids[k] for k in top if np.isfinite(s[k]) and S.ids[k] not in exclude][:n]
        return out if len(out) == n and len(set(out)) == n else None
