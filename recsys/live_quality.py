"""live_quality — product quality measured on the live organic stream (T-018, I-180..I-184, E-180..E-183, D-180).

Plain version. `shop.events` tells us, minute by minute, how often shoppers buy a product after viewing it. That
is ~15x more signal than the feedback of our own carousel. This module keeps three numbers up to date:

  1. rate(product)  purchases per view = (history + live purchases + K * prior) / (history + live views + K).
                    For a product with 60 days of history the live stream barely moves it (E-180: nothing to gain
                    there, products do not drift). For a product launched during the event it is the ONLY evidence:
                    the prior is the attribute model (category x description phrases x brand x price) and the live
                    views take over after ~100 views.
  2. sub_mult(sub)  is a whole subcategory selling more than its products normally do in the last 30 minutes?
                    observed purchases / expected purchases, shrunk, and only when the excess is statistically
                    clear (z >= 3 and >= x1.3); otherwise exactly 1. These are the "trend bursts" (x2.6, I-181).
  3. promo(product) is the product discounted right now (>= 5% below its catalogue price)? Organic x1.145 (I-182).

and turns them into a carousel quality `q` for qrank.py: on the 5,000 historical products the carousel quality is
the organic rate SQUARED (log q = a_sub + 2.0 * log rate, r = 0.94 within subcategory, I-183), so a new product
gets q = exp(a_sub + beta * log rate) instead of the median of its subcategory, and hot subcategories get
q * sub_mult ** gamma.

Read-only: never writes to RawTree. Serving hook (default OFF, hot switch, see `install`):
    data/lq.json = {"mode": "off" | "on" | "ab"}      ab = 50/50 by user hash (salt differs from policy.json's A/B)
Only the plain qrank path is touched (requests the active policy.json variant routes to qrank and that are not
re-ranked by the affinity policy). Answers built with live quality get model_version "<old>+lq".

    lq = LiveQuality(prior=attribute_prior)            # prior(cat_df) -> Series of purchases/view, optional
    lq.update(cat, hist_item, live_item, window)       # frames indexed by product id: views / purchases
    lq.rate, lq.sub_mult, lq.hot                       # Series, dict, list
    q2 = lq.adjust_q(q)                                # dict product -> carousel quality with live corrections
"""
from __future__ import annotations
import json, os, threading, time, traceback, zlib
from pathlib import Path
import numpy as np, pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
POLICY = str(DATA / "lq.json")
MODES = ("off", "on", "ab")

K_PROD = 100.0      # prior strength in views (E-180: best for new products among 30/100/300/1000; cold_items uses 100 too)
K_SUB = 20.0        # prior strength in expected purchases for the subcategory multiplier (E-180)
WINDOW_MIN = 30     # rolling window for the subcategory multiplier (15..60 min are equivalent in E-180)
HOT_MULT, HOT_Z = 1.3, 3.0      # gate: below this the multiplier is exactly 1 (ungated costs likelihood on calm products)
MULT_CAP = 4.0
PROMO_DISCOUNT, PROMO_LIFT = 0.95, 1.145    # price <= 95% of catalogue price -> organic purchases/view x1.145 (E-181)
BETA = 2.0          # log q = a_sub + BETA * log rate   (cross-section of 5,000 products, E-182)
GAMMA = 1.0         # q multiplier for hot subcategories / promos = organic lift ** GAMMA (1 = carry the measured lift 1:1)

SQL_WINDOW = """SELECT product_id::String i, toUInt32(countIf(event_type::String = 'view')) v,
  toUInt32(countIf(event_type::String = 'purchase')) p
FROM shop.events WHERE ts::DateTime64(3) > now64(3) - INTERVAL {w} MINUTE GROUP BY i"""
SQL_NEW = """SELECT product_id::String i, argMax(description::String, ts::String) description
FROM shop.catalog_updates WHERE change::String = 'new_product' GROUP BY i"""
SQL_BASE_PRICE = "SELECT product_id::String i, price_eur::Float64 price FROM shop.catalog"


def _counts(df, idx, v="v", p="p"):
    """-> (views, purchases) float arrays aligned to idx; df may be None, or use it_v/it_p column names."""
    if df is None or len(df) == 0: return np.zeros(len(idx)), np.zeros(len(idx))
    if v not in df.columns: v, p = "it_v", "it_p"
    d = df.reindex(idx)
    return d[v].fillna(0).to_numpy(float), d[p].fillna(0).to_numpy(float)


class LiveQuality:
    def __init__(self, prior=None, k_prod=K_PROD, k_sub=K_SUB, beta=BETA, gamma=GAMMA, promo_q=False):
        self.prior, self.k_prod, self.k_sub, self.beta, self.gamma, self.promo_q = prior, k_prod, k_sub, beta, gamma, promo_q
        self.rate = pd.Series(dtype=float)       # product -> organic purchases per view (posterior mean)
        self.sub_mult, self.sub_z, self.hot = {}, {}, []
        self.promo, self.new, self.sub_of, self.cat_of = set(), set(), {}, {}
        self.updated = 0.0

    def update(self, cat: pd.DataFrame, hist_item=None, live_item=None, window=None, promo=(), known=None):
        """cat: live catalogue (index product id; category, sub[, brand, price, description]).
        hist_item / live_item / window: per-product ORGANIC counts (columns v,p or it_v,it_p): 60-day history, the event
        so far, and the last WINDOW_MIN minutes. Purchases of our own carousel must not be in them (their impressions
        are not views): in the writer pass LiveTables.organic_item_frame(), never item_frame() (T-047). promo: ids discounted now. known: ids with a historical q
        (everything else is treated as new for `adjust_q`). All state is replaced in one step (thread-safe reads)."""
        idx = cat.index
        hv, hp = _counts(hist_item, idx); lv, lp = _counts(live_item, idx); wv, wp = _counts(window, idx)
        g = (hp.sum() + lp.sum() + 1.0) / (hv.sum() + lv.sum() + 20.0)
        pr = None
        if self.prior is not None:
            try: pr = np.asarray(self.prior(cat), float)
            except Exception as e: print("live_quality prior failed, using subcategory rate:", type(e).__name__, e, flush=True)
        sub = cat["sub"].to_numpy()
        if pr is None or len(pr) != len(idx) or not np.isfinite(pr).all():
            # fallback prior: rate of the subcategory (history + live), shrunk to the global rate with 300 views
            s = pd.DataFrame({"sub": sub, "v": hv + lv, "p": hp + lp}).groupby("sub")[["v", "p"]].sum()
            pr = ((s.p + 300 * g) / (s.v + 300)).reindex(sub).to_numpy()
        rate = (hp + lp + self.k_prod * pr) / (hv + lv + self.k_prod)
        # subcategory multiplier: purchases of the last window vs what these views normally produce
        w = pd.DataFrame({"sub": sub, "e": wv * rate, "p": wp}).groupby("sub")[["e", "p"]].sum()
        m = (w.p + self.k_sub) / (w.e + self.k_sub); z = (w.p - w.e) / np.sqrt(w.e + 1.0)
        hot = m[(m >= HOT_MULT) & (z >= HOT_Z)].sort_values(ascending=False)
        new = set(idx) - set(known) if known is not None else set(idx[(hv == 0)])
        self.__dict__.update(rate=pd.Series(rate, index=idx), sub_mult={s: float(min(v, MULT_CAP)) for s, v in hot.items()},
                             sub_z=z.to_dict(), hot=hot.index.tolist(), promo=set(promo) & set(idx), new=new,
                             sub_of=dict(zip(idx, sub)), cat_of=cat["category"].to_dict(), updated=time.time())
        return self

    def multiplier(self, ids, promo=True) -> np.ndarray:
        """Organic lift right now per product (1.0 unless its subcategory is hot or it is discounted)."""
        out = np.ones(len(ids))
        for k, i in enumerate(ids):
            out[k] = self.sub_mult.get(self.sub_of.get(i), 1.0) * (PROMO_LIFT if (promo and i in self.promo) else 1.0)
        return out

    def live_rate(self, ids) -> np.ndarray:
        """Expected organic purchases per view right now: posterior rate x hot subcategory x promo."""
        return self.rate.reindex(ids).to_numpy(float) * self.multiplier(ids)

    def adjust_q(self, q: dict) -> dict:
        """Carousel quality with live corrections. Old products keep their q (x hot multiplier ** gamma); products
        without q get exp(a_sub + beta * log rate), a_sub = median over the old products of the subcategory
        (then category, then everything)."""
        if not len(self.rate): return dict(q)
        r = self.rate
        old = [i for i in r.index if i in q and q[i] > 0]
        out = dict(q)
        if old:
            lq = np.log(np.array([q[i] for i in old])); ls = np.log(r.reindex(old).to_numpy())
            a = pd.DataFrame({"a": lq - self.beta * ls, "sub": [self.sub_of[i] for i in old], "cat": [self.cat_of[i] for i in old]})
            a_sub, a_cat, a_all = a.groupby("sub").a.median(), a.groupby("cat").a.median(), float(a.a.median())
            for i in r.index:
                if i in q: continue
                ai = a_sub.get(self.sub_of.get(i), a_cat.get(self.cat_of.get(i), a_all))
                out[i] = float(np.exp(ai + self.beta * np.log(r[i])))
        for i in r.index:
            if i not in out: continue
            m = self.sub_mult.get(self.sub_of.get(i), 1.0) * (PROMO_LIFT if (self.promo_q and i in self.promo) else 1.0)
            if m != 1.0: out[i] = out[i] * m ** self.gamma
        return out


# ---------------------------------------------------------------- attribute prior (reuse, never duplicate)
def default_prior():
    """prior(cat) -> purchases/view from metadata. Uses cold_items' attribute GLM (cold_prior.json). When the T-017
    attribute model lands, pass its predictor to LiveQuality(prior=...) instead; nothing else changes."""
    try:
        if __package__: from . import cold_items
        else: import cold_items
        cp = cold_items.ColdPrior.from_json(json.loads(cold_items.ART.read_text())["prior"])
    except Exception as e:
        print("live_quality: attribute prior not available:", type(e).__name__, e, flush=True); return None

    def prior(cat):
        d = cat if "description" in cat.columns else cat.assign(description="")
        return cp.predict(d.assign(description=d.description.fillna(""))).cr.to_numpy()
    return prior


# ---------------------------------------------------------------- serving hook (default off)
_state = {"mode": "off", "mtime": None, "checked": 0.0, "errors": 0, "served": 0, "t": time.time()}
LQ = None          # LiveQuality
QR2 = None         # qrank.Ranker with the adjusted q
_touched = set()   # user ids answered by QR2 in the current batch


def mode():
    now = time.time()
    if now - _state["checked"] > 1.0:
        _state["checked"] = now
        try:
            mt = os.path.getmtime(POLICY)
            if mt != _state["mtime"]:
                m = json.load(open(POLICY)).get("mode", "off"); m = m if m in MODES else "off"
                if m != _state["mode"]: print(f"live_quality mode -> {m}", flush=True)
                _state.update(mode=m, mtime=mt)
        except FileNotFoundError:
            if _state["mode"] != "off": print("live_quality mode -> off (no policy file)", flush=True)
            _state.update(mode="off", mtime=None)
        except Exception as e:
            print("live_quality policy read error (keeping mode)", e, flush=True)
    return _state["mode"]


def treated(user_id) -> bool: return zlib.crc32(("lq:" + user_id).encode()) % 2 == 1


def _err(where):
    _state["errors"] += 1
    if _state["errors"] <= 20: print("live_quality error in", where, flush=True); traceback.print_exc()


def refresh(g, desc, base_price):
    """One refresh: read-only queries + rebuild QR2. g = live.py globals()."""
    global QR2
    QR, query, st = g["QR"], g["query"], g["state"]
    cat = st.get("cat")
    if QR is None or cat is None: return False
    unavail = set(st.get("unavail") or ()) | set(st.get("stock_out") or ())
    for r in query(SQL_NEW): desc.setdefault(r["i"], r["description"])
    if not base_price: base_price.update({r["i"]: float(r["price"]) for r in query(SQL_BASE_PRICE)})
    window = pd.DataFrame(query(SQL_WINDOW.format(w=WINDOW_MIN)), columns=["i", "v", "p"]).set_index("i")
    # T-047: organic counts only. LIVE.item_frame() also holds the purchases of our own carousel, without their impressions
    with g["feature_lock"]: live_item = getattr(g["LIVE"], "organic_item_frame", g["LIVE"].item_frame)()
    c = cat.assign(description=[desc.get(i, "") for i in cat.index])
    bp = pd.Series(base_price).reindex(cat.index)
    promo = cat.index[(cat.price.astype(float) <= PROMO_DISCOUNT * bp).fillna(False).to_numpy()]
    LQ.update(c, g["BASE"]["item"], live_item, window, promo=promo, known=set(QR.q))
    r2 = type(QR)(QR.model, LQ.adjust_q(QR.q), QR.meta, QR.viewed_factor)
    r2.set_catalog(cat, unavail)
    QR2 = r2
    return True


def install(g, period=30.0, start_thread=True):
    """Call once from live.initialize(): `live_quality.install(globals())`. Inert until data/lq.json says on/ab.
    Wraps QR.slates and predict; every wrapper returns the original result on any exception."""
    global LQ
    QR = g.get("QR")
    if QR is None: print("live_quality not installed: qrank is not loaded", flush=True); return
    LQ = LiveQuality(prior=default_prior())
    desc, base_price = {}, {}
    o_slates, o_predict = QR.slates, g["predict"]

    def slates(reqs, *a, **k):
        m = _state["mode"]; r2 = QR2
        if m == "off" or r2 is None or a or k or time.time() - LQ.updated > 300:   # stale live data -> plain qrank
            return o_slates(reqs, *a, **k)
        try:
            pick = [j for j, r in enumerate(reqs) if m == "on" or treated(r.get("user_id", ""))]
            got = dict(zip(pick, r2.slates([reqs[j] for j in pick]))) if pick else {}
            got = {j: s for j, s in got.items() if s is not None and len(set(s)) == 10}
        except Exception:
            _err("slates"); got = {}
        rest = [j for j in range(len(reqs)) if j not in got]          # control arm, and anything QR2 could not answer
        out = [None] * len(reqs)
        for j, s in zip(rest, o_slates([reqs[j] for j in rest]) if rest else []): out[j] = s
        for j, s in got.items():
            out[j] = s; _touched.add(reqs[j].get("user_id"))
        return out

    def predict(reqs):
        mode(); _touched.clear()
        out = o_predict(reqs)
        if not _touched: return out
        try:
            user = {r["request_id"]: r["user_id"] for r in reqs}
            for ans in out:
                if ans["model_version"] == g["VERSION_Q"] and user.get(ans["request_id"]) in _touched:
                    ans["model_version"] += "+lq"; _state["served"] += 1
            if time.time() - _state["t"] > 60:
                print(f"live_quality mode={_state['mode']} last ~60s: slates {_state['served']}, hot {LQ.hot}, "
                      f"new products {len(LQ.new)}, promo {len(LQ.promo)}, errors {_state['errors']}", flush=True)
                _state.update(t=time.time(), served=0)
        except Exception: _err("predict")
        return out

    def loop():
        while True:
            try:
                if mode() != "off" or QR2 is None: refresh(g, desc, base_price)   # keep one warm copy, then only when on
            except Exception: _err("refresh")
            time.sleep(period)

    QR.slates = slates; g["predict"] = predict
    if start_thread: threading.Thread(target=loop, daemon=True, name="live_quality").start()
    print(f"live_quality installed, mode={mode()}", flush=True)
    return dict(desc=desc, base_price=base_price)


if __name__ == "__main__":   # python live_quality.py -> what the stream says right now (read-only)
    from rt import q
    query = lambda sql: q(sql).to_dict("records")
    cat = q("""SELECT product_id::String i, argMax(category::String, v) category, argMax(subcategory::String, v) sub,
      argMax(brand::String, v) brand, argMax(price_eur::Float64, v) price, argMax(description::String, v) description
      FROM (SELECT product_id, category, subcategory, brand, price_eur, description, '' v FROM shop.catalog UNION ALL
            SELECT product_id, category, subcategory, brand, price_eur, description, toString(ts) v FROM shop.catalog_updates)
      GROUP BY i""").set_index("i")
    hist = q("""SELECT product_id::String i, toUInt32(countIf(event_type::String='view')) v,
      toUInt32(countIf(event_type::String='purchase')) p FROM shop.history_events GROUP BY i""").set_index("i")
    live = q("""SELECT product_id::String i, toUInt32(countIf(event_type::String='view')) v,
      toUInt32(countIf(event_type::String='purchase')) p FROM shop.events GROUP BY i""").set_index("i")
    t = time.time()
    win = pd.DataFrame(query(SQL_WINDOW.format(w=WINDOW_MIN)), columns=["i", "v", "p"]).set_index("i")
    bp = pd.Series({r["i"]: float(r["price"]) for r in query(SQL_BASE_PRICE)}).reindex(cat.index)
    promo = cat.index[(cat.price.astype(float) <= PROMO_DISCOUNT * bp).fillna(False).to_numpy()]
    lq = LiveQuality(prior=default_prior()).update(cat, hist, live, win, promo=promo, known=set(hist.index))
    print(f"window query + update {time.time() - t:.2f}s | products {len(cat)}, new {len(lq.new)}, discounted now {len(lq.promo)}")
    print("hot subcategories (multiplier, z):", [(s, round(lq.sub_mult[s], 2), round(lq.sub_z[s], 1)) for s in lq.hot] or "none")
    n = pd.DataFrame({"rate": lq.rate.reindex(sorted(lq.new)), "views": live.v.reindex(sorted(lq.new)), "buys": live.p.reindex(sorted(lq.new))})
    print("new products by live rate:\n", n.sort_values("rate", ascending=False).head(8).round(4).to_string())
