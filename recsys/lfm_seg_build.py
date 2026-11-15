"""T-057 — what each shopper segment (device x region) buys: lfm_seg.json for the lfm features gsub / gbrand / gphr.

    cd recsys && python lfm_seg_build.py            # READ-ONLY RawTree, about 1 minute; writes lfm_seg.json

For each segment and each subcategory / brand / description phrase: log(organic purchases of the 60-day history + 5),
minus the segment's mean and minus the subcategory's (brand's, phrase's) mean over segments. So 0 = "this segment buys
this subcategory as much as any other segment does", +0.3 = about 35% more. The history has no shoppers of the final,
but a new shopper arrives with a device and a region, and that is all we know about them before their first views.
"""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PRIOR = 5.0


def pull():
    from rt import q
    def one(m):
        return q(f"""SELECT device::String dev, region::String reg, product_id::String i, countIf(event_type::String='purchase') p
            FROM shop.history_events WHERE cityHash64(product_id::String)%8={m} GROUP BY dev, reg, i""")
    with ThreadPoolExecutor(4) as ex: d = pd.concat(list(ex.map(one, range(8))))
    cat = q("SELECT product_id::String i, subcategory::String sub, brand::String brand, description::String description FROM shop.catalog")
    return d, cat


def residual(counts: pd.Series) -> pd.DataFrame:
    """counts indexed by (segment, level) -> two-way residual of log(count + PRIOR); rows = segments."""
    L = np.log(counts.unstack(fill_value=0) + PRIOR)
    L = L.sub(L.mean(axis=1), axis=0)
    return L.sub(L.mean(axis=0), axis=1)


def build(d: pd.DataFrame, cat: pd.DataFrame) -> dict:
    import cold_items
    d = d.assign(seg=d.dev + "|" + d.reg).merge(cat, on="i")
    out = {}
    for name, col in (("sub", "sub"), ("brand", "brand")):
        T = residual(d.groupby(["seg", col]).p.sum())
        out[name] = {s: {k: round(float(v), 4) for k, v in row.items()} for s, row in T.iterrows()}
    ph = {i: cold_items.attrs(t) for i, t in zip(cat.i, cat.description)}
    g = d.groupby(["seg", "i"]).p.sum().reset_index()
    rows = [(s, a, p) for s, i, p in zip(g.seg, g.i, g.p) for a in ph.get(i, ())]
    T = residual(pd.DataFrame(rows, columns=["seg", "a", "p"]).groupby(["seg", "a"]).p.sum()).reindex(columns=range(len(cold_items.ATTRS)), fill_value=0.0)
    out["phr"] = {s: [round(float(v), 4) for v in row.values] for s, row in T.iterrows()}
    return out


if __name__ == "__main__":
    d, cat = pull()
    out = build(d, cat)
    (HERE / "lfm_seg.json").write_text(json.dumps(out, ensure_ascii=False, sort_keys=True))
    v = np.array([x for s in out["sub"].values() for x in s.values()])
    print(len(out["sub"]), "segments;", int(d.p.sum()), "purchases; gsub sd %.3f, max |value| %.2f" % (v.std(), np.abs(v).max()))
