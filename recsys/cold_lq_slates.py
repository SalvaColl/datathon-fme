"""E-CS01d: what does cold_lq change in lfm's slates? Same real requests, same state, lq from qrank vs lq from cold_lq.

    cd recsys
    python cold_lq_slates.py            # needs data/bench/ (replay_backfill.py prep, read-only) and data/coldlq/ snapshot

Offline, no network, no writes. Rebuilds what the live writer holds at 15:00 UTC on 14 Nov: catalogue (base + the 200
products launched at 10:00 and 14:00), qrank, aff_policy (phrases of the new products synced), lfm with today's
organic events applied per (user, product) exactly like refresh_events(). Then answers the 900 real requests of
14:5x-15:00 with lfm twice. Reports new-product exposure and how many slates change, by segment. It says nothing about
conversion: that needs the hidden model (a live A/B by the writer owner).
Limits: stock-outs are not replayed (every catalogue product eligible); home_cands' "dead item" bitmap is not loaded.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
CUT = "2026-11-14 15:00:00"


def main():
    import aff_policy, cold_items, cold_lq, lfm, qrank
    snap = json.load(open(HERE / "data/coldlq/live_snapshot.json"))
    newp = pd.DataFrame(snap["new_products"]).set_index("product_id")
    newp = newp[newp.launched < CUT]
    base = pd.read_parquet(HERE / "data/catalog.parquet").set_index("product_id")
    cat = pd.concat([base[["category", "sub", "brand", "price"]], newp[["category", "sub", "brand", "price"]]])
    QR = qrank.Ranker.load(HERE / "data/qrank.joblib"); QR.set_catalog(cat, set())
    AP = aff_policy.AffPolicy.load(HERE / "data")
    for p, d in newp.description.items():
        AP.cold.desc[p] = d; AP.cold.attr[p] = cold_items.attrs(d)
    AP.aff.sync_products()
    history = pd.read_parquet(HERE / "data/user_item_all.parquet")
    LF = lfm.LiveFit.load(history)
    ev = pd.read_parquet(HERE / "data/bench/events.parquet")
    ev = ev[ev.t <= CUT]
    for k, name in (("v", "view"), ("a", "add_to_cart"), ("p", "purchase")):
        ev[k] = (ev.e == name).astype(int)
    g = ev.groupby(["u", "i"])[["v", "a", "p"]].sum().reset_index()
    for u, i, v, a, p in g.itertuples(index=False):
        LF.add(u, i, v, a, p); AP.add(u, i, v)
    live_item = g.groupby("i")[["v", "p"]].sum().rename(columns={"v": "it_v", "p": "it_p"})
    hist_item = history.groupby("i")[["v", "p"]].sum().rename(columns={"v": "it_v", "p": "it_p"})
    lq_new = cold_lq.ColdLQ().lq_for_lfm(QR, cat, hist_item, live_item, newp.description.to_dict(), force=True)
    reqs = json.load(open(HERE / "data/bench/snapshots.json"))["requests"]
    new = set(newp.index)
    stats = collections.defaultdict(collections.Counter)
    for name, lqd in (("qrank_lq", QR.lq), ("cold_lq", lq_new)):
        LF.set_catalog(cat, set(), AP.aff, lqd, None)
        for r in reqs:
            views = json.loads(r["rv"]) if isinstance(r["rv"], str) else (r["rv"] or [])
            rv = [x["product_id"] for x in views if isinstance(x, dict) and x.get("product_id")]
            is_new = str(r.get("is_new_user")).lower() in ("true", "1")
            req = dict(user_id=r["user_id"], rv=rv, page=r.get("page") or "product", is_new_user=is_new)
            s = LF.slate(req, LF.user_state(r["user_id"]), AP.aff) or []
            seg = ("new" if is_new else "known") + "/" + ("home" if not rv else "views")
            for key in (seg, "all"):
                c = stats[(name, key)]
                c["requests"] += 1; c["valid"] += len(set(s)) == 10; c["imp"] += len(s)
                c["imp_new"] += sum(p in new for p in s); c["slot1_new"] += bool(s) and s[0] in new
                c["with_new"] += any(p in new for p in s)
                stats[("slates", r["request_id"])][name] = s
    out = {"cut": CUT, "requests": len(reqs), "new_products": len(new), "segments": {}}
    for key in sorted({k for n, k in stats if n == "qrank_lq"}):
        row = {}
        for name in ("qrank_lq", "cold_lq"):
            c = stats[(name, key)]
            row[name] = dict(new_share_pct=round(100 * c["imp_new"] / max(1, c["imp"]), 2),
                             slot1_new_pct=round(100 * c["slot1_new"] / max(1, c["requests"]), 2),
                             slates_with_new_pct=round(100 * c["with_new"] / max(1, c["requests"]), 1),
                             valid_pct=round(100 * c["valid"] / max(1, c["requests"]), 1))
        row["requests"] = stats[("qrank_lq", key)]["requests"]
        out["segments"][key] = row
    pairs = [v for (n, _), v in stats.items() if n == "slates"]
    out["slates_changed_pct"] = round(100 * sum(p["qrank_lq"] != p["cold_lq"] for p in pairs) / len(pairs), 1)
    out["slot1_changed_pct"] = round(100 * sum((p["qrank_lq"][:1] != p["cold_lq"][:1]) for p in pairs) / len(pairs), 1)
    out["new_products_patched"] = sum(1 for p in new if lq_new.get(p) != QR.lq.get(p))
    print(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    main()
