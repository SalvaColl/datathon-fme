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
import collections, json, math, sys, zlib
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
         "cv",
         # r6 (T-035): collaborative filtering, the shopper's 60-day history factorised against everybody else's
         "mf",
         # T-039: product launched during the event (no 60-day history). Our own carousel sold these ~10 times more often
         # than lfm expected for returning shoppers (16 buys vs 1.6 expected, E-390); weight 0 in every committed file
         "newp",
         # T-044: product of a subcategory that is in a live burst right now (trends.py). In the two bursts our carousel
         # could measure (14 Nov, Bike Helmets and Game Consoles) these products sold 6.6 times more per impression than
         # outside the burst (15 buys vs 2.3 expected, E-440); weight 0 in every committed file
         "hot",
         # T-049: product quality read straight from the ORGANIC stream (60-day history + today), two numbers per product:
         # orate = log purchases per view, opop = log views, both centred on the catalogue median. Within the same request and
         # at the same slot they predict which product is bought better than `lq` (whose weight drops to 0 next to them),
         # on held-out requests, for new and returning shoppers and on home (E-490); weight 0 in every committed file
         "orate", "opop",
         # T-053: `hot` only for shoppers whose recent views include the burst's category. In the 7 bursts of 14 Nov these
         # shoppers (11% of the requests of a burst) bought hot products 11 times more often than the other products at the
         # same slot (30 buys vs 2.7 expected); everybody else 3 vs 1.9, no evidence (E-530). Lets a policy give them a
         # large dose and the rest a small one (`hot`); weight 0 in every committed file
         "hotc",
         # T-054: the product was in the recent views of an EARLIER request of this shopper. Those views never reach
         # shop.events, so until now the writer forgot them the moment the request was answered. Randomised history carousel
         # (24 days, 5.1 M impressions): 56 vs 12.6 purchases per 10k for products without organic history (x4.5, 125 buys,
         # flat across slots); live 14 Nov: returning shoppers x2.1 (40 buys vs 19 expected), new shoppers x5.6 (13 vs 2.3)
         # (E-540). Value = log1p(earlier requests of the last 30 days + PRV_TODAY x earlier requests since the event
         # started), 0 for pending carts; home has its own weight block; weight 0 in every committed file
         "prv",
         # T-055: the shopper BOUGHT (hcb) or only CLICKED (hcc) this product in the carousel of the 60-day history
         # (shop.history_sessions.purchased / .clicked). Carousel purchases never reach the organic events, so the model
         # saw these products as plain pending carts or untouched products. Live 14 Nov after 16:00 UTC, returning shoppers,
         # per impression with slot, cart, cart count, session context and category share: hcb +1.61 +- 0.14 on purchases
         # (109 buys), +1.46 +- 0.09 on clicks; inside the same request x2 against another pending cart at the same slot
         # and x3-5 against a non-cart product; hcc +0.40 +- 0.15 (E-550). 0 for products bought organically (those stay
         # excluded); weight 0 in every committed file
         "hcb", "hcc",
         # T-059: `newp` for requests WITHOUT recent views (home). `newp` itself stays 0 there, so until now no policy could
         # weight launched products on home. For new shoppers on home they are 8.5% of the organic purchases that follow
         # the request and 0.9% of our impressions (14 Nov 16:45 UTC - 15 Nov 01:50 UTC); no carousel evidence yet
         # (264 impressions), so this only opens the dial: weight 0 in every committed file and policy
         "newph",
         # T-063: attribute affinity computed ONLY from the products of the shopper's EARLIER requests (the `prv` store:
         # 30 days of history_sessions + the event), a source that never reaches shop.events and that `aff10` (organic
         # views + the current request) does not see. `prv` rewards the exact product; this transfers the taste to other
         # products with the same description phrases. Returning shoppers on pages, within the same request with the
         # live score, prv, aff10, ucat, usub, mf and session context as controls: +0.32 +- 0.11 on purchases (1,675),
         # +0.29 +- 0.06 on clicks, both halves; out of sample at three cuts a dose of 0.8 gains log-likelihood on
         # purchases and clicks (E-630). For new shoppers it loses out of sample: leave their weight at 0. Value = aff10's
         # formula on that profile, without the views of the request being answered and without the candidate itself;
         # weight 0 in every committed file and policy
         "rqa"]
# nbp: description phrases shared with something bought TODAY (0/1/2) | bsub: same subcategory as something bought today
# hcart: home page x carted-not-bought (history or today) | p40: price above 40 EUR
# segcheap: price-sensitive shopper (android in SEG_REGIONS) x price under 20 EUR | seglq: same shopper x product quality
# ucat / usub: share of the shopper's views that fall in this product's category / subcategory (shrunk to "no preference")
# cv: sum of graph weights (lfm_graph_B.json: sessions of the organic history, view 1 / cart 3 / purchase 6) between this
#     product and each recent view and each product carted today; 0 for products without edges (new products)
# mf: score of the product for this shopper in a rank-16 factorisation of the 60-day organic history (users x products,
#     log(1 + views + 3 carts + 6 purchases), lfm_mf_build.py -> lfm_mf.npz), standardised across the catalogue for each
#     shopper; 0 for shoppers without history and for products launched after the history (new products)
UC_PRIOR = 5.0
MF = HERE / "lfm_mf.npz"
GRAPH = HERE / "lfm_graph_B.json"
CV_SCALE, CV_CAP = 10.0, 5.0
SEG_REGIONS = ("Andalucía", "Canarias", "Murcia")
def in_segment(device, region): return device == "android" and region in SEG_REGIONS
AFF_CAP, NEUTRAL = 0.35, 0.10


LQ_MODES = ("cold", "cold_new", "cold_known")   # arm key "lq" (T-028): corrected quality for products launched today (cold_lq_arm);
                                   # "cold" = returning and new shoppers, "cold_new" = new shoppers only (T-034),
                                   # "cold_known" = returning shoppers only (T-047)
LQ_COHORT = {"cold_new": True, "cold_known": False}   # selective modes -> the is_new_user value they treat
X_HI = 60                          # exploration arm: the last slot is drawn from ranks 11..60
X_MODES = ("new", "known")         # arm key "explore": true = every shopper, "new" / "known" = only that kind of shopper
LQ_PAGES = ("product", "category")   # ...only on these pages and only with recent views; home is never touched


def lq_target(mode, is_new_user, page, rv) -> bool:
    """Does a request get the corrected quality under arm mode `mode`? The single rule for scoring and for routing."""
    if mode not in LQ_MODES or not rv or page not in LQ_PAGES: return False
    return mode == "cold" or LQ_COHORT[mode] == bool(is_new_user)


RC = "@recart"                     # arm key "recart": true (T-046). Marker entry of LiveFit.alt, see set_arms()


def recart_target(is_new_user, page, rv) -> bool:
    """Does a request get the re-cart bonus of an arm with "recart": true? Returning shoppers on product/category pages
    with recent views. New shoppers and home keep their behaviour."""
    return not is_new_user and bool(rv) and page in LQ_PAGES


def x_target(mode, is_new_user, page, rv) -> bool:
    """Does a request get the exploration slot under arm mode `mode` (True | "new" | "known")? Pages with views only."""
    if not (mode is True or mode in X_MODES) or not rv or page not in LQ_PAGES: return False
    return mode is True or (mode == "new") == bool(is_new_user)


CAP_KEYS = ("known", "new", "home_known", "home_new")     # arm key "newcap" (T-061): segments of the cap on launched products


def cap_key(is_new_user, rv) -> str:
    """Segment of a request for the cap on launched products: pages with views ("known" / "new") or requests without
    recent views ("home_known" / "home_new"), the same split as the model_version suffixes -k / -n / -kh / -nh."""
    return ("" if rv else "home_") + ("new" if is_new_user else "known")


def cap_launched(S, s, c, exclude=(), own=()):
    """T-061: scores with all but the best `c` launched products (S.newp, the ones the `newp` / `newph` weights push)
    at -inf, so a list never carries more than `c` of them however many products have been launched. The boost on
    launched products is a weight per product, so its exposure grows with every batch of launches (0.8 on new-user home:
    0.81 per list with 400 launched, 1.41 with 500); the cap bounds it without retuning the dose. Launched products
    the shopper has viewed this session or holds in a cart (`own`) are never dropped and count towards `c`: their
    place comes from the shopper's own record, not from the boost. Returns `s` itself when nothing has to go."""
    newp = getattr(S, "newp", None)
    if newp is None or c is None or c < 0: return s
    idx = np.flatnonzero((newp > 0) & np.isfinite(s))
    if len(idx) <= c: return s
    idx = idx[np.argsort(-s[idx], kind="stable")]
    left = c - sum(1 for k in idx if S.ids[k] in own and S.ids[k] not in exclude)
    drop = []
    for k in idx:
        p = S.ids[k]
        if p in own: continue
        if p in exclude: continue                      # cannot be served anyway: neither kept nor counted
        if left > 0: left -= 1
        else: drop.append(k)
    if not drop: return s
    s = s.copy(); s[drop] = -np.inf
    return s


class Snap:
    """Arrays aligned with the rows of AttrAffinity.A (one row per product). Built once per catalog refresh."""

    def __init__(self, ids, A, cat: pd.DataFrame, unavail, lq: dict | None, lq0: float, hc=None, lq_cold: dict | None = None, newp=None):
        n = len(ids); self.ids = ids; self.n = n; self.A = A[:n]
        self.row = {p: k for k, p in enumerate(ids)}
        c = cat.reindex(ids)
        self.ok = (c["category"].notna().values) & ~np.isin(np.array(ids, dtype=object), list(unavail))
        self.cat = pd.factorize(c["category"])[0]; self.sub = pd.factorize(c["sub"])[0]; self.brand = pd.factorize(c["brand"])[0]
        g = (lq or {}).get
        self.lq = np.array([g(p, lq0) for p in ids], dtype=np.float64) - lq0
        # T-028: corrected snapshot for arms with "lq": a COPY of the incumbent vector where only the products in lq_cold
        # (cold_lq_arm.Corrector.corrections) change. Both vectors are read-only; None = no valid correction this refresh.
        self.lq.flags.writeable = False
        self.lqc = None
        if lq_cold:
            # T-042: its own name. This buffer used to be called `c` and replaced the catalogue frame, so the price lines
            # below fell back to 20 EUR for every product and p40 / cheap were all zero for EVERY arm of the snapshot.
            corrected_lq = self.lq.copy()
            for p, v in lq_cold.items():
                k = self.row.get(p)
                if k is not None and isinstance(v, (int, float)) and np.isfinite(v): corrected_lq[k] = float(v) - lq0
            if not np.array_equal(corrected_lq, self.lq): corrected_lq.flags.writeable = False; self.lqc = corrected_lq
        # T-039: 1.0 for products launched during the event; None (feature stays 0) when the caller does not know them
        self.newp = np.isin(np.array(ids, dtype=object), list(newp)).astype(np.float64) if newp else None
        price = pd.to_numeric(c["price"], errors="coerce").fillna(20.0).values if "price" in c.columns else np.full(n, 20.0)   # catalogue only
        self.p40 = (price > 40).astype(float); self.cheap = (price < 20).astype(float)
        # home_cands keeps "viewed in the 60-day history, never carted" as one bitmap per user; map its bit order to ours
        self.ucode = self.scode = None        # stable category / subcategory codes of each product (LiveFit.set_catalog)
        self.hc = hc
        self.g = None                         # product-to-product graph: row -> (neighbour rows, weights), see LiveFit._graph_catalog
        self.mf = None                        # (product factors, their rows, the matching rows of this snapshot), see LiveFit._mf_catalog
        self.perm = np.array([hc.idx.get(p, -1) for p in ids], dtype=np.int64) if hc is not None else None
        self.hot = None                       # T-044: 1.0 for products of a subcategory in a live burst (LiveFit.set_catalog)
        self.orate = self.opop = None         # T-049: organic quality of each product (LiveFit.set_catalog, organic_quality())

    def stale(self, u):
        """Boolean mask: products this user viewed in the history and never carted (dead in the live carousel)."""
        if self.hc is None: return None
        bm = self.hc.stale.get(u)
        if bm is None: return None
        bits = np.unpackbits(np.frombuffer(bm, dtype=np.uint8), bitorder="little")
        out = np.zeros(self.n, dtype=bool); m = (self.perm >= 0) & (self.perm < len(bits))
        out[m] = bits[self.perm[m]].astype(bool)
        return out


PRV_TODAY, PRV_CAP = 2.0, 8.0      # T-054: weight of a view in an earlier request of the event; cap on the total count


def features(S: Snap, aff, rv, page, hist_cart: dict, live_cart, idx=None, bought_today=(), seg=False, mix=None, lq=None, mfu=None, prev=None, hcar=None) -> np.ndarray:
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
    q = S.lq if lq is None else lq                      # lq: an arm's own quality vector (Snap.lqc), serving only
    X[:, 9] = q
    bt = [k for k in (r(p) for p in bought_today) if k is not None]
    if bt:
        X[:, 11] = (S.A @ S.A[bt].T).max(axis=1)
        X[:, 12] = np.isin(S.sub, S.sub[bt])
        X[bt, 11] = 0.0; X[bt, 12] = 0.0
    if page == "home": X[:, 13] = (X[:, 1] > 0) | (X[:, 2] > 0)
    X[:, 14] = S.p40
    if seg: X[:, 15] = S.cheap; X[:, 16] = q
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
    if mfu is not None and S.mf is not None:            # mfu: the shopper's factor vector (LiveFit.user_mf)
        Q, rows_mf, rows_s = S.mf                        # Q: every product of the history; rows_s[k] <-> rows_mf[k]
        sc = Q @ mfu; sd = float(sc.std())
        if sd > 0: X[rows_s, 20] = (sc[rows_mf] - sc.mean()) / sd
    if getattr(S, "newp", None) is not None and rv and page in LQ_PAGES: X[:, 21] = S.newp      # never on home or without views
    if getattr(S, "newp", None) is not None and not rv: X[:, 29] = S.newp                       # T-059: its twin for requests without views
    if getattr(S, "hot", None) is not None:
        X[:, 22] = S.hot                                                                        # every page: a burst reaches every shopper
        if rows: X[:, 25] = S.hot * np.isin(S.cat, S.cat[rows])                                 # T-053: the burst's category is in the recent views
    if getattr(S, "orate", None) is not None: X[:, 23] = S.orate; X[:, 24] = S.opop             # every page: a property of the product
    if prev:                                            # T-054: {product: weighted count of EARLIER requests that had it in view}
        for p, c in prev.items():
            k = r(p)
            if k is not None and c > 0: X[k, 26] = math.log1p(min(float(c), PRV_CAP))
        if lc: X[lc, 26] = 0.0                          # pending carts keep their own order (live: x1.15, no evidence)
        hk = [k for k in (r(p) for p in hist_cart) if k is not None]
        if hk: X[hk, 26] = 0.0
        try: X[:, 30] = request_affinity(S, prev, rv)   # T-063: taste from earlier requests; any surprise leaves it at 0
        except Exception: X[:, 30] = 0.0
    if hcar:                                            # T-055: (products bought, products only clicked) in the history carousel
        for col, items in ((27, hcar[0]), (28, hcar[1])):
            hk = [k for k in (r(p) for p in items) if k is not None]
            if hk: X[hk, col] = 1.0
    return X if idx is None else X[idx]


RQA_SHRINK = 20.0       # T-063: pseudo attribute mass, the same as attr_affinity.SHRINK


def request_affinity(S, prev, rv=()):
    """T-063 (`rqa`): affinity of every product to the description phrases of the products seen in EARLIER requests
    (`prev`: {product: weighted count}, LiveFit.prev_views), in aff10's units and with its shrinkage, uncapped. The views
    of the request being answered are left out (they are in aff10 already) and a product does not count towards its own
    value (that is `prv`). Zeros when there is nothing to transfer."""
    out = np.zeros(S.n)
    if not prev: return out
    r = S.row.get; cur = set(rv or ())
    ks = []; ws = []
    for p, c in prev.items():
        if c > 0 and p not in cur:
            k = r(p)
            if k is not None: ks.append(k); ws.append(float(c))
    if not ks: return out
    ks = np.array(ks); ws = np.array(ws)
    A = S.A
    vec = ws @ A[ks]; tot = float(vec.sum())
    num = A @ vec; den = np.full(S.n, tot)
    own = A[ks]
    num[ks] -= ws * (own * own).sum(axis=1); den[ks] -= ws * own.sum(axis=1)
    return ((num + RQA_SHRINK * NEUTRAL) / (den + RQA_SHRINK) - NEUTRAL) * 10.0


OQ_PRIOR_P, OQ_PRIOR_V, OQ_POP0, OQ_CLIP = 1.0, 20.0, 5.0, 3.0


def organic_quality(ids, oq, hist=None):
    """T-049 -> (orate, opop), one value per product of `ids`, or (None, None) when there is nothing usable.
    oq: {product: (organic views, organic purchases)} over the 60-day history plus today (never purchases made through
    our own carousel). hist: the products that have a 60-day history; None = all of `oq`.
      orate = log((purchases + 1) / (views + 20)) minus the catalogue median: with no views a product sits at the prior
              (1 purchase per 20 views, about the median), so a product launched today starts neutral and moves with the stream
      opop  = log(views + 5) minus the catalogue median, for products WITH history; 0 (neutral) for the others, whose few
              hours of views are not comparable with 60 days
    Both clipped to +-3 so one odd product cannot dominate a slate."""
    try:
        if not oq: return None, None
        g = oq.get; v = np.zeros(len(ids)); p = np.zeros(len(ids)); has = np.zeros(len(ids), dtype=bool)
        for k, i in enumerate(ids):
            c = g(i)
            if c is None: continue
            v[k] = max(float(c[0]), 0.0); p[k] = max(float(c[1]), 0.0); has[k] = hist is None or i in hist
        if not np.isfinite(v).all() or not np.isfinite(p).all(): return None, None
        r = np.log((p + OQ_PRIOR_P) / (v + OQ_PRIOR_V)); pop = np.log(v + OQ_POP0)
        if has.sum() < 50:
            # T-050: (almost) no product of this catalogue has a 60-day history, e.g. a final round served on a new catalogue.
            # The purchase rate of the stream is still comparable between products, so orate stays on (centred on the whole
            # catalogue; the centre does not change any ranking) and opop, which needs the history, is neutral for everybody.
            # Without this an arm that gives `lq` weight 0 would be left with no product quality at all.
            if int((v > 0).sum()) < 50: return None, None            # too little stream to compare products
            return np.clip(r - np.median(r), -OQ_CLIP, OQ_CLIP), np.zeros(len(ids))
        orate = np.clip(r - np.median(r[has]), -OQ_CLIP, OQ_CLIP)
        opop = np.where(has, np.clip(pop - np.median(pop[has]), -OQ_CLIP, OQ_CLIP), 0.0)
        return orate, opop
    except Exception as e:
        print("lfm organic quality off:", type(e).__name__, e, flush=True); return None, None


def top_items(S, s, n=10, exclude=()):
    """The writer's top-N selection, including its tie order and stock-shock repair. Shared with offline target
    evaluation: a tied score does not put every tied product into the ten available slots. Does not mutate scores."""
    if S.n == 0 or n <= 0: return []
    top = np.argpartition(-s, min(n + 20, S.n - 1))[: n + 20]
    top = top[np.argsort(-s[top])]
    out = [S.ids[k] for k in top if np.isfinite(s[k]) and S.ids[k] not in exclude][:n]
    if len(out) < n and exclude:
        # Stock may have moved since the snapshot: look past the first thirty candidates.
        out = [S.ids[k] for k in np.argsort(-s) if np.isfinite(s[k]) and S.ids[k] not in exclude][:n]
    return out


class LiveFit:
    def __init__(self, coef: dict, history: pd.DataFrame | None = None):
        self.w = {k: np.array([coef[k]["w"].get(f, 0.0) for f in FEATS]) for k in ("known", "new")}
        self.b = {k: float(coef[k]["b"]) for k in ("known", "new")}
        self.alt_cap = {}             # arm tag -> {"known" | "new" | "home_known" | "home_new": max launched products per list} (T-061)
        self.alt_x = {}               # arm tag -> True | "new" | "known": exploration in the last slot (T-039)
        self.alt_lq = {}              # arm tag -> "cold" | "cold_new" (T-028), see set_arms()
        self.alt = {}                 # extra weight sets served side by side (A/B): name -> (w, b), see add_model()
        self.lq0 = float(coef.get("lq0", 0.0)); self.meta = coef.get("meta", {})
        self.hcart, self.hbought = {}, {}
        if history is not None:
            c = history[(history.a > 0) & (history.p == 0)]
            for u, i, a in zip(c.u.values, c.i.values, c.a.values): self.hcart.setdefault(u, {})[i] = int(a)
            self.hbought = history[history.p > 0].groupby("u").i.agg(set).to_dict()
        self.lcart, self.lbought = {}, {}
        # State windows (T-036). Time of the latest cart / purchase event per shopper and product, as the ISO string the
        # stream gives ("2026-11-15 08:00:00.123": string order = time order). day_start None = no day window (as before).
        self.lcart_t, self.lbought_t = {}, {}
        self.day_start, self.day_carts = None, False
        # T-063: purchases made before `prior_start` (live stream / our carousel, never the 60-day history) can be let
        # back into the lists. None = no boundary = behaviour before T-063. See set_prior().
        self.prior_start, self.prior_allow = None, False
        self.prior_stats = collections.Counter()
        self.snap = None
        # category mix of every shopper (r3). History matrices are built once, at the first set_catalog (needs the catalog).
        self._hist = history if history is not None and "v" in history else None        # a reference, dropped after the build
        self.ccode, self.sub_code, self.icode = {}, {}, {}      # category name -> code, subcategory -> code, product -> (cat, sub)
        self.urow, self.UC, self.US = {}, None, None            # user -> row of the history matrices
        self.lmix = {}                                          # today's views: user -> {product: views}
        # T-054: recent views of the shopper's EARLIER requests (they never appear in shop.events).
        self.prv_hist = {}                                      # user -> (products, counts): history_sessions, last 30 days
        self.prv_day = {}                                       # user -> {product: requests of the event that had it in view}
        self.prv_last = {}                                      # user -> (request_id, products) of the newest request added
        self.hcar = {}                                          # T-055: user -> (products bought, products only clicked) in the history carousel
        self.NC, self.NS = 16, 160                              # fixed widths, so codes stay valid when the catalog grows
        self.graph = None                                       # {product: [[neighbour, weight], ...]}, read once from GRAPH
        self.mf_u, self.mf_P, self.mf_Q, self.mf_items = None, None, None, None    # factorisation, read once from MF

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
        another on home.
        Re-cart arms (T-046): "recart": true keeps, for a product carted in the 60-day history AND again today (never
        bought), the larger of its two cart contributions: the score gets max(0, w_chn * log1p(history carts) - w_cl) on
        top. Without it a history cart worth w_chn * log1p(n) is REPLACED by w_cl the moment the shopper carts the
        product again (features() zeroes chn for today's carts), so under cx3 a once-carted product loses 1.45 points by
        being carted again. Returning shoppers on product/category pages with views only (recart_target); off by default.
        The flag travels as one more entry of `alt` ("<tag>@recart", the arm's own weights) rather than in a new
        attribute, so whatever installs `alt` installs the flag with it, atomically."""
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
            if a.get("recart") is True: alt[a["tag"] + RC] = alt[a["tag"]]
        self.alt = alt
        self.alt_lq = {a["tag"]: a["lq"] for a in arms if a.get("lq") in LQ_MODES}
        self.alt_x = {a["tag"]: a["explore"] for a in arms if a.get("explore") is True or a.get("explore") in X_MODES}   # T-039, see slate()
        self.alt_cap = {a["tag"]: dict(a["newcap"]) for a in arms if isinstance(a.get("newcap"), dict) and a["newcap"]}    # T-061, see slate()

    # ---- refresher thread ----
    def set_window(self, day_start=None, carts="persistent"):
        """Which live state belongs to the current day / phase. Definitions and evidence: D-360 in decisions.md, E-360 in experiments.md.
        day_start: "YYYY-MM-DD HH:MM:SS" UTC, or None for no day window (everything since the writer's EVENTS_SINCE
        counts as today, the behaviour before T-036).
          - purchases: ALWAYS excluded from the slate, whatever their date (permanent). Only purchases at or after
            day_start feed the "bought today" features (nbp, bsub).
          - carts: "persistent" (default) keeps every live cart as a live cart; "day" keeps carts at or after day_start
            as live carts and turns older ones into history carts (one more cart in `chn`). Never erased.
          - views (category mix, affinity): always persistent, they are preferences.
        An event whose time is unknown counts as today."""
        if day_start is not None:
            day_start = str(day_start)
            if len(day_start) != 19 or str(np.datetime64(day_start.replace(" ", "T"), "s")).replace("T", " ") != day_start:
                raise ValueError("day_start must be 'YYYY-MM-DD HH:MM:SS'")
        if carts not in ("persistent", "day"): raise ValueError("carts must be 'persistent' or 'day'")
        self.day_start, self.day_carts = day_start, carts == "day"       # two plain assignments; user_state reads them once

    def set_prior(self, boundary=None, mode="exclude"):
        """T-063. Purchases of the live state (organic stream since EVENTS_SINCE + our carousel feedback) whose latest
        time is before `boundary` ("YYYY-MM-DD HH:MM:SS" UTC, the start of the final) are "prior purchases".
          - mode "exclude" (default): they stay excluded, exactly as without a boundary; slate() only counts, in
            prior_stats, how many would enter the list (shadow diagnosis, the answer is untouched).
          - mode "allow": they are no longer excluded and compete with their normal score.
        Purchases at or after the boundary, purchases without a time and the 60-day history purchases stay excluded in
        both modes. Nothing is erased: carts, views, preferences and the "bought today" features do not change, and
        switching back restores the exclusion at the next request. boundary None switches everything off."""
        if boundary is not None:
            boundary = str(boundary)
            if len(boundary) != 19 or str(np.datetime64(boundary.replace(" ", "T"), "s")).replace("T", " ") != boundary:
                raise ValueError("boundary must be 'YYYY-MM-DD HH:MM:SS'")
        if mode not in ("exclude", "allow"): raise ValueError("mode must be 'exclude' or 'allow'")
        self.prior_allow = False                                   # never "allow" with a stale boundary in between
        self.prior_start = boundary
        self.prior_allow = boundary is not None and mode == "allow"
        self.prior_stats = collections.Counter()

    def prior_bought(self, u):
        """Products the shopper bought before the boundary and not since (and not in the 60-day history). Empty without
        a boundary. Lock-free: one C-level copy of the shopper's small dict."""
        ps = self.prior_start
        if ps is None: return set()
        t = self.lbought_t.get(u)
        if not t: return set()
        out = {i for i, x in list(t.items()) if x < ps}
        h = self.hbought.get(u)
        return out - h if h and out else out

    def add(self, u, i, v=0, a=0, p=0, ta=None, tp=None):
        """ta / tp: time of the latest cart / purchase event (ISO strings from the stream), used only by the state windows."""
        if v:
            d = self.lmix.setdefault(u, {}); d[i] = d.get(i, 0) + int(v)
        if p:
            self.lbought.setdefault(u, set()).add(i)
            if tp:
                d = self.lbought_t.setdefault(u, {})
                if tp > d.get(i, ""): d[i] = tp
        if a:
            self.lcart.setdefault(u, set()).add(i)
            if ta:
                d = self.lcart_t.setdefault(u, {})
                if ta > d.get(i, ""): d[i] = ta

    def set_catalog(self, cat, unavail, aff, lq=None, hc=None, lq_cold=None, newp=None, hot=None, oq=None, oq_hist=None):
        """hot (T-044): products of the subcategories in a live burst, or None / empty (the feature stays 0).
        oq (T-049): {product: (organic views, organic purchases)}, oq_hist: products with a 60-day history; None = features stay 0."""
        ids = list(aff.pid); A = aff.A
        ids = ids[:len(A)]
        S = Snap(ids, A, cat, set(unavail), lq, self.lq0, hc, lq_cold, newp)
        if hot: S.hot = np.isin(np.array(ids, dtype=object), list(hot)).astype(np.float64)
        if oq: S.orate, S.opop = organic_quality(ids, oq, oq_hist)
        try: self._mix_catalog(S, cat)
        except Exception as e: print("lfm category mix off:", type(e).__name__, e, flush=True); S.ucode = S.scode = None
        try: self._graph_catalog(S)
        except Exception as e: print("lfm graph off:", type(e).__name__, e, flush=True); S.g = None
        try: self._mf_catalog(S)
        except Exception as e: print("lfm mf off:", type(e).__name__, e, flush=True); S.mf = None
        self.snap = S                                                     # one atomic swap

    def _mf_catalog(self, S):
        """Factor rows matched to this snapshot. No file -> mf stays 0 and every weight file behaves as before."""
        if self.mf_u is None:
            if not MF.exists(): self.mf_u = {}; return
            z = np.load(MF, allow_pickle=False)
            self.mf_P = z["P"].astype(np.float64); self.mf_Q = z["Q"].astype(np.float64)
            self.mf_items = [str(x) for x in z["items"]]; self.mf_u = {str(u): k for k, u in enumerate(z["users"])}
        if not self.mf_u: return
        pairs = [(k, S.row[p]) for k, p in enumerate(self.mf_items) if p in S.row]
        S.mf = (self.mf_Q, np.array([a for a, _ in pairs], dtype=np.int64), np.array([b for _, b in pairs], dtype=np.int64))

    def user_mf(self, u):
        """The shopper's factor vector, or None (no history, or no factor file)."""
        k = self.mf_u.get(u) if self.mf_u else None
        return None if k is None else self.mf_P[k]

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

    # ---- T-054: views of earlier requests ----
    def load_prev_hist(self, frame) -> int:
        """frame: columns u, i, n (requests of the last 30 days of history_sessions with product i in the recent views)."""
        out = {}
        f = frame.sort_values("u", kind="stable")
        us = f.u.values; items = f.i.values; ns = f.n.values
        cut = np.r_[0, np.flatnonzero(us[1:] != us[:-1]) + 1, len(us)]
        for a, b in zip(cut[:-1], cut[1:]):
            out[us[a]] = (tuple(sys.intern(str(x)) for x in items[a:b]), tuple(int(x) for x in ns[a:b]))
        self.prv_hist = out
        return len(out)

    def add_request(self, u, rid, rv):
        """One request of the event (refresher thread). A product counts once per request."""
        items = tuple(dict.fromkeys(p for p in (rv or ()) if p))
        if not items: return
        d = self.prv_day.setdefault(u, {})
        for p in items: d[p] = d.get(p, 0) + 1
        self.prv_last[u] = (rid, items)

    def prev_views(self, u, rid=None):
        """{product: history requests + PRV_TODAY x event requests}, without the request being answered (`rid`): the
        refresher may have stored it already, and its own views are `islast` / `oinrv`, not earlier ones."""
        out = {}
        h = self.prv_hist.get(u)
        if h:
            for p, n in zip(h[0], h[1]): out[p] = float(n)
        d = self.prv_day.get(u)
        if d:
            last = self.prv_last.get(u)
            own = set(last[1]) if (last and rid is not None and last[0] == rid) else ()
            for p, n in list(d.items()):
                n = n - 1 if p in own else n
                if n > 0: out[p] = out.get(p, 0.0) + PRV_TODAY * n
        return out

    def load_hist_carousel(self, frame) -> int:
        """T-055. frame: columns u, i, b (1 = bought in the history carousel, 0 = only clicked)."""
        out = {}
        for u, i, b in zip(frame.u.values, frame.i.values, frame.b.values):
            e = out.get(u)
            if e is None: e = out[u] = ([], [])
            e[0 if b else 1].append(sys.intern(str(i)))
        self.hcar = {u: (tuple(e[0]), tuple(e[1])) for u, e in out.items()}
        return len(self.hcar)

    def wants_prv(self) -> bool:
        ks = (FEATS.index("prv"), FEATS.index("rqa"))
        sets = [self.w] + [w for w, _ in list(self.alt.values())]
        return any(float(w[seg][k]) != 0.0 for w in sets for seg in ("known", "new") for k in ks)

    def wants_hot(self) -> bool:
        """Does any weight set in use (committed or arm) give the burst feature a weight? If not, nobody asks for trends."""
        ks = (FEATS.index("hot"), FEATS.index("hotc"))
        sets = [self.w] + [w for w, _ in list(self.alt.values())]
        return any(float(w[seg][k]) != 0.0 for w in sets for seg in ("known", "new") for k in ks)

    def wants_oq(self) -> bool:
        """Does any weight set in use give the organic quality features a weight? If not, nobody builds them."""
        ks = [FEATS.index("orate"), FEATS.index("opop")]
        sets = [self.w] + [w for w, _ in list(self.alt.values())]
        return any(float(w[seg][k]) != 0.0 for w in sets for seg in ("known", "new") for k in ks)

    @property
    def ok(self): return self.snap is not None

    # ---- serving thread ----
    def user_state(self, u):
        """(bought, live carts not bought, history carts not bought, bought today). Copies: safe against concurrent add()."""
        bt = set(self.lbought.get(u, ()))
        b = bt | self.hbought.get(u, set())
        lc = set(self.lcart.get(u, ())) - b
        hc = {i: a for i, a in (self.hcart.get(u) or {}).items() if i not in b and i not in lc}
        ds = self.day_start
        if ds is not None:                               # b (the exclusion) is untouched: a purchase never comes back
            t = self.lbought_t.get(u) or {}
            bt = {i for i in bt if t.get(i, "~") >= ds}                  # "~" sorts after every date: unknown time = today
            if self.day_carts and lc:
                t = self.lcart_t.get(u) or {}
                h = self.hcart.get(u) or {}
                for i in [i for i in lc if t.get(i, "~") < ds]:
                    lc.discard(i); hc[i] = h.get(i, 0) + 1
        return b, lc, hc, bt, self.user_mix(u), self.user_mf(u)

    def scores(self, req, state, aff_obj, model=None):
        """(snapshot, score per product with dead / unavailable products at -inf)."""
        return self._scores(req, state, aff_obj, model)[:2]

    def _scores(self, req, state, aff_obj, model=None):
        """scores() plus the prior purchases of this shopper that are otherwise servable: (rows, their scores) or None (T-063)."""
        S = self.snap; rv = req.get("rv") or []
        bought, lc, hc = state[:3]; bt = state[3] if len(state) > 3 else ()
        aff = aff_obj.affinity_all(req["user_id"], rv)
        seg = "new" if req.get("is_new_user") else "known"
        w, b0 = (self.alt.get(model + "@home") if not rv else None) or self.alt[model] if model else (self.w, self.b)
        m = getattr(self, "alt_lq", {}).get(model) if model else None      # T-028: this arm asks for the corrected quality
        page = req.get("page", "product")
        prev = self.prev_views(req["user_id"], req.get("request_id")) if (w[seg][FEATS.index("prv")] != 0.0 or w[seg][FEATS.index("rqa")] != 0.0) else None
        X = features(S, aff, rv, page, hc, lc, bought_today=bt, seg=in_segment(req.get("device"), req.get("region")),
                     mix=state[4] if len(state) > 4 else None, mfu=state[5] if len(state) > 5 else None, lq=S.lqc if lq_target(m, seg == "new", page, rv) else None,
                     prev=prev, hcar=self.hcar.get(req["user_id"]))
        s = X @ w[seg] + b0[seg]
        if model and lc and (model + RC) in self.alt and recart_target(seg == "new", page, rv):
            # T-046: the history count comes from self.hcart because the served state drops re-carted products from hc
            h = self.hcart.get(req["user_id"])
            if h:
                wk = w[seg]; chn, cl = wk[FEATS.index("chn")], wk[FEATS.index("cl")]
                for p in lc:
                    n = h.get(p); k = S.row.get(p) if n else None
                    if k is not None:
                        gain = chn * math.log1p(n) - cl
                        if gain > 0: s[k] += gain
        dead = ~S.ok
        st = S.stale(req["user_id"])
        if st is not None:
            keep = [S.row[p] for p in list(hc) + list(lc) if p in S.row]
            # T-056: a product bought in the history carousel is not "viewed and never wanted": it keeps its place when
            # the arm weights `hcb` (live 14 Nov: 3 buys / 109 impressions for these pairs, the rate of the other hcb products)
            hb = self.hcar.get(req["user_id"]) if w[seg][FEATS.index("hcb")] != 0.0 else None
            if hb: keep += [S.row[p] for p in hb[0] if p in S.row]
            st[keep] = False; dead = dead | st
        prior = None
        if self.prior_start is not None:
            try:
                pb = self.prior_bought(req["user_id"])
                if pb:
                    k = np.array([S.row[p] for p in pb if p in S.row and not dead[S.row[p]]], dtype=int)
                    if len(k): prior = (k, s[k].copy())
                    if self.prior_allow: bought = set(bought) - pb
            except Exception: prior = None
        b = [S.row[p] for p in bought if p in S.row]
        if b: dead[b] = True
        s[dead] = -np.inf
        return S, s, prior

    def slate(self, req, state, aff_obj, n=10, exclude=(), model=None):
        S, s, prior = self._scores(req, state, aff_obj, model)
        s0 = s
        cap = getattr(self, "alt_cap", {}).get(model) if model else None
        out = None
        if cap:
            # T-061: at most `c` launched products in the list. Anything unexpected serves the uncapped list.
            try:
                c = cap.get(cap_key(req.get("is_new_user"), req.get("rv")))
                if c is not None:
                    own = set(req.get("rv") or ()) | set(state[1]) | set(state[2])
                    sc = cap_launched(S, s, int(c), exclude, own)
                    out = top_items(S, sc, n, exclude)
                    if len(out) == n: s = sc
                    else: out = None
            except Exception: out = None
        if out is None: out = top_items(S, s, n, exclude)
        xm = getattr(self, "alt_x", {}).get(model) if model else None
        if len(out) == n and x_target(xm, req.get("is_new_user"), req.get("page", "product"), req.get("rv")):
            out = self._explore(req, S, s, out, exclude)
        if self.prior_start is not None: self._prior_note(S, s0, prior, out, n, exclude)
        return out if len(out) == n and len(set(out)) == n else None

    def _prior_note(self, S, s, prior, out, n, exclude):
        """T-063 shadow diagnosis. Counts only; never changes `out`. In "exclude" mode: would any prior purchase enter
        the top n if it were not excluded (plain ranking, before the launched cap and the exploration slot)? In "allow"
        mode: how many were served."""
        try:
            c = self.prior_stats; c["requests"] += 1
            if prior is None: return
            k, v = prior
            c["requests_with_prior"] += 1; c["prior_candidates"] += len(k)
            ids = {S.ids[j] for j in k}
            if self.prior_allow:
                m = len(ids.intersection(out))
            else:
                s2 = s.copy(); s2[k] = v
                top = top_items(S, s2, n, exclude)
                m = len(ids.intersection(top))
                if m: c["top3_requests"] += bool(ids.intersection(top[:3]))
            if m: c["requests_entering"] += 1; c["products_entering"] += m
        except Exception: pass

    def _explore(self, req, S, s, out, exclude):
        """T-039 exploration arm: the LAST slot (10% of the impressions, ~3% of a slate's expected purchases) shows one
        product drawn uniformly from ranks 11..X_HI of this request's own ranking: valid, in stock, not bought, just not
        prioritised. Product/category pages with recent views only. Deterministic per request; any problem keeps `out`."""
        try:
            order = np.argsort(-s)[:X_HI + len(exclude) + len(out)]
            pool = [S.ids[k] for k in order if np.isfinite(s[k]) and S.ids[k] not in exclude and S.ids[k] not in out][:X_HI - len(out)]
            if not pool: return out
            key = str(req.get("request_id") or "") + "|" + str(req.get("user_id")) + "|" + "|".join(req.get("rv") or [])
            return out[:-1] + [pool[zlib.crc32(key.encode()) % len(pool)]]
        except Exception:
            return out
