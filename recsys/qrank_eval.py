"""Check qrank against LIVE data without writing anything (T-014 / E-081). SELECTs only.

    python qrank_eval.py --pull    # download today's feedback, requests, submissions, purchases, catalog
    python qrank_eval.py

For the requests that our writer answered with v1-gbm-cand (product/category pages) it reports:
 A. Does the qrank model predict what really happened with v1's slates? (calibration on live impressions)
 B. Natural experiment: when v1's slot-1 item happens to be qrank's slot-1 item, does the request convert more?
 C. Model-based expected conversion: v1's slates vs qrank's slates on the same requests.
 D. Validity (10 distinct in-stock ids) and time per batch.
"""
import sys, json, time
import numpy as np, pandas as pd
import qrank
from qrank import feature_rows

pd.set_option("display.width", 220)


def pull():
    from rt import q
    T = "team_26"
    fb = pd.concat([q(f"""SELECT f.request_id::String rid, r.ts::String ts, r.user_id::String u, r.context.page::String page,
      toJSONString(arrayMap(x -> x.product_id::String, r.recent_views::Array(Dynamic))) rv, toJSONString(f.shown) shown,
      f.served_by::String sb, f.purchased::String purchased
      FROM {T}.feedback f INNER JOIN shop.requests r ON r.request_id::String = f.request_id::String
      WHERE f.request_id::String != '__init__' AND cityHash64(f.request_id::String) % 4 = {k}""") for k in range(4)])
    fb.to_parquet("data/qe_fb.parquet")
    sm = pd.concat([q(f"SELECT request_id::String rid, model_version::String mv, toJSONString(items) items FROM {T}.submissions WHERE cityHash64(request_id::String) % 4 = {k}") for k in range(4)])
    sm.to_parquet("data/qe_sub.parquet")
    q("SELECT ts::String ts, user_id::String u, product_id::String i FROM shop.events WHERE event_type::String = 'purchase'").to_parquet("data/qe_purch.parquet")
    q("""SELECT product_id::String product_id, argMax(category::String, v) category, argMax(subcategory::String, v) sub, argMax(brand::String, v) brand,
      argMax(price_eur::Float64, v) price, argMax(is_active::Bool, v) active, argMax(chg, v) last_change FROM (
      SELECT product_id, category, subcategory, brand, price_eur, is_active, '' chg, '' v FROM shop.catalog UNION ALL
      SELECT product_id, category, subcategory, brand, price_eur, is_active, change::String, toString(ts) FROM shop.catalog_updates)
      GROUP BY product_id""").to_parquet("data/qe_cat.parquet")
    print("pulled", len(fb), "feedback rows")


def main():
    if "--pull" in sys.argv: pull()
    cat = pd.read_parquet("data/qe_cat.parquet").set_index("product_id")
    unavail = set(cat.index[(~cat.active.astype(bool)) | (cat.last_change == "out_of_stock")])
    R = qrank.Ranker.load(); R.set_catalog(cat, unavail)
    fb = pd.read_parquet("data/qe_fb.parquet"); sm = pd.read_parquet("data/qe_sub.parquet")
    m = fb.merge(sm, on="rid"); m = m[(m.shown == m["items"]) & m.mv.str.startswith("v1-gbm-cand") & ~m.mv.str.endswith("guard") & (m.page != "home")].drop_duplicates("rid")
    m["rv"] = m.rv.map(json.loads); m["shown"] = m.shown.map(json.loads); m["ts"] = pd.to_datetime(m.ts); m["buy"] = (m.purchased != "").astype(int)
    m = m[[len(r) > 0 and r[-1] in R.cat for r in m.rv]]
    pu = pd.read_parquet("data/qe_purch.parquet"); pu["ts"] = pd.to_datetime(pu.ts); byu = {u: g for u, g in pu[pu.u.isin(m.u)].groupby("u")}
    def bought(u, ts):
        g = byu.get(u); return set(g.i[g.ts < ts]) if g is not None else set()
    reqs = [{"rv": r.rv, "page": r.page, "bought": bought(r.u, r.ts)} for r in m.itertuples()]
    print(f"v1-served product/category requests: {len(m)}, purchases {m.buy.sum()}, conversion {100 * m.buy.mean():.2f}%  ({m.ts.min():%H:%M}-{m.ts.max():%H:%M} UTC)")

    # A. calibration of the model on v1's live impressions
    rows = []
    for r, q in zip(m.itertuples(), reqs):
        X = feature_rows(r.shown, r.rv, r.page, 0, R.lq, R.sub, R.brand, R.price); X[:, 0] = np.arange(10)
        p = R._predict(X); same = np.array([R.cat.get(i) == R.cat.get(r.rv[-1]) for i in r.shown]); b = np.array([i in q["bought"] for i in r.shown])
        for k, i in enumerate(r.shown): rows.append((r.rid, k, p[k], same[k], b[k], i == r.purchased, i in r.rv))
    E = pd.DataFrame(rows, columns=["rid", "slot", "p", "same_cat", "bought", "y", "viewed"])
    print("\nA. live impressions of v1, model prediction vs what happened")
    E["group"] = np.where(E.bought, "already bought by user", np.where(~E.same_cat, "other category (no support in history)", np.where(E.viewed, "same category, viewed", "same category, not viewed")))
    print(E.groupby("group").agg(impressions=("y", "size"), purchases=("y", "sum"), predicted=("p", "sum")).round(1).to_string())
    S = E[E.same_cat & ~E.bought]
    print(S.assign(bin=pd.qcut(S.p, [0, .5, .8, .95, 1])).groupby("bin", observed=True).agg(impressions=("y", "size"), purchases=("y", "sum"), predicted=("p", "sum")).round(1).to_string())
    live_factor = S.y.sum() / S.p.sum()
    print(f"live / model ratio on supported impressions: {live_factor:.2f}")

    # conservative re-pricing: separate live/model ratios for viewed and non-viewed impressions
    f_v = E[E.same_cat & ~E.bought & E.viewed].y.sum() / E[E.same_cat & ~E.bought & E.viewed].p.sum()
    f_n = E[E.same_cat & ~E.bought & ~E.viewed].y.sum() / E[E.same_cat & ~E.bought & ~E.viewed].p.sum()
    print(f"live / model ratio: viewed {f_v:.2f}, not viewed {f_n:.2f}")
    def price(slates, factor_view):   # expected conversion of slates with raw model probabilities re-priced by live ratios
        tot = []
        for x, r in zip(slates, m.itertuples()):
            if x is None: tot.append(np.nan); continue
            X = feature_rows(x[0], r.rv, r.page, 0, R.lq, R.sub, R.brand, R.price); X[:, 0] = np.arange(10); p = R._predict(X)
            v = np.array([i in r.rv for i in x[0]]); tot.append((p * np.where(v, factor_view, f_n)).sum())
        return 100 * np.nanmean(tot)
    for vf in (1.0, 0.45):
        R.viewed_factor = vf; alt = []
        for k in range(0, len(reqs), 8): alt += R.slates(reqs[k:k + 8], with_scores=True)
        hl = np.mean([r.rv[-1] in x[0] for x, r in zip(alt, m.itertuples()) if x is not None]); h0 = np.mean([r.rv[-1] == x[0][0] for x, r in zip(alt, m.itertuples()) if x is not None])
        print(f"qrank viewed_factor={vf}: last view in slate {hl:.2f}, in slot 1 {h0:.2f}; conservative expected conversion {price(alt, f_v):.2f}% "
              f"(if viewed ratio were at the low end 0.20: {price(alt, 0.20):.2f}%)")
    # C + D. qrank slates on the same requests (default viewed_factor)
    t = time.time(); out = []
    for k in range(0, len(reqs), 8): out += R.slates(reqs[k:k + 8], with_scores=True)
    dt = (time.time() - t) / (len(reqs) / 8)
    ok = [x is not None and len(set(x[0])) == 10 and not (set(x[0]) & unavail) and not (set(x[0]) & q["bought"]) for x, q in zip(out, reqs)]
    new = np.array([R._predict(np.column_stack([np.arange(10), feature_rows(x[0], r.rv, r.page, 0, R.lq, R.sub, R.brand, R.price)[:, 1:]])).sum() if x is not None else np.nan for x, r in zip(out, m.itertuples())])
    Ev = E.assign(pv=np.where(E.bought, 0, np.where(E.same_cat, E.p, 0))).groupby("rid").pv.sum().reindex(m.rid).values
    print(f"\nC. expected conversion by the model on the same {len(m)} requests: v1 slates {100 * np.nanmean(Ev):.2f}% (actual {100 * m.buy.mean():.2f}%) | qrank slates {100 * np.nanmean(new):.2f}% (raw history model, optimistic; see conservative lines above)")
    print(f"D. valid slates {np.mean(ok):.4f} of {len(ok)}; {1000 * dt:.0f} ms per batch of 8 requests")

    # B. natural experiment: agreement between v1 and qrank
    m = m.assign(same_top=[x is not None and x[0][0] == s[0] for x, s in zip(out, m.shown)], overlap=[len(set(x[0]) & set(s)) if x is not None else 0 for x, s in zip(out, m.shown)])
    print("\nB. actual conversion of v1 requests, by how much v1's slate agrees with qrank's")
    print(m.groupby("same_top").buy.agg(requests="size", purchases="sum", conversion="mean").round(4).to_string())
    print(m.assign(overlap=pd.cut(m.overlap, [-1, 1, 3, 5, 10])).groupby("overlap", observed=True).buy.agg(requests="size", purchases="sum", conversion="mean").round(4).to_string())
    top = pd.DataFrame({"q_top": [x[0][0] if x is not None else None for x in out], "purchased": m.purchased.values, "shown": m.shown.values})
    top["q_top_shown_by_v1"] = [a in s for a, s in zip(top.q_top, top["shown"])]
    g = top[top.q_top_shown_by_v1]
    print(f"qrank's slot-1 item was somewhere in v1's slate in {len(g)} requests; it was the purchased item in {(g.q_top == g.purchased).sum()} "
          f"({100 * (g.q_top == g.purchased).mean():.2f}% per impression, any slot; v1 average per impression {100 * E.y.mean():.3f}%)")


if __name__ == "__main__":
    main()
