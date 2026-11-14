"""Live recommender v1: candidate generation + gradient-boosting purchase model.

    .venv/bin/python live.py --dry-run     # compute answers, measure latency, do NOT write submissions
    .venv/bin/python live.py               # LIVE: writes to TEAM_ID.submissions (only ONE writer per team!)

pull -> predict -> push like the starter. Falls back to in-stock best sellers on any per-request error.
"""
from __future__ import annotations
import os, sys, time, json, threading, traceback
from pathlib import Path
import numpy as np, pandas as pd, requests, joblib
import fe
from fe import build_tables, featurize, FEATS

ENV = next((p for p in (Path(".env"), Path("../.env")) if p.exists()), None)
for line in ENV.read_text().splitlines() if ENV else []:
    k, _, v = line.partition("="); os.environ.setdefault(k.strip(), v.strip())
API = "https://api.rawtree.com"; TEAM = os.environ["TEAM_ID"]
http = requests.Session(); http.headers["Authorization"] = f"Bearer {os.environ['RAWTREE_API_KEY']}"
DRY = "--dry-run" in sys.argv
VERSION = "v1-gbm-cand"

def query(sql, timeout=20):
    r = http.post(f"{API}/v1/query", json={"sql": sql}, timeout=timeout); r.raise_for_status(); return r.json()["data"]

# ---------- state ----------
MODEL = joblib.load("data/model_buy.joblib")
BASE = build_tables(pd.read_parquet("data/user_item_all.parquet"))
state = {"live": None, "cat": None, "unavail": set(), "pools": None, "best": None, "ev_ts": "2026-11-14 07:00:00"}
lock = threading.Lock()

def refresh_catalog():
    rows = query("""SELECT product_id::String product_id, argMax(category::String,v) category, argMax(subcategory::String,v) sub,
      argMax(brand::String,v) brand, argMax(price_eur::Float64,v) price, argMax(created_at::String,v) created,
      argMax(is_active::Bool,v) active, argMax(chg,v) last_change
    FROM (SELECT product_id, category, subcategory, brand, price_eur, created_at, is_active, '' chg, '' v FROM shop.catalog
          UNION ALL SELECT product_id, category, subcategory, brand, price_eur, created_at, is_active, change::String, toString(ts) FROM shop.catalog_updates)
    GROUP BY product_id""")
    cat = pd.DataFrame(rows).set_index("product_id")
    unavail = set(cat.index[(~cat.active.astype(bool)) | (cat.last_change == "out_of_stock")])
    return cat, unavail

def refresh_events():
    rows = query(f"""SELECT user_id::String u, product_id::String i, toUInt32(countIf(event_type='view')) v,
      toUInt32(countIf(event_type='add_to_cart')) a, toUInt32(countIf(event_type='purchase')) p, max(ts::DateTime64(3))::String mx
      FROM shop.events WHERE ts::DateTime64(3) > toDateTime64('{state['ev_ts']}',3) GROUP BY u,i""", timeout=60)
    for r in rows: LIVE.add(r["u"], r["i"], r["v"], r["a"], r["p"])
    if rows: state["ev_ts"] = max(r["mx"] for r in rows)
    try:  # our own carousel purchases: shopper won't want them again
        fb = query(f"SELECT r.user_id::String u, f.purchased::String i FROM {TEAM}.feedback f INNER JOIN shop.requests r ON r.request_id::String=f.request_id::String WHERE f.purchased::String != '' AND f.ts::DateTime64(3) > now() - INTERVAL 2 MINUTE")
        for r in fb:
            if r["i"] not in fb_seen.setdefault(r["u"], set()):
                fb_seen[r["u"]].add(r["i"]); LIVE.add(r["u"], r["i"], 0, 0, 1)
    except Exception as e: print("fb refresh failed", e)
    return LIVE


class _Lookup:
    """Dict-backed stand-in for a DataFrame: .reindex(keys) -> DataFrame (missing keys = 0)."""
    def __init__(self, cols): self.d = {}; self.cols = cols
    def add(self, key, vals):
        x = self.d.get(key)
        if x is None: self.d[key] = list(vals)
        else:
            for k, v in enumerate(vals): x[k] += v
    def reindex(self, idx):
        z = [0] * len(self.cols); g = self.d.get
        return pd.DataFrame([g(k, z) for k in idx], columns=self.cols, index=idx)


class LiveTables(dict):
    """Incremental version of fe.build_tables for the live event stream: O(delta) per refresh."""
    def __init__(self):
        super().__init__(item=_Lookup(["it_v", "it_a", "it_p"]), usub=_Lookup(["us_v", "us_p"]), ucat=_Lookup(["uc_v", "uc_p"]),
                         utot=_Lookup(["ut_v", "ut_p"]), uit=_Lookup(["ui_v", "ui_a", "ui_p"]))
    def add(self, u, i, v, a, p):
        c = fe.C
        if i not in c.index: return
        s, k = c.at[i, "sub"], c.at[i, "category"]
        self["item"].add(i, (v, a, p)); self["uit"].add((u, i), (v, a, p)); self["usub"].add((u, s), (v, p))
        self["ucat"].add((u, k), (v, p)); self["utot"].add(u, (v, p))
    def item_frame(self):
        d = self["item"].d
        return pd.DataFrame.from_dict(d, orient="index", columns=self["item"].cols) if d else None

LIVE = LiveTables(); fb_seen = {}

def make_pools(cat, unavail, T):
    it = BASE["item"].copy()
    li = T.item_frame() if T is not None else None
    if li is not None: it = it.add(li, fill_value=0)
    it = it.reindex(cat.index).fillna(0)
    ok = cat.assign(cart=(it.it_a + 1) / (it.it_v + 50), pop=it.it_p)
    ok = ok[~ok.index.isin(unavail)]
    ok["score"] = ok.cart * np.log1p(ok["pop"] + 1)
    by_cat = {c: g.sort_values("score", ascending=False).index[:120].tolist() for c, g in ok.groupby("category")}
    by_sub = {s: g.sort_values("score", ascending=False).index[:25].tolist() for s, g in ok.groupby("sub")}
    new = ok[ok.last_change == "new_product"].index.tolist()
    best = ok.sort_values("pop", ascending=False).index.tolist()
    glob = ok.sort_values("score", ascending=False).index[:150].tolist()
    return dict(cat=by_cat, sub=by_sub, new=new, glob=glob), best

# user's own past items (base history), for candidates
U_ITEMS = pd.read_parquet("data/user_item_all.parquet").query("a>0 or v>=2").groupby("u").i.apply(list).to_dict()

def refresher():
    while True:
        try:
            cat, unavail = refresh_catalog()
            with lock: fe.set_catalog(cat)  # LIVE.add needs current catalog (new products)
            T = refresh_events()
            pools, best = make_pools(cat, unavail, T)
            with lock:
                fe.set_catalog(cat); state.update(cat=cat, unavail=unavail, live=T, pools=pools, best=best)
        except Exception as e: print("refresh error", e); traceback.print_exc()
        time.sleep(20)

def candidates(req, pools, unavail, cat):
    rv = req["rv"]; c = []
    c += rv
    for p in rv[-3:]:
        if p in cat.index: c += pools["sub"].get(cat.at[p, "sub"], []) + pools["cat"].get(cat.at[p, "category"], [])
    c += [x for x in U_ITEMS.get(req["user_id"], [])[:60]]
    if not rv: c += pools["glob"]
    c += [p for p in pools["new"] if not rv or (p in cat.index and cat.at[p, "category"] == cat.at[rv[-1], "category"])][:30]
    seen = set(); out = []
    for p in c:
        if p not in seen and p in cat.index and p not in unavail: seen.add(p); out.append(p)
    return out

def predict(reqs):
    with lock: pools, unavail, cat, live, best = state["pools"], state["unavail"], state["cat"], state["live"], state["best"]
    fallback = [p for p in best if p not in unavail][:10]
    rows = []
    for k, r in enumerate(reqs):
        for p in candidates(r, pools, unavail, cat):
            rows.append((k, r["user_id"], p, 0, r["rv"], r["page"], bool(r.get("is_new_user"))))
    P = pd.DataFrame(rows, columns=["sid", "u", "i", "slot", "rv", "page", "new_user"])
    out = []
    try:
        X = featurize(P, [BASE, live] if live is not None else BASE, pd.Timestamp.now("UTC").tz_localize(None))
        X["s"] = MODEL.predict_proba(X[FEATS])[:, 1]
        top = X.sort_values("s", ascending=False).groupby("sid").i.apply(list).to_dict()
    except Exception as e:
        print("predict error", e); traceback.print_exc(); top = {}
    for k, r in enumerate(reqs):
        items = top.get(k, [])[:10]
        if len(items) < 10: items += [p for p in fallback if p not in items][: 10 - len(items)]
        if len(set(items)) != 10: items = fallback
        out.append({"request_id": r["request_id"], "items": items, "model_version": VERSION})
    return out

def fallback_answers(reqs):
    with lock: best, unavail = state["best"], state["unavail"]
    items = [p for p in best if p not in unavail][:10]
    return [{"request_id": r["request_id"], "items": items, "model_version": VERSION + "-guard"} for r in reqs]

def pull(seen):
    rows = query("SELECT request_id::String request_id, ts::String ts, user_id::String user_id, is_new_user, context.page::String page, toJSONString(recent_views) rv FROM shop.requests ORDER BY ts DESC LIMIT 60")
    fresh = []
    for r in rows:
        if r["request_id"] in seen: continue
        seen.add(r["request_id"]); r["rv"] = [x["product_id"] for x in json.loads(r["rv"])]; fresh.append(r)
    return fresh

def main():
    threading.Thread(target=refresher, daemon=True).start()
    while state["pools"] is None: time.sleep(0.5)
    print("ready", "DRY RUN" if DRY else "LIVE", flush=True)
    seen = set(); lat = []
    first = True
    while True:
        try:
            reqs = pull(seen)
            if first: first = False; reqs = []  # skip stale backlog on start
            if reqs:
                t0 = time.time(); now = pd.Timestamp.now("UTC").tz_localize(None)
                # deadline guard: requests already >1.8s old get the instant fallback slate instead of the model
                old = [r for r in reqs if (now - pd.Timestamp(r["ts"])).total_seconds() > 1.8]
                ok = [r for r in reqs if r not in old]
                ans = (predict(ok) if ok else []) + fallback_answers(old); dt = time.time() - t0
                if old: print(f"deadline guard: {len(old)} requests served with fallback", flush=True)
                if not DRY:
                    http.post(f"{API}/v1/tables/submissions", params={"database": TEAM}, json=ans, timeout=5).raise_for_status()
                now = pd.Timestamp.now("UTC").tz_localize(None)
                lag = [(now - pd.Timestamp(r["ts"])).total_seconds() for r in reqs]; lat += lag
                if len(lat) >= 60:
                    print(f"{'dry' if DRY else 'sent'} n={len(lat)} age p50={np.median(lat):.2f}s p95={np.percentile(lat,95):.2f}s max={max(lat):.2f}s predict={dt*1000:.0f}ms ex={ans[-1]['items'][:3]}", flush=True); lat = []
        except Exception as e:
            print("loop error", e); time.sleep(1)
        time.sleep(0.25)

if __name__ == "__main__":
    main()
