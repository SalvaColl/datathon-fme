"""E-490 — organic product quality for lfm (T-049): validity + exposure replay of single-arm policies. DIAGNOSTICS, not a result:
the hidden model decides, on the leaderboard (team minus reference, same window).

    cd recsys
    python download_user_items.py && python cold_lq_replay.py --pull      # READ-ONLY RawTree
    python organic_quality.py policy.rot_oq1.json [more.json] [--n 3000] [--since "2026-11-14 17:00:00"] [--out file.json]

Every sampled answered request is scored with the catalogue, stock and shopper state AS OF the request, through the writer's
own path (clean_lfm_arms -> set_arms -> LiveFit.slate): once with r3 and once per policy. Organic counts as of the request =
60-day history + today's organic events of the 10-minute buckets already closed (coldlq_replay/item10.parquet).
Output per policy and segment: valid lists, lists changed, slot-1 changed, overlap, latency, and the organic purchase rate
(60-day purchases per view) of the products shown by each side.
"""
from __future__ import annotations
import argparse, collections, json, sys, time
from pathlib import Path
import numpy as np, pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("files", nargs="+"); ap.add_argument("--n", type=int, default=3000)
    ap.add_argument("--since", default="2026-11-14 17:00:00"); ap.add_argument("--out")
    a = ap.parse_args()
    import lfm, lfm_build as LB, cold_lq_replay as R, qrank, cart_variants as CV
    d, LF, aff, carts, buys = CV.setup()
    src = (HERE / "live.py").read_text(); i0 = src.index("def clean_lfm_arms"); i1 = src.index("def lfm_route")
    ns = {"lfm": lfm}; exec(src[i0:i1], ns); clean = ns["clean_lfm_arms"]          # the writer's function, unchanged
    pol = {"r3": [{"tag": "r3", "file": "lfm_coef_r3.json"}]}
    for f in a.files:
        conf = json.loads((HERE / f).read_text()); arms = clean(conf.get("lfm_arms"))
        assert conf.get("variant") == "lfm" and len(arms) == 1 and "lq" not in arms[0], f + ": rejected by clean_lfm_arms or carries lq"
        pol[f] = arms
    hist = pd.read_parquet(LB.DATA / "user_item_all.parquet").groupby("i")[["v", "p"]].sum()
    H = dict(zip(hist.index, zip(hist.v.values.astype(float), hist.p.values.astype(float)))); hset = set(H)
    it = pd.read_parquet(R.OUT / "item10.parquet"); it["b"] = pd.to_datetime(it.b) + pd.Timedelta(minutes=10)     # usable once closed
    it = it.sort_values("b")
    hc = LF.snap.hc
    d = d[(d.ts >= pd.Timestamp(a.since)) & (d.served_by == "team")]; d = d.iloc[::max(1, len(d) // a.n)]
    C = R.Catalogue(); QR = qrank.Ranker.load(HERE / "data" / "qrank.joblib"); shim = R.AffAsOf(aff)
    d = d.assign(ver=[C.version(t) for t in d.ts], bucket=d.ts.dt.floor("10min"))
    ms = collections.defaultdict(list); rows = []
    for (ver, bucket), g in d.groupby(["ver", "bucket"], sort=True, dropna=False):
        cat, unavail, desc = C.asof(None if pd.isna(ver) else ver)
        QR.set_catalog(cat, unavail); newp = set(cat.index) - set(QR.q)
        today = it[it.b <= bucket].groupby("i")[["v", "p"]].sum(); oq = dict(H)
        for i, v, p in zip(today.index, today.v.values, today.p.values):
            h = oq.get(i); oq[i] = (v + h[0], p + h[1]) if h else (float(v), float(p))
        LF.set_catalog(cat, unavail, aff, QR.lq, hc, newp=newp or None, oq=oq, oq_hist=hset)
        S = LF.snap; rate = np.array([(H.get(i, (0, 0))[1] + 1) / (H.get(i, (0, 0))[0] + 20) for i in S.ids])
        for r in g.itertuples():
            shim.ts = r.ts; st = LB.replay_state(LF, aff, carts, buys, r.user_id, r.ts)
            req = dict(user_id=r.user_id, rv=r.rv, page=r.page or "product", is_new_user=bool(r.new_user), device=r.device, region=r.region)
            seg = ("new" if r.new_user else "known") + ("/page" if r.rv else "/home"); out = {}
            for f, arms in pol.items():
                LF.set_arms(arms); t0 = time.perf_counter(); s = LF.slate(req, st, shim, exclude=unavail, model=arms[0]["tag"]); ms[f].append(1000 * (time.perf_counter() - t0))
                ok = s is not None and len(s) == 10 and len(set(s)) == 10 and not (set(s) & unavail) and not (set(s) & st[0]) and all(p in cat.index for p in s)
                out[f] = (s, ok)
            b = out["r3"][0]
            for f in a.files:
                s, ok = out[f]
                rows.append((f, seg, int(ok), int(s != b), int(bool(s) and bool(b) and s[0] != b[0]), len(set(s or ()) & set(b or ())),
                             float(np.mean([rate[S.row[p]] for p in b])) if b else np.nan, float(np.mean([rate[S.row[p]] for p in s])) if s else np.nan,
                             sum(p in newp for p in (b or ())), sum(p in newp for p in (s or ()))))
    T = pd.DataFrame(rows, columns=["policy", "seg", "valid", "changed", "slot1_changed", "overlap", "rate_r3", "rate_arm", "new_r3", "new_arm"])
    g = T.groupby(["policy", "seg"]).agg(requests=("valid", "size"), valid_pct=("valid", lambda x: 100 * x.mean()), lists_changed_pct=("changed", lambda x: 100 * x.mean()),
                                         slot1_changed_pct=("slot1_changed", lambda x: 100 * x.mean()), overlap=("overlap", "mean"),
                                         organic_rate_r3=("rate_r3", lambda x: 100 * x.mean()), organic_rate_arm=("rate_arm", lambda x: 100 * x.mean()),
                                         launched_per_list_r3=("new_r3", "mean"), launched_per_list_arm=("new_arm", "mean")).round(2)
    pd.set_option("display.width", 250); print(g.to_string())
    pct = lambda v, q: round(float(np.percentile(v, q)), 2)
    lat = {f: dict(p50=pct(v, 50), p95=pct(v, 95), p99=pct(v, 99)) for f, v in ms.items()}; print("latency ms", json.dumps(lat))
    if a.out: Path(a.out).write_text(json.dumps(dict(kind="diagnostics: validity and exposure, NOT conversion", since=a.since, requests=int(len(d)),
                                                     policies={f: pol[f] for f in a.files}, segments=g.reset_index().to_dict("records"), latency_ms=lat), indent=1))


if __name__ == "__main__":
    main()
