"""Live trend detection from organic `shop.events` (T-008, I-018/I-019).

What it does (plain version): every refresh we count views per product in 5-minute buckets for the last
~3 hours. For each subcategory (and product) we compare its *share* of views in the last 15 minutes with
its usual share (median of the previous 15-minute blocks). A subcategory whose share jumps well beyond
what random noise explains is "hot". We expose a score multiplier and a list of hot items so the serving
loop can (a) add hot items as candidates and (b) tilt scores towards them.

Read-only: this module never writes to RawTree. `live.py` is NOT modified by this module; integration is
proposed in decisions.md (D-011).

    snap = trends.snapshot(query, sub_of)          # query = live.query, sub_of = {product_id: subcategory}
    snap.hot                                       # ['Kettles'] ...
    snap.multiplier(product_ids)                   # np.array, 1.0 for non-trending products
    snap.hot_items(pools_by_sub, n=10)             # candidates from hot subcategories

The same `compute()` is used by `trends_replay.py` offline, so serving and evaluation share one code path.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np, pandas as pd

BUCKET_MIN = 5          # width of a time bucket
RECENT = 3              # recent window = 3 buckets = 15 min
BASE = 36               # baseline = previous 36 buckets = 3 h
MIN_BASE = 6            # need at least 30 min of baseline before saying anything
K_SUB, K_PROD = 20.0, 5.0   # pseudo-views for shrinkage (lift -> 1 when there is little data)
HOT_LIFT, HOT_Z, HOT_MIN_VIEWS = 2.0, 6.0, 50   # a subcategory is "hot" if all three hold
ALPHA, CAP = 0.5, 3.0   # multiplier = clip(lift, 1, CAP) ** ALPHA  (conservative: sqrt of the lift)

SQL = """SELECT toUInt16(intDiv(dateDiff('second', ts::DateTime64(3), toDateTime64('{now}', 3)), {bsec})) age,
  product_id::String i, toUInt32(countIf(event_type::String = 'view')) v,
  toUInt32(countIf(event_type::String = 'add_to_cart')) a, toUInt32(countIf(event_type::String = 'purchase')) p
FROM shop.events
WHERE ts::DateTime64(3) > toDateTime64('{now}', 3) - INTERVAL {horizon} MINUTE AND ts::DateTime64(3) <= toDateTime64('{now}', 3)
GROUP BY age, i"""


def fetch_counts(query, now=None, recent=RECENT, base=BASE) -> pd.DataFrame:
    """One cheap aggregate query: rows (age bucket, product, views, carts, purchases). age 0 = newest bucket.
    `now` defaults to the newest event timestamp minus nothing: we lag 5 s to let late events land."""
    if now is None:
        now = (pd.Timestamp.now("UTC").tz_localize(None) - pd.Timedelta(seconds=5)).strftime("%Y-%m-%d %H:%M:%S")
    rows = query(SQL.format(now=now, bsec=BUCKET_MIN * 60, horizon=(recent + base) * BUCKET_MIN))
    return pd.DataFrame(rows, columns=["age", "i", "v", "a", "p"])


@dataclass
class Snapshot:
    sub_lift: dict = field(default_factory=dict)     # subcategory -> shrunk share lift (1 = normal)
    sub_z: dict = field(default_factory=dict)        # subcategory -> Poisson z-score of the recent count
    prod_lift: dict = field(default_factory=dict)    # product -> shrunk lift relative to its own subcategory
    hot: list = field(default_factory=list)          # hot subcategories, strongest first
    sub_of: dict = field(default_factory=dict)
    n_base: int = 0

    def multiplier(self, product_ids, alpha=ALPHA, cap=CAP, hot_only=True) -> np.ndarray:
        """Score multiplier per product. Non-hot subcategories get exactly 1.0 (no noise injected)."""
        hot = set(self.hot)
        out = np.ones(len(product_ids))
        for k, p in enumerate(product_ids):
            s = self.sub_of.get(p)
            if s is None or (hot_only and s not in hot): continue
            out[k] = min(max(self.sub_lift.get(s, 1.0), 1.0), cap) ** alpha
        return out

    def hot_items(self, pools_by_sub: dict, n=10) -> list:
        """Top items of each hot subcategory (pools_by_sub = live.py pools['sub'], already in-stock and ranked)."""
        out = []
        for s in self.hot: out += pools_by_sub.get(s, [])[:n]
        return out


def compute(counts: pd.DataFrame, sub_of: dict, recent=RECENT, base=BASE) -> Snapshot:
    """counts: rows (age, i, v[, a, p]) with age = bucket index back from 'now' (0 = newest)."""
    snap = Snapshot(sub_of=sub_of)
    if counts is None or len(counts) == 0: return snap
    c = counts[counts.age < recent + base]
    n_base = int(min(base, c.age.max() + 1 - recent)) if len(c) else 0
    snap.n_base = n_base
    if n_base < MIN_BASE: return snap
    c = c.assign(sub=c.i.map(sub_of)).dropna(subset=["sub"])
    rec, old = c[c.age < recent], c[(c.age >= recent) & (c.age < recent + n_base)]
    v_tot = float(rec.v.sum())
    if v_tot <= 0: return snap
    # --- subcategory level: robust baseline = median share over previous blocks of `recent` buckets
    blk = (old.age - recent) // recent
    sb = old.assign(blk=blk).pivot_table(index="blk", columns="sub", values="v", aggfunc="sum", fill_value=0)
    sb = sb[sb.sum(axis=1) > 0]
    share = sb.div(sb.sum(axis=1), axis=0).median()
    v_sub = rec.groupby("sub").v.sum()
    subs = share.index.union(v_sub.index)
    e = share.reindex(subs).fillna(0) * v_tot
    v = v_sub.reindex(subs).fillna(0)
    lift = (v + K_SUB) / (e + K_SUB); z = (v - e) / np.sqrt(e + 1.0)
    snap.sub_lift, snap.sub_z = lift.to_dict(), z.to_dict()
    hot = lift[(lift >= HOT_LIFT) & (z >= HOT_Z) & (v >= HOT_MIN_VIEWS)].sort_values(ascending=False)
    snap.hot = hot.index.tolist()
    # --- product level, relative to its own subcategory (is this product moving more than its shelf?)
    pv_old = old.groupby("i").v.sum(); pv_rec = rec.groupby("i").v.sum()
    prods = pv_old.index.union(pv_rec.index)
    psub = pd.Series(prods.map(sub_of), index=prods)
    sub_old = old.groupby("sub").v.sum()
    e_p = pv_old.reindex(prods).fillna(0) / psub.map(sub_old).replace(0, np.nan) * psub.map(v_sub)
    e_p = e_p.fillna(0)
    snap.prod_lift = ((pv_rec.reindex(prods).fillna(0) + K_PROD) / (e_p + K_PROD)).to_dict()
    return snap


def snapshot(query, sub_of: dict, now=None) -> Snapshot:
    """Fetch + compute. Safe to call from the refresher thread; on any error return a neutral snapshot."""
    try:
        return compute(fetch_counts(query, now), sub_of)
    except Exception as e:  # never break serving because of trends
        print("trends error", e)
        return Snapshot(sub_of=sub_of)


def window_snapshots(query, sub_of: dict, windows=(15, 5), now=None) -> dict:
    """Causal detectors from ONE background query. Windows are minutes, using the same five-minute buckets,
    three-hour baseline and thresholds. No shared mutable detector state; empty/error snapshots stay neutral."""
    if not windows or any(type(w) is not int or w not in (5, 15) for w in windows):
        raise ValueError("trend windows must be 5 or 15 minutes")
    windows = tuple(dict.fromkeys(windows))
    try:
        counts = fetch_counts(query, now, recent=max(windows) // BUCKET_MIN, base=BASE)
        return {w: compute(counts, sub_of, recent=w // BUCKET_MIN, base=BASE) for w in windows}
    except Exception as e:
        print("trend windows error", type(e).__name__, e, flush=True)
        return {w: Snapshot(sub_of=sub_of) for w in windows}


if __name__ == "__main__":  # python trends.py  -> print what is hot right now (read-only)
    import time
    from rt import q
    cat = q("""SELECT product_id::String i, argMax(subcategory::String, v) sub FROM (
        SELECT product_id, subcategory, '' v FROM shop.catalog UNION ALL
        SELECT product_id, subcategory, toString(ts) v FROM shop.catalog_updates) GROUP BY i""")
    sub_of = dict(zip(cat.i, cat["sub"]))
    t = time.time(); s = snapshot(lambda sql: q(sql).to_dict("records"), sub_of); dt = time.time() - t
    top = sorted(s.sub_lift.items(), key=lambda x: -x[1])[:8]
    print(f"query+compute {dt:.2f}s, baseline blocks of 5min: {s.n_base}, hot: {s.hot}")
    for k, v in top: print(f"  {k:22s} lift {v:5.2f}  z {s.sub_z[k]:6.1f}")
