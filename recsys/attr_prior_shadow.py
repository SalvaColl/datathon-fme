"""E-620 — shadow of the attribute prior inside `orate` (T-062). DIAGNOSTICS: validity and exposure, NOT conversion.

    cd recsys
    python download_user_items.py && python cold_lq_replay.py --pull      # READ-ONLY RawTree
    python attr_prior_shadow.py policy.rot_ug1.json [--n 3000] [--since "2026-11-15 02:00:00"] [--out file.json]

The policy file must hold a control arm and a challenger that differs only by the key `oqa`. Every sampled answered
request is scored with the catalogue, stock, shopper state and organic counts AS OF the request (unified_eval.snapshots)
through the writer's own path (clean_lfm_arms -> set_arms -> LiveFit.slate), once per arm. The prior of each product
comes from live.attr_prior's own code, with the catalogue and descriptions as of the request.
"""
from __future__ import annotations
import argparse, collections, json, sys, time, types
from pathlib import Path
import numpy as np, pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("file"); ap.add_argument("--n", type=int, default=3000)
    ap.add_argument("--since", default="2026-11-15 02:00:00"); ap.add_argument("--out")
    a = ap.parse_args()
    import unified_eval as U, live, cold_items
    lfm, LB, R, qrank, CV, d, LF, aff, carts, buys, H, it = U.load_all()
    conf = json.loads((HERE / a.file).read_text()); arms = live.clean_lfm_arms(conf.get("lfm_arms"))
    assert len(arms) == 2 and "oqa" not in arms[0] and "oqa" in arms[1], "need [control, challenger with oqa]"
    assert {k: v for k, v in arms[0].items() if k != "tag"} == {k: v for k, v in arms[1].items() if k not in ("tag", "oqa")}, "arms differ by more than oqa"
    ctl, chl = arms[0]["tag"], arms[1]["tag"]
    LF.set_arms(arms); live.LF = LF
    cold = cold_items.ColdStart(); live.AP = types.SimpleNamespace(cold=cold)
    C = R.Catalogue(); hset = set(H)
    d = d[(d.ts >= pd.Timestamp(a.since)) & (d.served_by == "team")]; d = d.iloc[::max(1, len(d) // a.n)]
    st_ = collections.defaultdict(collections.Counter); ms = collections.defaultdict(list); prior_log = []
    for g, cat, unavail, S, newp, burst in U.snapshots(R, qrank, LF, aff, d, H, it):
        ver = C.version(g.ts.iloc[0]); desc = C.asof(None if pd.isna(ver) else ver)[2]
        cold.desc = dict(desc or {})
        bucket = g.ts.iloc[0].floor("10min")
        today = it[it.b <= bucket].groupby("i")[["v", "p"]].sum(); oq = dict(H)
        for i, v, p in zip(today.index, today.v.values, today.p.values):
            h = oq.get(i); oq[i] = (v + h[0], p + h[1]) if h else (float(v), float(p))
        pr = live.attr_prior(cat, hset)
        S.orate_d = lfm.organic_prior_delta(S.ids, oq, hset, pr) if pr else None
        nohist = [p for p in cat.index if p not in hset]
        prior_log.append(dict(bucket=str(bucket), no_history=len(nohist), with_prior=len(pr or {}), delta_nonzero=int((S.orate_d != 0).sum()) if S.orate_d is not None else 0,
                              prior_p10_p50_p90=[round(float(x), 4) for x in np.percentile(list(pr.values()), [10, 50, 90])] if pr else None))
        for r in g.itertuples():
            st = LB.replay_state(LF, aff, carts, buys, r.user_id, r.ts)
            shim = R.AffAsOf(aff); shim.ts = r.ts
            page = r.page or "product"
            req = dict(user_id=r.user_id, rv=r.rv, page=page, is_new_user=bool(r.new_user), device=r.device, region=r.region)
            seg = ("new" if r.new_user else "known") + ("/page" if (r.rv and page in lfm.LQ_PAGES) else "/home" if not r.rv else "/other")
            outs = {}
            for tag in (ctl, chl):
                t0 = time.perf_counter(); s = LF.slate(req, st, shim, exclude=unavail, model=tag); ms[tag].append(1000 * (time.perf_counter() - t0))
                ok = s is not None and len(s) == 10 and len(set(s)) == 10 and not (set(s) & unavail) and not (set(s) & st[0]) and all(p in cat.index for p in s)
                outs[tag] = (s or [], ok)
            b, s = outs[ctl][0], outs[chl][0]
            c = st_[seg]; c["requests"] += 1; c["valid_ctl"] += outs[ctl][1]; c["valid_chl"] += outs[chl][1]
            c["changed"] += s != b; c["slot1"] += bool(s and b and s[0] != b[0]); c["overlap"] += len(set(s) & set(b))
            c["launched_ctl"] += sum(p in newp for p in b); c["launched_chl"] += sum(p in newp for p in s)
            c["old_changed"] += [p for p in b if p not in newp] != [p for p in s if p not in newp][:len([p for p in b if p not in newp])] and sum(p in newp for p in b) == sum(p in newp for p in s)
    res = {}
    for seg, c in sorted(st_.items()):
        m = max(1, c["requests"])
        res[seg] = dict(requests=c["requests"], valid_ctl_pct=round(100 * c["valid_ctl"] / m, 2), valid_chl_pct=round(100 * c["valid_chl"] / m, 2), changed_pct=round(100 * c["changed"] / m, 1),
                        slot1_changed_pct=round(100 * c["slot1"] / m, 1), overlap=round(c["overlap"] / m, 2),
                        launched_per_list_ctl=round(c["launched_ctl"] / m, 2), launched_per_list_chl=round(c["launched_chl"] / m, 2))
    pct = lambda v, q: round(float(np.percentile(v, q)), 2)
    lat = {f: dict(p50=pct(v, 50), p95=pct(v, 95), p99=pct(v, 99)) for f, v in ms.items()}
    pd.set_option("display.width", 250); print(pd.DataFrame(res).T.to_string()); print("latency ms", json.dumps(lat)); print("prior, first / last snapshot", json.dumps(prior_log[:1] + prior_log[-1:]))
    if a.out: Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(json.dumps(dict(kind="diagnostics: validity and exposure, NOT conversion", since=a.since, policy=arms, segments=res, latency_ms=lat, prior=prior_log), indent=1))


if __name__ == "__main__":
    main()
