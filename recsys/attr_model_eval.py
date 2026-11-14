"""Check attr_model against LIVE feedback (hidden buying model) without writing anything (T-017 / E-172). SELECTs only.

    python attr_model_eval.py --pull    # today's feedback + requests, organic purchases, catalogue, new-product descriptions
    python attr_model_eval.py

Every impression that was really shown today on product/category pages (by our writer or by the organizers'
fallback) is scored with attr_model as a COLD model: quality from history + attributes only, no live counts, so
the 100 products launched today are scored from their attributes alone and every shopper from `recent_views` alone.
 A. Calibration and ranking power on live impressions, against qrank's score on the same impressions.
 B. The slices that matter for the final: products launched today, first-time shoppers.
 C. What the phrase features say live (shared phrases with the last view, session phrase share).
 D. Slates: validity, overlap with qrank, model-based expected conversion, time per request.
"""
import sys, json, time
import numpy as np, pandas as pd
from sklearn.metrics import roc_auc_score
import attr_model as am, qrank, cold_items

pd.set_option("display.width", 220)
SLOT = np.array([1, .53, .40, .30, .24, .21, .18, .16, .13, .13])   # slot curve of non-viewed items (I-083)


def pull():
    from rt import q
    T = "team_26"
    fb = pd.concat([q(f"""SELECT f.request_id::String rid, r.ts::String ts, r.user_id::String u, r.is_new_user::Bool nu, r.context.page::String page,
      toJSONString(arrayMap(x -> x.product_id::String, r.recent_views::Array(Dynamic))) rv, toJSONString(f.shown) shown,
      f.served_by::String sb, f.purchased::String purchased, f.clicked::String clicked
      FROM {T}.feedback f INNER JOIN shop.requests r ON r.request_id::String = f.request_id::String
      WHERE f.request_id::String != '__init__' AND cityHash64(f.request_id::String) % 4 = {k}""") for k in range(4)])
    fb.to_parquet("data/ae_fb.parquet")
    q("SELECT ts::String ts, user_id::String u, product_id::String i FROM shop.events WHERE event_type::String = 'purchase'").to_parquet("data/ae_purch.parquet")
    q("""SELECT product_id::String product_id, argMax(category::String, v) category, argMax(subcategory::String, v) sub, argMax(brand::String, v) brand,
      argMax(price_eur::Float64, v) price, argMax(created_at::String, v) created, argMax(description::String, v) description,
      argMax(is_active::Bool, v) active, argMax(chg, v) last_change FROM (
      SELECT product_id, category, subcategory, brand, price_eur, created_at, description, is_active, '' chg, '' v FROM shop.catalog UNION ALL
      SELECT product_id, category, subcategory, brand, price_eur, created_at, description, is_active, change::String, toString(ts) FROM shop.catalog_updates)
      GROUP BY product_id""").to_parquet("data/ae_cat.parquet")
    q("""SELECT product_id::String i, toUInt32(countIf(event_type::String='view')) it_v, toUInt32(countIf(event_type::String='purchase')) it_p
      FROM shop.events GROUP BY i""").to_parquet("data/ae_live_item.parquet")
    print("pulled", len(fb), "feedback rows")


def table(t, by, name):
    g = t.groupby(by, observed=True).agg(impressions=("y", "size"), purchases=("y", "sum"), predicted=("p", "sum"), clicks=("c", "sum"))
    g["per_10k"] = (1e4 * g.purchases / g.impressions).round(1); g["pred_per_10k"] = (1e4 * g.predicted / g.impressions).round(1)
    g["clicks_per_10k"] = (1e4 * g.clicks / g.impressions).round(1)
    print(f"\n{name}\n" + g.drop(columns="predicted").to_string())


def main():
    if "--pull" in sys.argv: pull()
    cat = pd.read_parquet("data/ae_cat.parquet").set_index("product_id")
    unavail = set(cat.index[(~cat.active.astype(bool)) | (cat.last_change == "out_of_stock")])
    R = am.Ranker.load()
    new_ids = [p for p in cat.index if p not in R.base_attrs]
    new_attrs = {p: cold_items.attrs(cat.at[p, "description"]) for p in new_ids}
    R.set_catalog(cat, unavail, live_item=None, attrs=new_attrs)        # COLD: no live counts
    I = R.index
    Q = qrank.Ranker.load(); Q.set_catalog(cat, unavail)
    fb = pd.read_parquet("data/ae_fb.parquet").drop_duplicates("rid")
    fb = fb[fb.page != "home"].copy()
    fb["rv"] = fb.rv.map(json.loads); fb["shown"] = fb.shown.map(json.loads); fb["ts"] = pd.to_datetime(fb.ts)
    fb = fb[[len(r) > 0 and r[-1] in I.ix and all(i in I.ix for i in s) and len(s) == 10 for r, s in zip(fb.rv, fb.shown)]]
    pu = pd.read_parquet("data/ae_purch.parquet"); pu["ts"] = pd.to_datetime(pu.ts); byu = {u: g for u, g in pu[pu.u.isin(fb.u)].groupby("u")}
    def bought(u, ts):
        g = byu.get(u); return set(g.i[g.ts < ts]) if g is not None else set()
    print(f"live product/category requests with feedback: {len(fb)} ({fb.ts.min():%H:%M}-{fb.ts.max():%H:%M} UTC), purchases {(fb.purchased != '').sum()}, "
          f"served by team {(fb.sb == 'team').sum()}, by fallback {(fb.sb != 'team').sum()}; products launched today: {len(new_ids)}")
    newset = set(new_ids); rows = []; X = []; Xq = []
    for r in fb.itertuples():
        rv = [I.ix[x] for x in r.rv if x in I.ix]; items = np.array([I.ix[i] for i in r.shown])
        f = I.features(items, rv, r.page, 0); f[:, 0] = np.arange(10); X.append(f)
        g = qrank.feature_rows(r.shown, [x for x in r.rv if x in Q.cat], r.page, 0, Q.lq, Q.sub, Q.brand, Q.price); g[:, 0] = np.arange(10); Xq.append(g)
        b = bought(r.u, r.ts); lc = I.catname[rv[-1]]
        for k, i in enumerate(r.shown):
            rows.append((r.rid, k, i == r.purchased, i == r.clicked, i in newset, r.nu, I.catname[items[k]] == lc, i in b, r.sb))
    X = np.vstack(X); Xq = np.vstack(Xq)
    t = pd.DataFrame(rows, columns=["rid", "slot", "y", "c", "new_item", "new_user", "same_cat", "bought", "sb"])
    t["p"] = R._predict(X); t["pq"] = Q._predict(Xq, calibrated=True)
    t["viewed"] = (X[:, 2] + X[:, 3]) > 0; t["shl"] = X[:, 11].astype(int); t["aff"] = X[:, 12]

    table(t, ["same_cat", "bought", "viewed"], "0. where live purchases come from (same category as last view / already bought / viewed in session)")
    s = t[t.same_cat & ~t.bought].copy()            # the impressions attr_model would be allowed to show
    print(f"\nA. eligible impressions (same category, not bought): {len(s)}, purchases {int(s.y.sum())}, clicks {int(s.c.sum())}")
    for name, col in (("attr_model (cold)", "p"), ("qrank", "pq")):
        print(f"   {name:18s} AUC purchase {roc_auc_score(s.y, s[col]):.3f}  AUC click {roc_auc_score(s.c, s[col]):.3f}  predicted/observed purchases {s[col].sum() / s.y.sum():.2f}"
              f"  | non-viewed only: AUC purchase {roc_auc_score(s.y[~s.viewed], s[col][~s.viewed]):.3f} click {roc_auc_score(s.c[~s.viewed], s[col][~s.viewed]):.3f}")
    s["bin"] = pd.qcut(s.p, [0, .5, .8, .95, .99, 1]); table(s, "bin", "A. calibration by attr_model score (eligible impressions)")
    s["binq"] = pd.qcut(s.pq, [0, .5, .8, .95, .99, 1]); table(s.assign(p=s.pq), "binq", "A. same for qrank's score")
    table(s[~s.viewed], "new_item", "B. products launched today (non-viewed impressions): scored from attributes only")
    n = s[s.new_item & ~s.viewed]
    if n.y.sum() + n.c.sum() >= 5: print(f"   within launched products: AUC click {roc_auc_score(n.c, n.p):.3f} (n={len(n)}, clicks {int(n.c.sum())}, purchases {int(n.y.sum())})")
    table(s, "new_user", "B. first-time shoppers vs known (eligible impressions)")
    for nu in (True, False):
        z = s[s.new_user == nu]; print(f"   new_user={nu}: AUC purchase attr_model {roc_auc_score(z.y, z.p):.3f} qrank {roc_auc_score(z.y, z.pq):.3f} | click {roc_auc_score(z.c, z.p):.3f} vs {roc_auc_score(z.c, z.pq):.3f}")
    table(s[~s.viewed], "shl", "C. non-viewed: phrases shared with the last viewed product")
    s["affb"] = pd.cut(s.aff, [-1, 0.001, 0.15, 0.3, 0.5, 1.01]); table(s[~s.viewed], "affb", "C. non-viewed: share of the session's phrases on this product")

    # E. within one request: does the scorer put the bought / clicked item above the other eligible items shown with it?
    cols = {"attr_model": s.p, "qrank": s.pq}
    try:
        import attr_affinity
        AFF = attr_affinity.AttrAffinity(cold_items.ColdStart(), ui_path="data/user_item_all.parquet")
        fbi = fb.set_index("rid"); au = np.empty(len(t)); ah = np.empty(len(t)); mass = np.empty(len(t)); rid_ = t.rid.values
        for k in range(0, len(t), 10):
            r = fbi.loc[rid_[k]]
            au[k:k + 10] = AFF.affinity(r.u, r.shown, r.rv); ah[k:k + 10] = AFF.affinity(r.u, r.shown, ()); mass[k:k + 10] = AFF.user_vec(r.u).sum()
        t["aff_u"], t["aff_h"], t["mass"] = au, ah, mass; s = s.join(t[["aff_u", "aff_h", "mass"]])
        cap = lambda a: np.minimum(a, am.CAP)
        cols.update({f"attr_model x exp({am.BETA_HIST:.0f}*stored taste)  [attr_aff]": s.p * np.exp(am.BETA_HIST * cap(s.aff_h)),
                     "attr_model x exp(40*taste incl. recent_views)": s.p * np.exp(40 * cap(s.aff_u)),
                     "qrank x exp(40*taste incl. recent_views)  [qrank_aff]": s.pq * np.exp(40 * cap(s.aff_u)),
                     "qrank x exp(20*taste incl. recent_views)": s.pq * np.exp(20 * cap(s.aff_u))})
    except Exception as e:
        print("\n(E without history affinity:", type(e).__name__, e, ")"); s["mass"] = 0.0

    def within(d, col, sc):
        d = d.assign(sc=sc.loc[d.index]); d = d[d.groupby("rid")[col].transform("max") > 0]
        d["share"] = d.sc / d.groupby("rid").sc.transform("sum"); d["rk"] = d.groupby("rid").sc.rank(ascending=False)
        w = d[d[col]]; return len(w), np.log(w.share).mean(), (w.rk == 1).mean()
    print("\nE. within-request ranking of what was shown (log-likelihood of the chosen item: higher is better; hit@1)")
    for nm, d in (("all shoppers", s), ("shoppers with stored history", s[s.mass > 0]), ("shoppers WITHOUT history (the final's case)", s[s.mass == 0])):
        print(f"  {nm}")
        for k, sc in cols.items():
            a, b = within(d, "y", sc), within(d, "c", sc)
            print(f"    {k:56s} purchases N={a[0]:3d} loglik {a[1]:.3f} hit@1 {a[2]:.3f} | clicks N={b[0]:3d} loglik {b[1]:.3f} hit@1 {b[2]:.3f}")

    # D. slates on the same requests
    reqs = [{"rv": r.rv, "page": r.page, "bought": bought(r.u, r.ts) | unavail} for r in fb.itertuples()]
    sub = list(range(0, len(reqs), max(1, len(reqs) // 3000)))
    t0 = time.perf_counter(); res = []
    for k in range(0, len(sub), 4): res += R.slates([reqs[j] for j in sub[k:k + 4]], with_scores=True)
    dt = (time.perf_counter() - t0) / (len(sub) / 4)
    lat = []
    for k in range(0, 400, 4):
        t1 = time.perf_counter(); R.slates([reqs[j] for j in sub[k:k + 4]]); lat.append(time.perf_counter() - t1)
    resq = Q.slates([reqs[j] for j in sub], with_scores=True)
    ok = [x for x in res if x is not None]
    valid = np.mean([len(set(x[0])) == 10 and not (set(x[0]) & unavail) for x in ok])
    both = [(a, b, j) for a, b, j in zip(res, resq, sub) if a is not None and b is not None]
    # judge both policies with the SAME scorer (attr_model, slot-aware) to compare like with like; optimistic for its own slates
    def judge(slate, j):
        r = fb.iloc[j]; rv = [I.ix[x] for x in r.rv if x in I.ix]
        f = I.features(np.array([I.ix[i] for i in slate]), rv, r.page, 0); f[:, 0] = np.arange(10); return float(R._predict(f).sum())
    ja = np.mean([sum(a[1]) for a, b, j in both]); jq = np.mean([judge(b[0], j) for a, b, j in both])
    new_per = np.mean([len(set(a[0]) & newset) for a, b, j in both]); new_q = np.mean([len(set(b[0]) & newset) for a, b, j in both])
    print(f"\nD. slates for {len(sub)} requests: answered {len(ok)}, valid {valid:.3f}; batch of 4 requests: mean {1000 * dt:.0f} ms, p95 {1000 * np.percentile(lat, 95):.0f} ms")
    print(f"   overlap with qrank's slate {np.mean([len(set(a[0]) & set(b[0])) for a, b, j in both]):.1f}/10, same slot-1 {np.mean([a[0][0] == b[0][0] for a, b, j in both]):.2f}; "
          f"last viewed product in slate {np.mean([fb.iloc[j].rv[-1] in a[0] for a, b, j in both]):.2f}; products launched today per slate: attr_model {new_per:.2f}, qrank {new_q:.2f}")
    k = s.y.sum() / s.p.sum()      # live recalibration of the history-trained probabilities on eligible impressions
    print(f"   expected purchases per 100 requests by attr_model's own scorer x live calibration {k:.2f} (MODEL-BASED, optimistic for its own slates, not a leaderboard number): qrank slates {100 * k * jq:.2f} | attr_model slates {100 * k * ja:.2f}")
    print(f"   actual purchases per 100 of these requests: {100 * (fb.purchased != '').mean():.2f}")


if __name__ == "__main__":
    main()
