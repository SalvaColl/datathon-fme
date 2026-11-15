"""E-460 — replay of the re-cart arm option (T-046) through the writer's own code. DIAGNOSTICS, never a result: the hidden
model decides, on the leaderboard, candidate vs control vs reference in identical windows.

    cd recsys
    python download_user_items.py && python cold_lq_replay.py --pull      # READ-ONLY RawTree
    python recart_replay.py [--n 12000] [--since "2026-11-14 12:00"] [--pairs cs2r,r3] [--out file.json]

Every sampled answered request is served twice per pair (control arm, the same arm with "recart": true) by
live.clean_lfm_arms -> LiveFit.set_arms -> LiveFit.slate, with the catalogue, stock and shopper state AS OF the request
(as cold_lq_replay.py builds them). No value model: the bonus is in the served lists, and what is reported is what
changes (first slot, top 3, composition), validity and latency, by cohort. Cohorts outside the target must not change.
Also printed: what our own carousel sold for re-carted products vs history-only carts, by slot group (observed feedback,
lists the live arms chose: selected, not causal).
"""
from __future__ import annotations
import argparse, collections, json, os, sys, time
from pathlib import Path
import numpy as np, pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
R3 = "lfm_coef_r3.json"
PAIRS = {       # name -> control arm (without tag); the candidate is the same arm plus "recart": true
    "cx3": {"file": R3, "w": {"known": {"chn": 3.0}}, "home": {"file": R3}},
    "r3": {"file": R3},
    # T-051: cs2r (policy.rot_cs2r.json), chn 3.0 = cl 3.0, so only products carted 2+ times in the history get anything
    "cs2r": {"file": R3, "w": {"known": {"chn": 3.0, "cl": 3.0, "ssub2": 3.0, "scat2": 3.0, "ucat": 6.0, "islast": 3.7, "oinrv": 4.0}}, "home": {"file": R3}},
}


def main(n=12000, since="2026-11-14 12:00:00", out=None, pairs=("cx3", "r3")):
    PAIRS = {k: globals()["PAIRS"][k] for k in pairs}      # at most 2 pairs: clean_lfm_arms takes 4 arms
    os.environ.setdefault("DRY_RUN", "1")
    import lfm, lfm_build as LB, cold_lq_replay as R, qrank
    sys.argv = [sys.argv[0], "--dry-run"]
    import live
    d, LF, aff, carts, buys = LB.load()
    LF.lq0 = float(json.loads((HERE / R3).read_text()).get("lq0", LF.lq0))
    arms = []
    for name, spec in PAIRS.items(): arms += [{"tag": name, **spec}, {"tag": name + "rc", **spec, "recart": True}]
    clean = live.clean_lfm_arms(arms); assert len(clean) == len(arms), "clean_lfm_arms rejected the arms"
    LF.set_arms(clean)
    hc = LF.snap.hc
    d = d[d.ts >= pd.Timestamp(since)]
    full = d
    d = d.iloc[::max(1, len(d) // n)]
    C = R.Catalogue(); QR = qrank.Ranker.load(HERE / "data" / "qrank.joblib"); shim = R.AffAsOf(aff)
    d = d.assign(ver=[C.version(t) for t in d.ts], bucket=d.ts.dt.floor("10min"))
    st_ = collections.defaultdict(collections.Counter); ms = collections.defaultdict(list)
    for (ver, bucket), g in d.groupby(["ver", "bucket"], sort=True, dropna=False):
        cat, unavail, desc = C.asof(None if pd.isna(ver) else ver)
        QR.set_catalog(cat, unavail); newp = set(cat.index) - set(QR.q)
        LF.set_catalog(cat, unavail, aff, QR.lq, hc, newp=newp or None)
        S = LF.snap
        for r in g.itertuples():
            shim.ts = r.ts; st = LB.replay_state(LF, aff, carts, buys, r.user_id, r.ts)
            bought, lc, hcu = st[:3]
            page = r.page or "product"
            req = dict(user_id=r.user_id, rv=r.rv, page=page, is_new_user=bool(r.new_user), device=r.device, region=r.region)
            coh = ("new" if r.new_user else "known") + ("/page" if (r.rv and page in lfm.LQ_PAGES) else "/home")
            h = LF.hcart.get(r.user_id) or {}
            re = {p for p in lc if h.get(p) and p in S.row and S.ok[S.row[p]] and p not in unavail}        # carted in the history and again today, servable
            for name in PAIRS:
                lists = {}
                for tag in (name, name + "rc"):
                    t0 = time.perf_counter(); s = LF.slate(req, st, shim, exclude=unavail, model=tag); ms[tag].append(1000 * (time.perf_counter() - t0))
                    lists[tag] = s
                a, b = lists[name], lists[name + "rc"]
                for key in (name + "|" + coh, name + "|all") + ((name + "|known/page with re-carts",) if coh == "known/page" and re else ()):
                    c = st_[key]; c["requests"] += 1; c["with_recart"] += bool(re); c["recarts"] += len(re)
                    for tag, s in ((name, a), (name + "rc", b)):
                        good = s is not None and len(s) == 10 and len(set(s)) == 10 and not (set(s) & unavail) and not (set(s) & bought) and all(p in cat.index for p in s)
                        c["valid_" + tag] += good
                        if s is None: continue
                        pos = [k for k, p in enumerate(s) if p in re]
                        c["re_in_list_" + tag] += len(pos); c["re_top3_" + tag] += sum(k < 3 for k in pos); c["re_slot1_" + tag] += bool(pos and pos[0] == 0)
                        c["req_re_shown_" + tag] += bool(pos); c["carts_" + tag] += sum(p in lc or p in hcu for p in s)
                    if a is None or b is None: c["none"] += 1; continue
                    c["changed"] += a != b; c["slot1"] += a[0] != b[0]; c["top3"] += a[:3] != b[:3]; c["replaced"] += len(set(b) - set(a))
                    c["same_set_reordered"] += a != b and set(a) == set(b)
    res = {}
    for key, c in sorted(st_.items()):
        name = key.split("|")[0]; m = max(1, c["requests"]); rc = name + "rc"
        res[key] = dict(requests=c["requests"], requests_with_recart_pct=round(100 * c["with_recart"] / m, 1), recarts_per_request=round(c["recarts"] / m, 2),
                        lists_changed_pct=round(100 * c["changed"] / m, 2), slot1_changed_pct=round(100 * c["slot1"] / m, 2), top3_changed_pct=round(100 * c["top3"] / m, 2),
                        products_replaced=round(c["replaced"] / m, 3), only_reordered_pct=round(100 * c["same_set_reordered"] / m, 2),
                        valid_pct={t: round(100 * c["valid_" + t] / m, 2) for t in (name, rc)},
                        recarts_in_list={t: round(c["re_in_list_" + t] / m, 3) for t in (name, rc)}, recarts_in_top3={t: round(c["re_top3_" + t] / m, 3) for t in (name, rc)},
                        recart_at_slot1_pct={t: round(100 * c["re_slot1_" + t] / m, 2) for t in (name, rc)},
                        requests_showing_a_recart_pct={t: round(100 * c["req_re_shown_" + t] / m, 2) for t in (name, rc)},
                        carts_per_list={t: round(c["carts_" + t] / m, 2) for t in (name, rc)})
    pct = lambda v, q: round(float(np.percentile(v, q)), 2)
    lat = {t: dict(p50=pct(v, 50), p95=pct(v, 95), p99=pct(v, 99), max=round(max(v), 2)) for t, v in ms.items()}
    obs = observed(full, LF, aff, carts, buys, LB, lfm)
    outd = dict(kind="replay through LiveFit.slate, state as of each request; diagnostics, not a leaderboard prediction", since=since, requests=int(len(d)),
                first=str(d.ts.min()), last=str(d.ts.max()), arms=clean, segments=res, latency_ms=lat, observed_feedback=obs)
    if out: Path(out).parent.mkdir(parents=True, exist_ok=True); Path(out).write_text(json.dumps(outd, indent=1))
    print(json.dumps(outd, indent=1))
    return outd


def observed(d, LF, aff, carts, buys, LB, lfm):
    """What our carousel sold, returning shoppers on product/category pages with views, by cart type of the shown product and slot group."""
    k = d[(~d.new_user) & (d.rv.str.len() > 0) & d.page.isin(lfm.LQ_PAGES)]
    tab = collections.defaultdict(lambda: [0, 0]); reqs = collections.Counter()
    for r in k.itertuples():
        b, lc, hcu, bt = LB.state_asof(LF, carts, buys, r.user_id, r.ts, getattr(aff, "fbuys", None))
        h = LF.hcart.get(r.user_id) or {}
        re = {p for p in lc if h.get(p)}
        reqs["requests"] += 1; reqs["with_recart"] += bool(re)
        for s, p in enumerate(r.shown[:10]):
            if p in b: continue
            ty = "recart" if p in re else "today_only" if p in lc else "history_only" if p in hcu else "no_cart"
            g = "slot1" if s == 0 else "slots2-3" if s < 3 else "slots4-10"
            for key in (ty + "|" + g, ty + "|all"):
                tab[key][0] += 1; tab[key][1] += int(p == r.purchased)
    return dict(requests=reqs["requests"], requests_with_recart_pct=round(100 * reqs["with_recart"] / max(1, reqs["requests"]), 1),
                cells={key: dict(impressions=v[0], buys=v[1], per10k=round(1e4 * v[1] / v[0], 1) if v[0] else None) for key, v in sorted(tab.items())})


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=12000); ap.add_argument("--since", default="2026-11-14 12:00:00"); ap.add_argument("--out")
    ap.add_argument("--pairs", default="cx3,r3", help="one or two of: " + ", ".join(PAIRS))
    a = ap.parse_args(); main(a.n, a.since, a.out, tuple(a.pairs.split(",")))
