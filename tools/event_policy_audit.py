"""Read-only event-policy audit on an independently cached snapshot; never starts a writer.

python tools/event_policy_audit.py prepare
python tools/event_policy_audit.py promotions
python tools/event_policy_audit.py shadow --n 1500

Input cache: data/local_eval/trends_promotions/{cases,cat,catlog,ev,views,fb,minute,item10,
hist_users,hist_items}.parquet and manifest.json. Cases are outcome-enriched: composition is
diagnostic, not traffic prevalence or conversion. Unified weights used same-day data: this
is retrospective screening, not untouched policy validation. Organic counts lag by up to
ten minutes; trend counts have one-minute resolution. No unexposed-item negatives are used.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "recsys"))
import attr_affinity, cold_items, home_cands, lfm, lfm_build as LB, qrank, trends

CACHE = ROOT / "data" / "local_eval" / "trends_promotions"


def pull(cache, start, asof):
    """SELECT-only acquisition; refuse to overwrite a complete snapshot. No secrets in the cache or logs."""
    from tools.feedback_monitor import sql, TEAM
    start = pd.Timestamp(start); end = pd.Timestamp(asof)
    if start.tzinfo: start = start.tz_convert("UTC").tz_localize(None)
    if end.tzinfo: end = end.tz_convert("UTC").tz_localize(None)
    if end != end.floor("10min") or start >= end:
        raise ValueError("asof must be a completed UTC ten-minute boundary after start")
    if end > pd.Timestamp.now("UTC").tz_localize(None) - pd.Timedelta(minutes=2):
        raise ValueError("Leave at least two minutes for delayed events")
    if (cache / "manifest.json").exists(): raise FileExistsError("Use a new --cache for a different snapshot")
    a, b = str(start), str(end)
    query = f"""SELECT r.request_id::String request_id,r.is_new_user::Bool new_user,r.user_id::String user_id,
      r.ts::String ts,r.context.page::String page,r.context.device::String device,r.context.region::String region,
      toJSONString(r.recent_views) rv,toJSONString(f.shown) shown,f.purchased::String purchased,f.clicked::String clicked
      FROM {TEAM}.feedback f INNER JOIN shop.requests r ON r.request_id::String=f.request_id::String
      WHERE r.ts::DateTime64(3)>='{a}' AND r.ts::DateTime64(3)<'{b}' AND f.served_by::String='team'
      AND r.context.page::String IN ('product','category') AND (f.clicked::String!='' OR f.purchased::String!='')"""
    cases = sql(query)
    if not cases: raise ValueError("No feedback cases in requested period")
    users = sorted({r["user_id"] for r in cases}); ids = ",".join("'" + u.replace("'", "''") + "'" for u in users)
    cat = f"""SELECT product_id::String product_id,argMax(category::String,t) category,
      argMax(subcategory::String,t) sub,argMax(brand::String,t) brand,argMax(price_eur::Float64,t) price,
      argMax(description::String,t) description,uniqExact(subcategory::String) nsub FROM
      (SELECT product_id,category,subcategory,brand,price_eur,description,'' t FROM shop.catalog UNION ALL
       SELECT product_id,category,subcategory,brand,price_eur,description,toString(ts) t FROM shop.catalog_updates
       WHERE ts::DateTime64(3)<'{b}') GROUP BY product_id"""
    queries = {
        "cat": cat,
        "catlog": f"SELECT product_id::String product_id,'' ts,price_eur::Float64 price,is_active::Bool active,'base' change FROM shop.catalog UNION ALL SELECT product_id::String product_id,ts::String ts,price_eur::Float64 price,is_active::Bool active,change::String change FROM shop.catalog_updates WHERE ts::DateTime64(3)<'{b}'",
        "ev": f"SELECT user_id::String u,product_id::String i,event_type::String e,min(ts::DateTime64(3))::String t0 FROM shop.events WHERE user_id::String IN ({ids}) AND event_type::String IN ('add_to_cart','purchase') AND ts::DateTime64(3)<'{b}' GROUP BY u,i,e",
        "views": f"SELECT user_id::String u,product_id::String i,toStartOfInterval(ts::DateTime64(3),INTERVAL 10 MINUTE)::String t,count() n FROM shop.events WHERE user_id::String IN ({ids}) AND event_type::String='view' AND ts::DateTime64(3)<'{b}' GROUP BY u,i,t",
        "fb": f"SELECT r.user_id::String u,f.purchased::String i,min(f.ts::DateTime64(3))::String t FROM {TEAM}.feedback f INNER JOIN shop.requests r ON r.request_id::String=f.request_id::String WHERE r.user_id::String IN ({ids}) AND f.purchased::String!='' AND f.ts::DateTime64(3)<'{b}' GROUP BY u,i",
        "item10": f"SELECT product_id::String i,toStartOfInterval(ts::DateTime64(3),INTERVAL 10 MINUTE)::String b,countIf(event_type::String='view') v,countIf(event_type::String='purchase') p FROM shop.events WHERE ts::DateTime64(3)<'{b}' GROUP BY i,b",
        "minute": f"SELECT toStartOfMinute(e.ts::DateTime64(3))::String t,c.sub sub,countIf(e.event_type::String='view') v,countIf(e.event_type::String='purchase') p FROM shop.events e INNER JOIN ({cat}) c ON c.product_id=e.product_id::String WHERE e.ts::DateTime64(3)>='{start-pd.Timedelta(minutes=195)}' AND e.ts::DateTime64(3)<'{b}' GROUP BY t,sub"}
    with ThreadPoolExecutor(max_workers=3) as pool:
        names = list(queries); raw = dict(zip(names, pool.map(sql, [queries[k] for k in names])))
    if any(int(r["nsub"]) > 1 for r in raw["cat"]):
        raise ValueError("Subcategories changed: reconstruct event metadata as of each event before using this audit")
    if pd.to_datetime(pd.DataFrame(raw["minute"]).t).max() < end - pd.Timedelta(minutes=2):
        raise ValueError("Organic timestamp coverage does not reach requested cutoff")
    cache.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(cases).to_parquet(cache / "cases.parquet")
    for name, rows in raw.items(): pd.DataFrame(rows).to_parquet(cache / (name + ".parquet"))
    history = ROOT / "recsys/data/user_item_all.parquet"
    pd.read_parquet(history, filters=[("u", "in", users)]).to_parquet(cache / "hist_users.parquet")
    pd.read_parquet(history, columns=["i", "v", "p"]).groupby("i")[["v", "p"]].sum().to_parquet(cache / "hist_items.parquet")
    fingerprint = {}
    for name in ("policy.unified.json", "lfm_coef_r3.json", "cold_prior.json", "lfm_mf.npz", "data/qrank.joblib"):
        p = ROOT / "recsys" / name
        fingerprint[name] = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
    manifest = dict(asof_utc=b, start_utc=a, source_artifacts=fingerprint,
                    limitations="Outcome-enriched retrospective sample; unified weights selected on same-day data; not conversion")
    (cache / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(dict(cases=len(cases), cache=str(cache), asof_utc=b)))


def detectors(minute):
    """Same subcategory flags as production compute(), from completed minute buckets only."""
    d = minute.copy(); d["t"] = pd.to_datetime(d.t)
    names = sorted(d["sub"].unique()); origin = d.t.min()
    grid = pd.date_range(origin, d.t.max(), freq="min")
    v = d.pivot_table(index="t", columns="sub", values="v", aggfunc="sum", fill_value=0).reindex(
        index=grid, columns=names, fill_value=0).to_numpy(float)
    memo = {}

    def at(ts):
        cut = int((pd.Timestamp(ts).floor("min") - origin).total_seconds() / 60)
        if cut <= 0 or cut > len(v): return {15: set(), 5: set()}
        if cut not in memo:
            data = v[max(0, cut - 195):cut]
            rr, cc = np.nonzero(data)
            frame = pd.DataFrame({"age": (len(data) - 1 - rr) // 5,
                                  "i": [names[k] for k in cc], "v": data[rr, cc]})
            mapping = {s: s for s in names}
            memo[cut] = {w: set(trends.compute(frame, mapping, recent=w // 5).hot) for w in (15, 5)}
        return memo[cut]
    return at


def load(cache, limit=None):
    manifest = json.loads((cache / "manifest.json").read_text())
    for name, expected in manifest.get("source_artifacts", {}).items():
        p = ROOT / "recsys" / name
        if (hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None) != expected:
            raise ValueError("Source artifact changed: " + name)
    get = lambda name: pd.read_parquet(cache / (name + ".parquet"))
    cat = get("cat").set_index("product_id"); hist = get("hist_users")
    cold = cold_items.ColdStart()
    for p, desc in cat.description.items():
        if p not in cold.attr: cold.attr[p] = cold_items.attrs(desc)
    aff = attr_affinity.AttrAffinity(cold, ui_path=None)
    h = hist[(hist.v > 0) & hist.i.isin(aff.pid)]
    codes, users = pd.factorize(h.u); aff.UV = np.zeros((len(users), 20), dtype=np.float32)
    aff.uix = {u: k for k, u in enumerate(users)}
    np.add.at(aff.UV, codes, aff.A[h.i.map(aff.pid).values] * h.v.values[:, None].astype(np.float32))
    qr = qrank.Ranker.load(ROOT / "recsys/data/qrank.joblib"); qr.set_catalog(cat)
    coef = json.loads((ROOT / "recsys/lfm_coef_r3.json").read_text())
    lf = lfm.LiveFit(coef, hist)
    lf.set_catalog(cat, set(), aff, qr.lq, home_cands.HomeCands(hist, cat))
    policy = json.loads((ROOT / "recsys/policy.unified.json").read_text())
    spec = policy["lfm_arms"][0]
    import copy
    fast = copy.deepcopy(spec); fast.update(tag="b7", trend_window=5)
    lf.set_arms([spec, fast])
    carts, buys = {}, {}
    for r in get("ev").itertuples():
        (carts if r.e == "add_to_cart" else buys).setdefault(r.u, {})[r.i] = np.datetime64(r.t0)
    aff.fbuys = {}
    for r in get("fb").itertuples(): aff.fbuys.setdefault(r.u, {})[r.i] = np.datetime64(r.t) + LB.FB_LAG
    aff.today = {}
    for r in get("views").itertuples():
        if r.i in aff.pid:
            aff.today.setdefault(r.u, []).append((np.datetime64(r.t) + np.timedelta64(10, "m"), aff.pid[r.i], int(r.n)))
    log = get("catlog"); clock = LB.CatLog(log, lf.snap)
    # New items use their launch price, never a later maximum or future restoration price.
    reference = clock.price0.copy()
    for t, k, price, active, change in clock.ev:
        if change == "new_product" and not np.isfinite(reference[k]): reference[k] = price
    base = get("hist_items"); oq = {i: [float(r.v), float(r.p)] for i, r in base.iterrows()}
    items = get("item10"); items["end"] = pd.to_datetime(items.b) + pd.Timedelta(minutes=10)
    items = list(items.sort_values("end").itertuples()); cursor = 0; bucket = None
    signal = detectors(get("minute")); cases = get("cases").sort_values("ts")
    if limit: cases = cases.iloc[::max(1, len(cases) // limit)]
    for r in cases.itertuples():
        ts = pd.Timestamp(r.ts); rv = [x["product_id"] for x in json.loads(r.rv)]
        if bucket != ts.floor("10min"):
            while cursor < len(items) and items[cursor].end <= ts.floor("10min"):
                e = items[cursor]; old = oq.setdefault(e.i, [0., 0.]); old[0] += e.v; old[1] += e.p; cursor += 1
            lf.snap.orate, lf.snap.opop = lfm.organic_quality(lf.snap.ids, oq, set(base.index))
            bucket = ts.floor("10min")
        s = lf.snap; exists, unav, price = clock.at(ts)
        s.ok = exists & ~unav & cat.category.reindex(s.ids).notna().values
        s.p40 = (price > 40).astype(float); s.cheap = (price < 20).astype(float)
        hot = signal(ts)
        for window, field in ((15, "hot"), (5, "hot_fast")):
            mask = cat["sub"].reindex(s.ids).isin(hot[window]).to_numpy() & exists
            if mask.sum() > .1 * max(1, exists.sum()): mask[:] = False
            mask = mask.astype(float); mask.flags.writeable = False; setattr(s, field, mask)
        s.hot_expires_at = time.monotonic() + lfm.HOT_TTL_S
        state = LB.replay_state(lf, aff, carts, buys, r.user_id, ts)
        req = dict(user_id=r.user_id, rv=rv, page=r.page, device=r.device, region=r.region, is_new_user=bool(r.new_user))
        yield r, req, state, lf, aff, ts, reference, price


class AsOf:
    def __init__(self, aff, ts): self.aff, self.ts = aff, ts
    def affinity_all(self, u, rv): return LB.aff_asof(self.aff, u, rv, self.ts)


def promotion_depth(price, reference):
    """20% off = 1; neutral for increases/missing/bad metadata. References must be available as of the request."""
    valid = np.isfinite(price) & np.isfinite(reference) & (price > 0) & (reference > 0)
    out = np.zeros(len(price))
    out[valid] = np.clip(np.log(reference[valid] / price[valid]), 0, np.log(2)) / np.log(1.25)
    return out


def prepare(cache):
    features, scores, labels, weights, meta = [], [], [], [], []
    for k, (row, req, state, lf, aff, ts, reference, price) in enumerate(load(cache)):
        shown = json.loads(row.shown); target = row.purchased or row.clicked
        if target not in shown: continue
        s, score = lf.scores(req, state, AsOf(aff, ts), model="u1")
        idx = np.array([s.row.get(p, -1) for p in shown]); y = shown.index(target)
        if min(idx) < 0 or not np.isfinite(score[idx[y]]): continue
        pr, ref = price[idx], reference[idx]
        discount = promotion_depth(pr, ref)
        last = s.row.get(req["rv"][-1]) if req["rv"] else None
        context = (s.cat[idx] == s.cat[last]) if last is not None else np.zeros(10)
        features.append(np.column_stack([discount, discount * context]))
        scores.append(score[idx]); labels.append(y); weights.append(3.0 if row.purchased else 1.0)
        meta.append(dict(u=row.user_id, ts=str(ts), new=bool(row.new_user), buy=bool(row.purchased),
                         page=row.page, discounted_items=int((discount > .05).sum()), target_discounted=bool(discount[y] > .05)))
        if k % 1000 == 0: print("prepare_progress", k, flush=True)
    np.savez_compressed(cache / "promo_features.npz", features=np.array(features), scores=np.array(scores),
                        y=np.array(labels), weights=np.array(weights))
    pd.DataFrame(meta).to_parquet(cache / "promo_meta.parquet")
    (cache / "prepared_policy.json").write_text(json.dumps(json.loads((ROOT / "recsys/policy.unified.json").read_text()), sort_keys=True))
    print(json.dumps(dict(prepared_cases=len(meta), purchases=sum(x["buy"] for x in meta))))


def promotions(cache):
    from scipy.optimize import minimize
    from scipy.special import logsumexp
    data = np.load(cache / "promo_features.npz"); m = pd.read_parquet(cache / "promo_meta.parquet")
    x, score, y, weight = [data[k] for k in ("features", "scores", "y", "weights")]
    if (cache / "prepared_policy.json").read_text() != json.dumps(json.loads((ROOT / "recsys/policy.unified.json").read_text()), sort_keys=True):
        raise ValueError("Policy changed: prepare again before comparing")
    # Hard exclusions contribute zero probability; finite floor avoids 0 * -inf in the optimizer.
    score = np.where(np.isfinite(score), score, -100.)
    slot = np.broadcast_to(np.log(np.arange(1, 11)), score.shape)
    rng = np.random.default_rng(540)
    for new in (False, True):
        cohort = (m.new == new).values & m.page.isin(["product", "category"]).values
        tr = cohort & (m.ts < "2026-11-14 20:00:00").values
        z = np.stack([score, slot], axis=-1)
        def fit(z, offset, start, penalty, bounds=None):
            a, b, target, sw = z[tr], offset[tr], y[tr], weight[tr]
            def loss(th):
                v = b + a @ th; normal = logsumexp(v, axis=1)
                p = np.exp(v - normal[:, None]); p[np.arange(len(p)), target] -= 1
                return (sw * (normal - v[np.arange(len(v)), target])).sum() + .5 * penalty * (th @ th), \
                       np.einsum("nij,ni,n->j", a, p, sw) + penalty * th
            result = minimize(loss, start, jac=True, method="L-BFGS-B", bounds=bounds)
            if not result.success: raise RuntimeError("Conditional fit failed: " + str(result.message))
            return result.x
        cal = fit(z, np.zeros_like(score), np.array([1., -.5]), .1, [(0.05, 5.), (-3., 0.)])
        offset = z @ cal
        baseline = offset[np.arange(len(y)), y] - logsumexp(offset, axis=1)
        for col, name in enumerate(("discount", "discount_context")):
            th = fit(x[:, :, col:col + 1], offset, np.zeros(1), 1.)
            v = offset + x[:, :, col] * th[0]
            ll = v[np.arange(len(y)), y] - logsumexp(v, axis=1)
            for lo, hi in (("20:00", "22:00"), ("22:00", "24:40")):
                end = "2026-11-15 00:40" if hi == "24:40" else "2026-11-14 " + hi
                mask = cohort & (m.ts >= "2026-11-14 " + lo).values & (m.ts < end).values & m.buy.values
                g = pd.DataFrame({"u": m.u[mask], "d": ll[mask] - baseline[mask]}).groupby("u").agg(total=("d", "sum"), n=("d", "size"))
                if not len(g): continue
                jj = rng.integers(0, len(g), size=(2000, len(g)))
                boot = g.total.values[jj].sum(1)
                print(json.dumps(dict(segment="new" if new else "known", candidate=name, trained_weight=round(float(th[0]), 4),
                    period=lo + "-" + hi, purchases=int(mask.sum()), discount_target_cases=int(m.target_discounted[mask].sum()),
                    purchase_choice_ll_delta=round(float(g.total.sum()), 4), user_bootstrap95=np.quantile(boot, [.025, .975]).round(4).tolist())))


def shadow(cache, n):
    from collections import Counter
    counts = defaultdict(Counter); latency = defaultdict(list)
    for k, (row, req, state, lf, aff, ts, reference, price) in enumerate(load(cache, n)):
        out = {}
        for tag in ("u1", "b7"):
            t = time.perf_counter(); out[tag] = lf.slate(req, state, AsOf(aff, ts), model=tag)
            latency[tag].append(1000 * (time.perf_counter() - t))
        s = lf.snap
        different = not np.array_equal(s.hot, s.hot_fast)
        cohort = ("new" if req["is_new_user"] else "known") + ("/page" if req["rv"] else "/home")
        for key in ("all", cohort, "different_masks" if different else "same_masks"):
            c = counts[key]; c["n"] += 1; c["changed"] += out["u1"] != out["b7"]
            for tag in out:
                slate = out[tag]
                c["valid_" + tag] += slate is not None and len(slate) == len(set(slate)) == 10 and all(
                    s.ok[s.row[p]] and p not in state[0] for p in slate)
        if k % 1000 == 0: print("shadow_progress", k, flush=True)
    print(json.dumps({key: dict(n=c["n"], changed_pct=round(100 * c["changed"] / c["n"], 3),
          valid_pct={tag: round(100 * c["valid_" + tag] / c["n"], 3) for tag in ("u1", "b7")}) for key, c in counts.items()}))
    print(json.dumps({tag: dict(p95=round(float(np.quantile(t, .95)), 3), p99=round(float(np.quantile(t, .99)), 3)) for tag, t in latency.items()}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("pull", "prepare", "promotions", "shadow"))
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--n", type=int, default=1500)
    parser.add_argument("--start", default="2026-11-14 12:00:00", help="UTC")
    parser.add_argument("--asof", help="UTC ten-minute boundary; required by pull")
    args = parser.parse_args()
    if args.n < 1: parser.error("n must be positive")
    if args.command == "pull":
        if not args.asof: parser.error("pull requires --asof")
        pull(args.cache, args.start, args.asof)
    elif args.command == "shadow": shadow(args.cache, args.n)
    else: globals()[args.command](args.cache)
