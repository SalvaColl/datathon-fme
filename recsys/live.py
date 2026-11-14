"""Live recommender v1: candidate generation + gradient-boosting purchase model.

    .venv/bin/python live.py --dry-run     # compute answers, measure latency, do NOT write submissions
    .venv/bin/python live.py               # LIVE: writes to TEAM_ID.submissions (only ONE writer per team!)

pull -> predict -> push like the starter. Falls back to in-stock best sellers on any per-request error.
"""
from __future__ import annotations
import os, sys, time, json, threading, traceback, zlib, collections
from pathlib import Path
os.environ.setdefault('OMP_NUM_THREADS', '1')
import numpy as np, pandas as pd, requests, joblib
if __package__:
    from . import fe, qrank, aff_policy
    from .serving import Journal, WriterLock, age, repair, serve
else:
    import fe, qrank, aff_policy
    from serving import Journal, WriterLock, age, repair, serve
build_tables, featurize, FEATS = fe.build_tables, fe.featurize, fe.FEATS
DATA = Path(__file__).resolve().parent / 'data'

ENV = next((p for p in (Path(".env"), Path("../.env")) if p.exists()), None)
for line in ENV.read_text().splitlines() if ENV else []:
    k, _, v = line.partition("="); os.environ.setdefault(k.strip(), v.strip())
API = os.environ.get('RAWTREE_API_URL', 'https://api.rawtree.com').rstrip('/'); TEAM = os.environ.get("TEAM_ID", '')
transport = threading.local()
def session():
    # requests.Session is mutable: never share one across poll/refresh/stock threads.
    if not hasattr(transport, 'http'):
        transport.http = requests.Session()
        transport.http.headers['Authorization'] = f"Bearer {os.environ['RAWTREE_API_KEY']}"
    return transport.http
DRY = "--dry-run" in sys.argv
AB = "--ab" in sys.argv  # 50/50 by user hash: half baseline (control), half model, ONE writer
VERSION = "v1-gbm-cand-r1"
VERSION_Q = "v2-qrank-r1"
VERSION_A = "v1-aff-r1"            # GBM x description-phrase affinity (D-090)
VERSION_QA = "v2-qrank-aff-r1"     # qrank x description-phrase affinity
# Ranking variant for requests WITH recent views (product/category pages). Hot-switchable: the refresher re-reads
# data/policy.json every cycle, e.g. {"variant": "qrank"}.  v1 = GBM (default, unchanged behaviour) | qrank = qrank.py
# | ab_qrank = 50/50 by user hash, v1 vs qrank, so compare_versions.py can compare the two model_versions.
# D-090 adds the affinity family: aff = GBM x affinity on every page | qrank_aff = qrank x affinity on pages with
# views, GBM x affinity on home | ab_aff = 50/50 by user hash, v1 vs aff | ab_qrank_aff = 50/50, qrank vs qrank_aff.
VARIANTS = ("v1", "qrank", "ab_qrank", "aff", "qrank_aff", "ab_aff", "ab_qrank_aff")
POLICY = {"variant": next((v for v in VARIANTS[1:] if "--" + v.replace("_", "-") in sys.argv), "v1")}
def treated(user_id): return zlib.crc32(user_id.encode()) % 2 == 1      # A/B arm, stable per user
def use_aff(r):
    """Does this request get the affinity policy under the active variant? Never if aff_policy failed to load."""
    v = POLICY['variant']
    return AP is not None and (v in ('aff', 'qrank_aff') or (v in ('ab_aff', 'ab_qrank_aff') and treated(r['user_id'])))
def use_qrank(r):
    v = POLICY['variant']
    return bool(r.get('rv')) and (v in ('qrank', 'qrank_aff', 'ab_qrank_aff') or (v == 'ab_qrank' and treated(r['user_id'])))
def read_policy():
    try:
        v = json.loads((DATA / 'policy.json').read_text()).get('variant')
        if v in VARIANTS and v != POLICY['variant']:
            POLICY['variant'] = v; print(json.dumps(dict(event='policy', variant=v)), flush=True)
    except FileNotFoundError: pass
    except Exception as e: print('policy.json ignored', type(e).__name__, flush=True)

def query(sql, timeout=20):
    r = session().post(f"{API}/v1/query", json={"sql": sql}, timeout=timeout); r.raise_for_status(); return r.json()["data"]

# ---------- state ----------
MODEL, BASE, U_ITEMS = None, None, {}
QR = None                                  # qrank.Ranker, loaded by initialize() if data/qrank.joblib exists
BOUGHT = collections.defaultdict(set)      # user -> products bought today (organic stream + our carousel feedback)
AP = None                                  # aff_policy.AffPolicy, loaded by initialize(); None -> aff variants act as v1/qrank
def initialize():
    global MODEL, BASE, U_ITEMS, QR, AP
    try: AP = aff_policy.AffPolicy.load(DATA)
    except Exception as e: print('aff_policy not loaded, affinity variants disabled:', type(e).__name__, e, flush=True)
    try: QR = qrank.Ranker.load(DATA / 'qrank.joblib')
    except Exception as e: print('qrank not loaded, serving v1 only:', type(e).__name__, flush=True)
    MODEL = joblib.load(DATA / 'model_buy.joblib')
    history = pd.read_parquet(DATA / 'user_item_all.parquet')
    BASE = build_tables(history)
    U_ITEMS = history.query('a>0 or v>=2').groupby('u').i.apply(list).to_dict()

state = {"live": None, "cat": None, "unavail": set(), "stock_out": set(), "stock_checked": 0,
         "pools": None, "best": None, "ev_ts": "2026-11-14 07:00:00"}
lock = threading.Lock()
feature_lock = threading.Lock()

def snapshot():
    with lock:
        return state['pools'], state['unavail'] | state['stock_out'], state['cat'], state['live'], state['best']

def stock_refresher():
    while True:
        try:
            rows = query("""SELECT product_id::String product_id FROM shop.catalog_updates
                WHERE change::String IN ('out_of_stock','back_in_stock') GROUP BY product_id
                HAVING argMax(change::String, ts::DateTime64(3)) = 'out_of_stock'""", timeout=(0.5, 1.5))
            with lock:
                state.update(stock_out={r['product_id'] for r in rows}, stock_checked=time.monotonic())
        except Exception as e:
            print('stock refresh failed', type(e).__name__, flush=True)
        time.sleep(1)

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
    with feature_lock:
        for r in rows:
            LIVE.add(r["u"], r["i"], r["v"], r["a"], r["p"])
            if r["p"]: BOUGHT[r["u"]].add(r["i"])
            if AP is not None: AP.add(r["u"], r["i"], r["v"])
    if rows: state["ev_ts"] = max(r["mx"] for r in rows)
    try:  # our own carousel purchases: shopper won't want them again
        fb = query(f"SELECT r.user_id::String u, f.purchased::String i FROM {TEAM}.feedback f INNER JOIN shop.requests r ON r.request_id::String=f.request_id::String WHERE f.purchased::String != '' AND f.ts::DateTime64(3) > now() - INTERVAL 2 MINUTE")
        for r in fb:
            if r["i"] not in fb_seen.setdefault(r["u"], set()):
                fb_seen[r["u"]].add(r["i"])
                with feature_lock: LIVE.add(r["u"], r["i"], 0, 0, 1); BOUGHT[r["u"]].add(r["i"])
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
# U_ITEMS loaded by initialize(), never on import or inside the serving loop.

def refresher():
    while True:
        try:
            read_policy()
            cat, unavail = refresh_catalog()
            with lock: fe.set_catalog(cat)  # LIVE.add needs current catalog (new products)
            if QR is not None: QR.set_catalog(cat, unavail)
            if state['pools'] is None:
                # Serve from cached historical features while the first stream backfill runs.
                pools, best = make_pools(cat, unavail, None)
                with lock:
                    state.update(cat=cat, unavail=unavail, live=None, pools=pools, best=best)
            T = refresh_events()
            if AP is not None:
                try: AP.refresh(query, cat, BASE["item"], T.item_frame())
                except Exception as e: print('aff refresh failed', type(e).__name__, e, flush=True)
            pools, best = make_pools(cat, unavail, T)
            with lock:
                fe.set_catalog(cat); state.update(cat=cat, unavail=unavail, live=T, pools=pools, best=best)
        except Exception as e: print("refresh error", e); traceback.print_exc()
        time.sleep(20)

def candidates(req, pools, unavail, cat, aff=False):
    rv = req["rv"]; c = []
    c += rv
    if aff: c += AP.candidates(req, cat, unavail)
    for p in rv[-3:]:
        if p in cat.index: c += pools["sub"].get(cat.at[p, "sub"], []) + pools["cat"].get(cat.at[p, "category"], [])
    c += [x for x in U_ITEMS.get(req["user_id"], [])[:60]]
    if not rv: c += pools["glob"]
    last_category = cat.at[rv[-1], 'category'] if rv and rv[-1] in cat.index else None
    c += [p for p in pools["new"] if not rv or (last_category is not None and p in cat.index and cat.at[p, "category"] == last_category)][:30]
    seen = set(); out = []
    for p in c:
        if p not in seen and p in cat.index and p not in unavail: seen.add(p); out.append(p)
    return out

def predict(reqs):
    pools, unavail, cat, live, best = snapshot()
    fallback = [p for p in best if p not in unavail][:10]
    qver = {}
    quick = qrank_slates(reqs, unavail, qver)   # {index: slate} for requests answered by qrank; the rest go through the GBM
    aff = {k for k, r in enumerate(reqs) if k not in quick and use_aff(r)}   # GBM requests that get the affinity policy
    cold = AP.cold_tables if (AP is not None and POLICY['variant'] in ('aff', 'qrank_aff')) else None   # new-product pseudo-counts
    rows = []
    for k, r in enumerate(reqs):
        if k in quick: continue
        try: cand = candidates(r, pools, unavail, cat, aff=k in aff)
        except Exception as e:
            print('aff candidates error', type(e).__name__, e, flush=True); aff.discard(k); cand = candidates(r, pools, unavail, cat)
        for p in cand:
            rows.append((k, r["user_id"], p, 0, r["rv"], r["page"], bool(r.get("is_new_user"))))
    P = pd.DataFrame(rows, columns=["sid", "u", "i", "slot", "rv", "page", "new_user"])
    out = []
    try:
        if not len(P): raise LookupError('no GBM rows')
        with feature_lock:
            tables = [BASE] + ([live] if live is not None else []) + ([cold] if cold is not None else [])
            X = featurize(P, tables if len(tables) > 1 else BASE, pd.Timestamp.now("UTC").tz_localize(None), catalog=cat)
        X["s"] = MODEL.predict_proba(X[FEATS])[:, 1]
        if aff:
            try:
                m = X.sid.isin(aff).values
                X.loc[m, "s"] = X.s.values[m] * AP.boost(X[m])
            except Exception as e:
                print('aff boost error', type(e).__name__, e, flush=True); aff = set()
        top = X.sort_values("s", ascending=False).groupby("sid").i.apply(list).to_dict()
    except LookupError: top = {}
    except Exception as e:
        print("predict error", e); traceback.print_exc(); top = {}
    for k, r in enumerate(reqs):
        if k in quick:
            out.append({"request_id": r["request_id"], "items": quick[k], "model_version": qver.get(k, VERSION_Q)}); continue
        items = top.get(k, [])[:10]
        if len(items) < 10: items += [p for p in fallback if p not in items][: 10 - len(items)]
        if len(set(items)) != 10: items = fallback
        out.append({"request_id": r["request_id"], "items": items, "model_version": VERSION_A if k in aff else VERSION})
    return out

def qrank_slates(reqs, unavail, versions=None):
    """Slates from qrank for the requests the active variant routes to it. Any failure -> {} (GBM path).
    `versions` (optional dict) receives index -> VERSION_QA for the slates re-ranked with affinity."""
    if QR is None or not QR.ok: return {}
    try:
        idx = [k for k, r in enumerate(reqs) if use_qrank(r)]
        if not idx: return {}
        with feature_lock: bought = [set(BOUGHT.get(reqs[k]['user_id'], ())) for k in idx]
        qreqs = [{"user_id": reqs[k]['user_id'], "rv": reqs[k]['rv'], "page": reqs[k].get('page', 'product'), "bought": b | unavail} for k, b in zip(idx, bought)]
        out = {}
        want = [j for j, k in enumerate(idx) if use_aff(reqs[k])]
        try:
            for j, s in zip(want, AP.qrank_slates(QR, [qreqs[j] for j in want]) if want else []):
                if s is not None and len(set(s)) == 10:
                    out[idx[j]] = s
                    if versions is not None: versions[idx[j]] = VERSION_QA
        except Exception as e:
            print('aff qrank error', type(e).__name__, e, flush=True)
        todo = [j for j in range(len(idx)) if idx[j] not in out]      # plain qrank, and affinity requests that fell through
        for j, s in zip(todo, QR.slates([qreqs[j] for j in todo]) if todo else []):
            if s is not None and len(set(s)) == 10: out[idx[j]] = s
        return out
    except Exception as e:
        print('qrank error', type(e).__name__, e, flush=True); return {}

def fallback_answers(reqs, version=None):
    _, unavail, _, _, best = snapshot()
    items = [p for p in best if p not in unavail][:10]
    return [{"request_id": r["request_id"], "items": items, "model_version": version or VERSION + "-guard"} for r in reqs]

def pull(seen):
    rows = query("SELECT request_id::String request_id, ts::String ts, user_id::String user_id, is_new_user, context.page::String page, toJSONString(recent_views) rv FROM shop.requests ORDER BY ts DESC LIMIT 60", timeout=(0.5, 2.0))
    fresh = []
    for r in rows:
        if r["request_id"] in seen: continue
        try:
            views = json.loads(r['rv']) if isinstance(r['rv'], str) else r['rv']
            r['rv'] = [x['product_id'] for x in (views or []) if isinstance(x, dict) and x.get('product_id')]
        except (ValueError, TypeError):
            r['rv'] = []
        fresh.append(r)
    return fresh

def send_answers(reqs, answers, journal, seen, dry=False):
    """Recheck eligibility/deadline, durably claim once, then perform ONE POST."""
    _, unavailable, cat, _, best = snapshot()
    active = set(cat.index) - unavailable
    by_id = {a['request_id']: a for a in answers}
    batch = []
    for r in reqs:
        rid = r['request_id']
        if age(r) > 2.5:
            seen.add(rid)
            continue
        original = by_id.get(rid, {})
        items = repair(original.get('items'), best, active)
        version = original.get('model_version', VERSION + '-guard')
        if items != original.get('items'):
            version = VERSION + '-guard'
        answer = dict(request_id=rid, items=items, model_version=version)
        if dry or journal.claim(answer):
            batch.append(answer)
        seen.add(rid)
    if not batch:
        return
    if dry:
        return
    # Journal commits/validation take time too. Recheck immediately before POST.
    live_ids = {r['request_id'] for r in reqs if age(r) <= 2.5}
    dropped = [a['request_id'] for a in batch if a['request_id'] not in live_ids]
    if dropped:
        journal.finish(dropped, 'expired_before_post')
    batch = [a for a in batch if a['request_id'] in live_ids]
    if not batch:
        return
    started = time.perf_counter()
    remaining = min(3-age(r) for r in reqs if r['request_id'] in {a['request_id'] for a in batch})
    try:
        response = session().post(f'{API}/v1/tables/submissions', params={'database': TEAM},
            json=batch, timeout=(min(0.3, remaining/2), max(0.05, remaining-0.3)))
        response.raise_for_status()
    except Exception as exc:
        journal.finish([a['request_id'] for a in batch], 'uncertain')
        print(json.dumps(dict(event='push_uncertain', n=len(batch), error=type(exc).__name__,
                              post_ms=round(1000*(time.perf_counter()-started), 1))), flush=True)
        # A timeout can mean accepted-but-acknowledgement-lost. Never blindly retry.
        return
    journal.finish([a['request_id'] for a in batch], 'acknowledged')
    print(json.dumps(dict(event='push_ack', n=len(batch),
        post_ms=round(1000*(time.perf_counter()-started), 1),
        oldest_age_ms=round(1000*max(age(r) for r in reqs), 1))), flush=True)


def main():
    import tempfile
    directory = Path(tempfile.gettempdir()) / ('rawtree-' + TEAM)
    writer_lock = None if DRY else WriterLock(directory / 'writer.lock')
    journal = None if DRY else Journal(directory / 'attempts.sqlite3')
    try:
        initialize()
        threading.Thread(target=refresher, daemon=True).start()
        threading.Thread(target=stock_refresher, daemon=True).start()
        while state['pools'] is None:
            time.sleep(0.1)
        print('ready', 'DRY RUN' if DRY else 'LIVE', 'A/B 50/50' if AB else '', flush=True)
        seen = set()
        if not DRY:
            # First migration from the old writer has no local journal. Reconcile
            # newest IDs with remote submissions before serving any of them.
            seen.update(r['request_id'] for r in query(f"""SELECT DISTINCT s.request_id::String request_id
                FROM {TEAM}.submissions s INNER JOIN
                (SELECT request_id FROM shop.requests ORDER BY ts DESC LIMIT 60) r
                ON s.request_id::String = r.request_id::String"""))
        def deliver(reqs, answers):
            send_answers(reqs, answers, journal, seen, dry=DRY)
        def score(reqs):
            ctrl = [r for r in reqs if AB and zlib.crc32(r['user_id'].encode()) % 2 == 0]
            model = [r for r in reqs if r not in ctrl]
            return (predict(model) if model else []) + fallback_answers(ctrl, 'baseline-ctrl')
        while True:
            started = time.perf_counter()
            try:
                reqs = pull(seen)
                if journal:
                    reqs = [r for r in reqs if not journal.contains(r['request_id'])]
                expired_ids = {r['request_id'] for r in reqs if age(r) > 2.5}
                seen.update(expired_ids)
                expired = serve(reqs, score, fallback_answers, deliver)
                if reqs:
                    print(json.dumps(dict(event='loop', n=len(reqs), expired=expired,
                        loop_ms=round(1000*(time.perf_counter()-started), 1),
                        stock_age_s=round(time.monotonic()-state['stock_checked'], 2))), flush=True)
            except Exception as exc:
                print('loop error', type(exc).__name__, str(exc), flush=True)
                time.sleep(0.1)
            # Network round trips already consumed time; don't add a fixed .25s tax.
            time.sleep(max(0, 0.1-(time.perf_counter()-started)))
    finally:
        if journal:
            journal.close()
        if writer_lock:
            writer_lock.close()


if __name__ == '__main__':
    main()
