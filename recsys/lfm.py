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
FEATS = ["aff10", "chn", "cl", "islast", "oinrv", "ssub2", "scat2", "na", "home", "lq", "sbrand",
         # r2 (T-021): weights missing from a coefficient file count as 0, so r1 files keep working unchanged
         "nbp", "bsub", "hcart", "p40", "segcheap", "seglq",
         # r3 (T-024): the shopper's own category mix, from the views of the 60-day history plus today's
         "ucat", "usub",
         # r5 (T-027): product-to-product co-occurrence with what the shopper is looking at right now
         "cv"]
# nbp: description phrases shared with something bought TODAY (0/1/2) | bsub: same subcategory as something bought today
# hcart: home page x carted-not-bought (history or today) | p40: price above 40 EUR
# segcheap: price-sensitive shopper (android in SEG_REGIONS) x price under 20 EUR | seglq: same shopper x product quality
# ucat / usub: share of the shopper's views that fall in this product's category / subcategory (shrunk to "no preference")
# cv: sum of graph weights (lfm_graph_B.json: sessions of the organic history, view 1 / cart 3 / purchase 6) between this
#     product and each recent view and each product carted today; 0 for products without edges (new products)
UC_PRIOR = 5.0
GRAPH = HERE / "lfm_graph_B.json"
CV_SCALE, CV_CAP = 10.0, 5.0
SEG_REGIONS = ("Andalucía", "Canarias", "Murcia")
def in_segment(device, region): return device == "android" and region in SEG_REGIONS
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
        price = pd.to_numeric(c["price"], errors="coerce").fillna(20.0).values if "price" in c else np.full(n, 20.0)
        self.p40 = (price > 40).astype(float); self.cheap = (price < 20).astype(float)
        # home_cands keeps "viewed in the 60-day history, never carted" as one bitmap per user; map its bit order to ours
        self.ucode = self.scode = None        # stable category / subcategory codes of each product (LiveFit.set_catalog)
        self.hc = hc
        self.g = None                         # product-to-product graph: row -> (neighbour rows, weights), see LiveFit._graph_catalog
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


def features(S: Snap, aff, rv, page, hist_cart: dict, live_cart, idx=None, bought_today=(), seg=False, mix=None) -> np.ndarray:
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
    bt = [k for k in (r(p) for p in bought_today) if k is not None]
    if bt:
        X[:, 11] = (S.A @ S.A[bt].T).max(axis=1)
        X[:, 12] = np.isin(S.sub, S.sub[bt])
        X[bt, 11] = 0.0; X[bt, 12] = 0.0
    if page == "home": X[:, 13] = (X[:, 1] > 0) | (X[:, 2] > 0)
    X[:, 14] = S.p40
    if seg: X[:, 15] = S.cheap; X[:, 16] = S.lq
    if mix is not None and S.ucode is not None:         # mix = (views per category code, views per subcategory code)
        cv, sv = mix; t = float(cv.sum())
        X[:, 17] = ((cv[S.ucode] + UC_PRIOR / len(cv)) / (t + UC_PRIOR) - 1.0 / len(cv)) * (S.ucode >= 0)
        X[:, 18] = ((sv[S.scode] + UC_PRIOR / len(sv)) / (t + UC_PRIOR) - 1.0 / len(sv)) * (S.scode >= 0)
    if S.g is not None:
        acc = X[:, 19]
        for k in set(rows) | set(lc):
            e = S.g.get(k)
            if e is not None: acc[e[0]] += e[1]
        np.minimum(acc * CV_SCALE, CV_CAP, out=acc)
    return X if idx is None else X[idx]


class LiveFit:
    def __init__(self, coef: dict, history: pd.DataFrame | None = None):
        self.w = {k: np.array([coef[k]["w"].get(f, 0.0) for f in FEATS]) for k in ("known", "new")}
        self.b = {k: float(coef[k]["b"]) for k in ("known", "new")}
        self.alt = {}                 # extra weight sets served side by side (A/B): name -> (w, b), see add_model()
        self.lq0 = float(coef.get("lq0", 0.0)); self.meta = coef.get("meta", {})
        self.hcart, self.hbought = {}, {}
        if history is not None:
            c = history[(history.a > 0) & (history.p == 0)]
            for u, i, a in zip(c.u.values, c.i.values, c.a.values): self.hcart.setdefault(u, {})[i] = int(a)
            self.hbought = history[history.p > 0].groupby("u").i.agg(set).to_dict()
        self.lcart, self.lbought = {}, {}
        self.snap = None
        # category mix of every shopper (r3). History matrices are built once, at the first set_catalog (needs the catalog).
        self._hist = history if history is not None and "v" in history else None        # a reference, dropped after the build
        self.ccode, self.sub_code, self.icode = {}, {}, {}      # category name -> code, subcategory -> code, product -> (cat, sub)
        self.urow, self.UC, self.US = {}, None, None            # user -> row of the history matrices
        self.lmix = {}                                          # today's views: user -> {product: views}
        self.NC, self.NS = 16, 160                              # fixed widths, so codes stay valid when the catalog grows
        self.graph = None                                       # {product: [[neighbour, weight], ...]}, read once from GRAPH

    @classmethod
    def load(cls, history=None, path=ART):
        return cls(json.loads(Path(path).read_text()), history)

    def add_model(self, name, coef):
        """Register another coefficient file (same features, same shopper state) under `name`, e.g. "r2"."""
        self.alt[name] = ({k: np.array([coef[k]["w"].get(f, 0.0) for f in FEATS]) for k in ("known", "new")},
                          {k: float(coef[k]["b"]) for k in ("known", "new")})

    def set_arms(self, arms):
        """Tuning arms served side by side (T-021). Each arm: {"tag": "x1", "file": "lfm_coef_r2.json" (optional),
        "w": {"known": {"islast": 3.0}, "new": {...}} (optional absolute overrides)}. An arm without file and
        without w is the committed weights (control). Replaces the previous arms in one step; raises on bad input.
        Fused arms: an optional "home": {"file": ..., "w": ...} (same shape; {} = committed weights) gives the weights
        used on home requests (no recent views), so one arm can serve one weight set on product/category pages and
        another on home."""
        def build(a):
            if a.get("file"):
                c = json.loads((HERE / a["file"]).read_text())
                w = {k: np.array([c[k]["w"].get(f, 0.0) for f in FEATS]) for k in ("known", "new")}
                b = {k: float(c[k]["b"]) for k in ("known", "new")}
            else:
                w = {k: v.copy() for k, v in self.w.items()}; b = dict(self.b)
            for seg, over in (a.get("w") or {}).items():
                for f, val in over.items(): w[seg][FEATS.index(f)] = float(val)
            return w, b
        alt = {}
        for a in arms:
            alt[a["tag"]] = build(a)
            if isinstance(a.get("home"), dict): alt[a["tag"] + "@home"] = build(a["home"])
        self.alt = alt

    # ---- refresher thread ----
    def add(self, u, i, v=0, a=0, p=0):
        if v:
            d = self.lmix.setdefault(u, {}); d[i] = d.get(i, 0) + int(v)
        if p: self.lbought.setdefault(u, set()).add(i)
        if a: self.lcart.setdefault(u, set()).add(i)

    def set_catalog(self, cat, unavail, aff, lq=None, hc=None):
        ids = list(aff.pid); A = aff.A
        ids = ids[:len(A)]
        S = Snap(ids, A, cat, set(unavail), lq, self.lq0, hc)
        try: self._mix_catalog(S, cat)
        except Exception as e: print("lfm category mix off:", type(e).__name__, e, flush=True); S.ucode = S.scode = None
        try: self._graph_catalog(S)
        except Exception as e: print("lfm graph off:", type(e).__name__, e, flush=True); S.g = None
        self.snap = S                                                     # one atomic swap

    def _graph_catalog(self, S):
        """Graph edges as row indices of this snapshot. No file -> cv stays 0 and every weight file behaves as before."""
        if self.graph is None: self.graph = json.loads(GRAPH.read_text())["adj"] if GRAPH.exists() else {}
        if not self.graph: return
        old = self.snap
        if old is not None and old.g is not None and old.ids == S.ids: S.g = old.g; return        # same products, same rows
        r = S.row.get; g = {}
        for a, nb in self.graph.items():
            k = r(a)
            if k is None: continue
            e = [(j, w) for j, w in ((r(b), w) for b, w in nb) if j is not None]
            if e: g[k] = (np.array([j for j, _ in e], dtype=np.int64), np.array([w for _, w in e], dtype=np.float64))
        S.g = g

    def _mix_catalog(self, S, cat):
        for p, c, sb in zip(cat.index, cat["category"].values, cat["sub"].values):
            if p in self.icode or not isinstance(c, str): continue
            cc = self.ccode.setdefault(c, len(self.ccode)); sc = self.sub_code.setdefault(sb, len(self.sub_code)) if isinstance(sb, str) else -1
            self.icode[p] = (cc if cc < self.NC else -1, sc if sc < self.NS else -1)
        code = [self.icode.get(p, (-1, -1)) for p in S.ids]
        S.ucode = np.array([c[0] for c in code], dtype=np.int64); S.scode = np.array([c[1] for c in code], dtype=np.int64)
        if self._hist is not None:
            h = self._hist; self._hist = None
            uc, users = pd.factorize(h["u"]); ic = h["i"].map(self.icode)
            ok = ic.notna().values; v = h["v"].values[ok].astype(np.float64); uc = uc[ok]
            c = np.array([x[0] for x in ic[ok]], dtype=np.int64); sb = np.array([x[1] for x in ic[ok]], dtype=np.int64)
            n = len(users); m = c >= 0; m2 = sb >= 0
            UC = np.bincount(uc[m] * self.NC + c[m], weights=v[m], minlength=n * self.NC).reshape(n, self.NC).astype(np.float32)
            US = np.bincount(uc[m2] * self.NS + sb[m2], weights=v[m2], minlength=n * self.NS).reshape(n, self.NS).astype(np.float32)
            self.UC, self.US, self.urow = UC, US, {u: k for k, u in enumerate(users)}

    def user_mix(self, u, asof=None):
        """(views per category code, views per subcategory code): 60-day history + today's views (`asof`: {product: views}
        replaces the live counter, used by lfm_build.py to rebuild the state as of each logged request)."""
        k = self.urow.get(u)
        cv = self.UC[k].astype(np.float64) if k is not None else np.zeros(self.NC)
        sv = self.US[k].astype(np.float64) if k is not None else np.zeros(self.NS)
        for p, n in list((self.lmix.get(u) or {}).items() if asof is None else asof.items()):
            c = self.icode.get(p)
            if c is None: continue
            if c[0] >= 0: cv[c[0]] += n
            if c[1] >= 0: sv[c[1]] += n
        return cv, sv

    @property
    def ok(self): return self.snap is not None

    # ---- serving thread ----
    def user_state(self, u):
        """(bought, live carts not bought, history carts not bought, bought today). Copies: safe against concurrent add()."""
        bt = set(self.lbought.get(u, ()))
        b = bt | self.hbought.get(u, set())
        lc = set(self.lcart.get(u, ())) - b
        hc = {i: a for i, a in (self.hcart.get(u) or {}).items() if i not in b and i not in lc}
        return b, lc, hc, bt, self.user_mix(u)

    def scores(self, req, state, aff_obj, model=None):
        """(snapshot, score per product with dead / unavailable products at -inf)."""
        S = self.snap; rv = req.get("rv") or []
        bought, lc, hc = state[:3]; bt = state[3] if len(state) > 3 else ()
        aff = aff_obj.affinity_all(req["user_id"], rv)
        seg = "new" if req.get("is_new_user") else "known"
        w, b0 = (self.alt.get(model + "@home") if not rv else None) or self.alt[model] if model else (self.w, self.b)
        X = features(S, aff, rv, req.get("page", "product"), hc, lc, bought_today=bt, seg=in_segment(req.get("device"), req.get("region")),
                     mix=state[4] if len(state) > 4 else None)
        s = X @ w[seg] + b0[seg]
        dead = ~S.ok
        st = S.stale(req["user_id"])
        if st is not None:
            keep = [S.row[p] for p in list(hc) + list(lc) if p in S.row]
            st[keep] = False; dead = dead | st
        b = [S.row[p] for p in bought if p in S.row]
        if b: dead[b] = True
        s[dead] = -np.inf
        return S, s

    def slate(self, req, state, aff_obj, n=10, exclude=(), model=None):
        S, s = self.scores(req, state, aff_obj, model)
        top = np.argpartition(-s, min(n + 20, S.n - 1))[: n + 20]
        top = top[np.argsort(-s[top])]
        out = [S.ids[k] for k in top if np.isfinite(s[k]) and S.ids[k] not in exclude][:n]
        return out if len(out) == n and len(set(out)) == n else None
