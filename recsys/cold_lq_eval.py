"""E-CS01: does cold_lq place today's new products at the right quality rank of their subcategory? (T-CS01)

    cd recsys
    python cold_lq_eval.py --pull      # READ-ONLY RawTree -> data/coldlq/live_snapshot.json (git-ignored), then evaluates
    python cold_lq_eval.py             # evaluate the cached snapshot (deterministic: fixed bootstrap seed)

Strict time split per launch batch L (all launches so far land on exact hours, 100 products each):
  * features: catalogue + description (prior), plus the product's organic events in [L, L+h) for h = 0 / 30 / 60 min;
  * target:   the product's organic purchase/view in [L+h, E), E = next launch batch or end of data (max 4 h),
    turned into a REALIZED QUANTILE among the established products of the same subcategory in the same window.
  * prediction: the lq the serving would use, turned into a PREDICTED QUANTILE among the same established products'
    lq (log of qrank's history q, which is what lfm/qrank compare against).
Variants (all through cold_lq.ColdLQ -> Javi's live_quality.LiveQuality, T-018): current = qrank's fallback (median
q of the subcategory); sub_live = ablation without the phrase prior (live_quality's own fallback: subcategory rate,
K=300); glm = cold_items attribute prior only (no live counts); glm_live = prior + live views (what cold_lq ships).
Metrics: mean |predicted - realized quantile|, Spearman between them, precision/recall of the realized top quartile;
95% CI of the MAE difference vs current by bootstrap over products (2,000 draws, seed 20261114).
Only organic shop.events and the catalogue are used; no feedback, no simulator labels, no league test period.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
SNAP = HERE / "data" / "coldlq" / "live_snapshot.json"
MIN_TARGET_VIEWS, SEED, DRAWS = 30, 20261114, 2000


def pull():
    from datetime import datetime, timezone
    import rt  # noqa: F401  (credentials from ../.env, read-only queries)
    from rt import q
    newp = q("""SELECT product_id::String product_id, min(ts::DateTime64(3))::String launched, argMax(category::String, ts::String) category,
      argMax(subcategory::String, ts::String) sub, argMax(brand::String, ts::String) brand, argMax(price_eur::Float64, ts::String) price,
      argMax(description::String, ts::String) description FROM shop.catalog_updates WHERE change::String='new_product' GROUP BY product_id""")
    ev = q("""SELECT product_id::String i, toStartOfTenMinutes(ts::DateTime64(3))::String b, countIf(event_type::String='view') v,
      countIf(event_type::String='add_to_cart') a, countIf(event_type::String='purchase') p FROM shop.events
      WHERE ts::DateTime64(3) < toStartOfTenMinutes(now()) GROUP BY i, b""")
    SNAP.parent.mkdir(parents=True, exist_ok=True)
    json.dump(dict(observed_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"), new_products=newp.to_dict("records"),
                   events_10min=ev.to_dict("records")), open(SNAP, "w"))


def load():
    import joblib
    import cold_lq, live_quality
    s = json.load(open(SNAP))
    newp = pd.DataFrame(s["new_products"]).set_index("product_id")
    ev = pd.DataFrame(s["events_10min"]); ev["t"] = pd.to_datetime(ev.b)
    for c in "vap": ev[c] = ev[c].astype(float)
    base = pd.read_parquet(HERE / "data" / "catalog.parquet").set_index("product_id")
    cat = pd.concat([base[["category", "sub", "brand", "price"]], newp[["category", "sub", "brand", "price"]]])
    ui = pd.read_parquet(HERE / "data" / "user_item_all.parquet", columns=["i", "v", "p"])
    hist = ui.groupby("i")[["v", "p"]].sum().rename(columns={"v": "it_v", "p": "it_p"})
    q = joblib.load(HERE / "data" / "qrank.joblib")["q"]
    desc = newp.description.to_dict()
    variants = {"sub_live": cold_lq.ColdLQ(live_quality.LiveQuality(prior=None)),   # ablation: no phrase prior
                "glm_live": cold_lq.ColdLQ()}                                       # as shipped (live_quality defaults)
    return s, newp, ev, cat, q, hist, desc, variants


def current_lq(q, cat, products):
    """qrank.set_catalog's rule for products without q: median q of the subcategory, then category, then global."""
    qs = pd.Series(q, dtype=float).reindex(cat.index)
    qs = qs.fillna(qs.groupby(cat["sub"]).transform("median")).fillna(qs.groupby(cat.category).transform("median")).fillna(qs.median())
    return np.log(qs.clip(lower=1e-6)).reindex(products).to_dict()


def evaluate(h_list=(0, 30, 60)):
    s, newp, ev, cat, q, hist, desc, V = load()
    lq_old = np.log(pd.Series(q, dtype=float).clip(lower=1e-6))
    end_data = ev.t.max() + pd.Timedelta(minutes=10)
    launches = sorted(pd.to_datetime(newp.launched).dt.floor("10min").unique())
    rows, floor = [], []
    for j, L in enumerate(launches):
        prods = newp.index[pd.to_datetime(newp.launched).dt.floor("10min") == L]
        E_cap = min(launches[j + 1] if j + 1 < len(launches) else end_data, L + pd.Timedelta(hours=4), end_data)
        cur = current_lq(q, cat, list(prods))
        for h in h_list:
            a, b = L + pd.Timedelta(minutes=h), E_cap
            if b - a < pd.Timedelta(minutes=30):
                continue
            early = ev[(ev.t >= L) & (ev.t < a)].groupby("i")[["v", "p"]].sum().rename(columns={"v": "it_v", "p": "it_p"})
            tgt = ev[(ev.t >= a) & (ev.t < b)].groupby("i")[["v", "p"]].sum()
            if h == 0:   # noise floor: established products, history lq quantile vs realized quantile, same windows/subs
                for sub, g in cat.loc[[x for x in tgt.index[tgt.v >= MIN_TARGET_VIEWS] if x in lq_old.index and x in cat.index]].groupby("sub"):
                    if len(g) >= 8:
                        rr = ((tgt.loc[g.index, "p"] + 0.5) / (tgt.loc[g.index, "v"] + 10)).rank(pct=True)
                        floor.extend(np.abs(lq_old.loc[g.index].rank(pct=True) - rr).tolist())
            pred = {"current": cur,
                    "sub_live": V["sub_live"].estimate(q, cat, hist, early, desc),
                    "glm": V["glm_live"].estimate(q, cat, hist, None, desc),
                    "glm_live": V["glm_live"].estimate(q, cat, hist, early, desc)}
            for p in prods:
                if p not in tgt.index or tgt.at[p, "v"] < MIN_TARGET_VIEWS:
                    continue
                sub = cat.at[p, "sub"]
                est = [x for x in cat.index[(cat["sub"] == sub).values] if x in lq_old.index and x in tgt.index and tgt.at[x, "v"] >= MIN_TARGET_VIEWS]
                if len(est) < 8:
                    continue
                r_est = (tgt.loc[est, "p"] + 0.5) / (tgt.loc[est, "v"] + 10)
                r_new = (tgt.at[p, "p"] + 0.5) / (tgt.at[p, "v"] + 10)
                row = dict(batch=str(L), h=h, product=p, sub=sub, n_ref=len(est), target_views=float(tgt.at[p, "v"]),
                           realized=float((r_est < r_new).mean() + 0.5 * (r_est == r_new).mean()))
                ref_lq = lq_old.loc[est].values
                for k, d in pred.items():
                    row[k] = float((ref_lq < d[p]).mean() + 0.5 * (ref_lq == d[p]).mean())
                rows.append(row)
    R = pd.DataFrame(rows)
    rng = np.random.default_rng(SEED)
    out = {"observed_utc": s["observed_utc"], "n_rows": len(R), "launch_batches": [str(x) for x in launches], "by_h": {},
           "established_noise_floor_mae": round(float(np.mean(floor)), 3), "established_noise_floor_n": len(floor)}
    for h, g in R.groupby("h"):
        res = {"products": int(len(g)), "median_ref_products": int(g.n_ref.median()), "median_target_views": int(g.target_views.median())}
        err = {k: np.abs(g[k].values - g.realized.values) for k in ("current", "sub_live", "glm", "glm_live")}
        top = g.realized.values >= 0.75
        for k, e in err.items():
            pt = g[k].values >= 0.75
            res[k] = dict(mae_quantile=round(float(e.mean()), 3),
                          spearman=round(float(spearmanr(g[k], g.realized)[0]), 3) if g[k].nunique() > 1 else None,
                          top25_precision=round(float((pt & top).sum() / max(1, pt.sum())), 3) if pt.sum() else None,
                          top25_recall=round(float((pt & top).sum() / max(1, top.sum())), 3),
                          predicted_top25=int(pt.sum()))
            if k != "current":
                idx = rng.integers(0, len(g), size=(DRAWS, len(g)))
                diff = (e[idx] - err["current"][idx]).mean(1)
                res[k]["mae_minus_current_CI95"] = [round(float(np.percentile(diff, 2.5)), 3), round(float(np.percentile(diff, 97.5)), 3)]
        res["realized_top25"] = int(top.sum())
        out["by_h"][int(h)] = res
    return out, R


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pull", action="store_true"); ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    if a.pull:
        pull()
    out, R = evaluate()
    print(json.dumps(out, indent=1))
    if a.out:
        a.out.write_text(json.dumps(out, indent=1))
