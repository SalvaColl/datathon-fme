"""T-SA01 / H2: does time since launch predict new-product purchases beyond prior + Bayesian live update?

    cd recsys
    python alpha_h2.py --pull     # READ-ONLY: launches + organic events per product per 10 min -> data/alpha/ (git-ignored)
    python alpha_h2.py            # analysis on the cache (deterministic)

Reference (what live_quality / cold_lq already do): rate_b = (purchases before b + K * prior) / (views before b + K),
prior = live_quality.default_prior() (cold_items GLM), K = 100. For every 10-min bucket b of a new product:
expected purchases E_b = views_b * rate_b, observed O_b. O/E by age since launch shows what the reference misses.
Controls: (1) clock: established products in the same clock buckets, rate from their 60-day history, O/E per bucket;
new-product O/E is divided by it (removes global time effects); (2) negative control: 300 established products given a
fake launch at the same times, same computation, should be flat. Discovery = 10:00 batch, validation = later batches.
Poisson 95% CI on O/E (exact, via chi-square). Organic shop.events only; no feedback, no simulator labels.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import chi2

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
CACHE = HERE / "data" / "alpha"
K = 100.0
AGE_BINS = [0, 10, 30, 60, 120, 10_000]
AGE_LABELS = ["0-10", "10-30", "30-60", "60-120", "120+"]


def pull():
    from datetime import datetime, timezone
    from rt import q
    CACHE.mkdir(parents=True, exist_ok=True)
    cat = q("""SELECT product_id::String product_id, argMax(category::String,v) category, argMax(subcategory::String,v) sub,
      argMax(brand::String,v) brand, argMax(price_eur::Float64,v) price, argMax(description::String,v) description,
      min(if(chg = 'new_product', t, NULL)) launched
      FROM (SELECT product_id, category, subcategory, brand, price_eur, description, '' v, '' chg, NULL t FROM shop.catalog
            UNION ALL SELECT product_id, category, subcategory, brand, price_eur, description, toString(ts), change::String,
                             ts::DateTime64(3) FROM shop.catalog_updates) GROUP BY product_id""")
    ev = q("""SELECT product_id::String i, toStartOfTenMinutes(ts::DateTime64(3))::String b, countIf(event_type::String='view') v,
      countIf(event_type::String='add_to_cart') a, countIf(event_type::String='purchase') p FROM shop.events
      WHERE ts::DateTime64(3) < toStartOfTenMinutes(now()) GROUP BY i, b""")
    cat.to_parquet(CACHE / "catalog.parquet"); ev.to_parquet(CACHE / "events_10min.parquet")
    (CACHE / "meta.json").write_text(json.dumps({"observed_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                                  "rows": len(ev), "launched": int(cat.launched.notna().sum())}))


def oe_ci(o, e):
    lo = chi2.ppf(0.025, 2 * o) / 2 if o > 0 else 0.0
    hi = chi2.ppf(0.975, 2 * (o + 1)) / 2
    return round(o / e, 3) if e else None, [round(lo / e, 3), round(hi / e, 3)] if e else None


def rows_for(products, ev, prior, launch, hist=None):
    """One row per (product, bucket >= launch): views, purchases, reference rate from strictly earlier data."""
    out = []
    g = ev[ev.i.isin(products)].sort_values("t")
    for p, x in g.groupby("i"):
        L = launch[p]; x = x[x.t >= L]
        hv, hp = (hist.get(p, (0.0, 0.0)) if hist is not None else (0.0, 0.0))
        cv, cp = 0.0, 0.0
        for t, v, pu in zip(x.t, x.v, x.p):
            rate = (hp + cp + K * prior[p]) / (hv + cv + K)
            out.append((p, t, (t - L).total_seconds() / 60, v, pu, v * rate))
            cv += v; cp += pu
    return pd.DataFrame(out, columns=["i", "t", "age", "v", "o", "e"])


def analyse():
    import live_quality
    meta = json.loads((CACHE / "meta.json").read_text())
    cat = pd.read_parquet(CACHE / "catalog.parquet").set_index("product_id")
    ev = pd.read_parquet(CACHE / "events_10min.parquet"); ev["t"] = pd.to_datetime(ev.b)
    for c in "vap": ev[c] = ev[c].astype(float)
    pr = live_quality.default_prior()
    prior = pd.Series(pr(cat.assign(description=cat.description.fillna(""))), index=cat.index)
    new = cat[cat.launched.notna()].copy(); new["L"] = pd.to_datetime(new.launched).dt.floor("10min")
    batches = sorted(new.L.unique())
    # clock control: established products, history-based rate, O/E per clock bucket
    ui = pd.read_parquet(HERE / "data" / "user_item_all.parquet", columns=["i", "v", "p"])
    h = ui.groupby("i")[["v", "p"]].sum()
    hist = {p: (float(r.v), float(r.p)) for p, r in h.iterrows()}
    old = ev[ev.i.isin(h.index)].copy()
    old["e"] = old.v * old.i.map(lambda p: (hist[p][1] + K * prior.get(p, 0.05)) / (hist[p][0] + K))
    clock = old.groupby("t").agg(o=("p", "sum"), e=("e", "sum")); clock["r"] = clock.o / clock.e
    R = rows_for(list(new.index), ev, prior, new.L.to_dict())
    R["batch"] = R.i.map(new.L); R["clock"] = R.t.map(clock.r).fillna(1.0); R["e_adj"] = R.e * R.clock
    R["age_bin"] = pd.cut(R.age, AGE_BINS, right=False, labels=AGE_LABELS)
    # negative control: 300 established products with fake launches at the real batch times, prior from history
    rng = np.random.default_rng(20261114)
    fake = list(rng.choice(sorted(set(old.i)), size=300, replace=False))
    fl = {p: batches[k % len(batches)] for k, p in enumerate(fake)}
    N = rows_for(fake, ev, prior, fl, hist=hist)
    N["clock"] = N.t.map(clock.r).fillna(1.0); N["e_adj"] = N.e * N.clock
    N["age_bin"] = pd.cut(N.age, AGE_BINS, right=False, labels=AGE_LABELS)
    out = {"observed_utc": meta["observed_utc"], "batches": [str(b) for b in batches],
           "clock_oe_range_established": [round(float(clock.r.min()), 3), round(float(clock.r.max()), 3)]}
    for name, sel in (("discovery (10:00 batch)", R.batch == batches[0]), ("validation (later batches)", R.batch != batches[0]),
                      ("negative control (fake launch, established)", None)):
        D = N if sel is None else R[sel]
        tab = {}
        for a, g in D.groupby("age_bin", observed=True):
            oe, ci = oe_ci(g.o.sum(), g.e_adj.sum())
            tab[str(a)] = dict(products=int(g.i.nunique()), views=int(g.v.sum()), purchases=int(g.o.sum()),
                               expected=round(float(g.e_adj.sum()), 1), OE=oe, CI95=ci,
                               views_per_product_bucket=round(float(g.v.mean()), 1))
        out[name] = tab
    # views dynamics (exposure, not quality): new vs established views per product per bucket, by age
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pull", action="store_true"); ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    if a.pull:
        pull()
    res = analyse()
    print(json.dumps(res, indent=1))
    if a.out:
        a.out.write_text(json.dumps(res, indent=1))
