"""Live recommender v1: candidate generation + gradient-boosting purchase model.

    .venv/bin/python live.py --dry-run     # compute answers, measure latency, do NOT write submissions
    .venv/bin/python live.py               # LIVE: writes to TEAM_ID.submissions (only ONE writer per team!)
    .venv/bin/python live.py --takeover    # restart with no gap: warm up next to the running writer, then take its lock

pull -> predict -> push like the starter. Falls back to in-stock best sellers on any per-request error.
"""
from __future__ import annotations
import os, sys, time, json, threading, traceback, zlib, collections, gc, signal
from pathlib import Path
os.environ.setdefault('OMP_NUM_THREADS', '1')
import numpy as np, pandas as pd, requests, joblib
if __package__:
    from . import fe, qrank, aff_policy, d130, live_quality, attr_policy, lfm, home_arms, cold_lq_arm
    from .serving import Journal, WriterLock, age, repair, serve, take_over
else:
    import fe, qrank, aff_policy, d130, live_quality, attr_policy, lfm, home_arms, cold_lq_arm
    from serving import Journal, WriterLock, age, repair, serve, take_over
build_tables, featurize, FEATS = fe.build_tables, fe.featurize, fe.FEATS
DATA = Path(__file__).resolve().parent / 'data'

ENV = next((p for p in (Path(".env"), Path("../.env")) if p.exists()), None)
for line in ENV.read_text().splitlines() if ENV else []:
    k, _, v = line.partition("="); os.environ.setdefault(k.strip(), v.strip())
API = os.environ.get('RAWTREE_API_URL', 'https://api.rawtree.com').rstrip('/'); TEAM = os.environ.get("TEAM_ID", '')
transport = threading.local()
class ReadOnlySession(requests.Session):
    """Dry-run transport: the ONLY request that can leave the process is read-only SQL on /v1/query.
    Anything else (POST /v1/tables/submissions, INSERT/ALTER/... SQL) raises before touching the network."""
    def request(self, method, url, *args, **kwargs):
        body = kwargs.get('json')
        sql = str((body.get('sql') if isinstance(body, dict) else '') or '').lstrip().upper()
        if not str(url).split('?')[0].endswith('/v1/query') or not sql.startswith(('SELECT', 'WITH')):
            raise PermissionError(f'dry-run: refused {method} {str(url).split("?")[0]}')
        return super().request(method, url, *args, **kwargs)
def session():
    # requests.Session is mutable: never share one across poll/refresh/stock threads.
    if not hasattr(transport, 'http'):
        transport.http = ReadOnlySession() if DRY else requests.Session()
        transport.http.headers['Authorization'] = f"Bearer {os.environ['RAWTREE_API_KEY']}"
    return transport.http
# --dry-run or RAWTREE_DRY_RUN=1: compute everything, never write (enforced by ReadOnlySession, not only by flags).
DRY = "--dry-run" in sys.argv or os.environ.get('RAWTREE_DRY_RUN') == '1'
AB = "--ab" in sys.argv  # 50/50 by user hash: half baseline (control), half model, ONE writer
VERSION = "v1-gbm-cand-r1"
VERSION_Q = "v2-qrank-r1"
VERSION_A = "v1-aff-r1"            # GBM x description-phrase affinity (D-090)
VERSION_QA = "v2-qrank-aff-r1"     # qrank x description-phrase affinity
VERSION_L = "v3-lfm-r1"            # live-fitted model (T-018); served with a segment suffix: -k returning, -n new, +h on home
# Ranking variant for requests WITH recent views (product/category pages). Hot-switchable: the refresher re-reads
# data/policy.json every cycle, e.g. {"variant": "qrank"}.  v1 = GBM (default, unchanged behaviour) | qrank = qrank.py
# | ab_qrank = 50/50 by user hash, v1 vs qrank, so compare_versions.py can compare the two model_versions.
# D-090 adds the affinity family: aff = GBM x affinity on every page | qrank_aff = qrank x affinity on pages with
# views, GBM x affinity on home | ab_aff = 50/50 by user hash, v1 vs aff | ab_qrank_aff = 50/50, qrank vs qrank_aff.
# T-018 adds lfm = live-fitted model on every page | ab_lfm = 50/50 by user hash, qrank (control) vs lfm.
# D-170 adds the attribute ranker (attr_model) for pages with views: attr = attr_model, rest unchanged (GBM on home) |
# attr_aff = attr_model + stored-taste boost, and everything else as qrank_aff | ab_attr = 50/50, v1 vs attr |
# ab_attr_aff = 50/50, qrank_aff vs attr_aff (only the ranker of pages with views differs between arms).
VERSION_T = "v3-attr-r1"
VERSION_TA = "v3-attr-aff-r1"
VARIANTS = ("v1", "qrank", "ab_qrank", "aff", "qrank_aff", "ab_aff", "ab_qrank_aff", "attr", "attr_aff", "ab_attr", "ab_attr_aff", "lfm", "ab_lfm")
POLICY = {"variant": next((v for v in VARIANTS[1:] if "--" + v.replace("_", "-") in sys.argv), "v1"), "qrank_arms": [], "lfm_arms": []}
# T-021: tuning arms for lfm requests, read by the leaderboard per model_version ("v3-lfm-<tag>-k|-n|-kh|-nh"):
#   {"variant": "lfm", "lfm_arms": [{"tag": "r1"}, {"tag": "r2", "file": "lfm_coef_r2.json"}, {"tag": "x1", "w": {"known": {"islast": 3.0}}}]}
# An arm with only a tag is the committed weights (control). Users are split evenly by hash across 2-4 arms.
def clean_lfm_arms(raw):
    def spec(a):      # weights spec {"file": ..., "w": ...} -> cleaned dict, or None if anything is off
        if not isinstance(a, dict): return None
        f, w = a.get('file'), a.get('w') or {}
        ok = f is None or (isinstance(f, str) and f.startswith('lfm_coef') and f.endswith('.json') and '/' not in f)
        ok = ok and isinstance(w, dict) and set(w) <= {'known', 'new'} and all(
            isinstance(o, dict) and all(k in lfm.FEATS and isinstance(v, (int, float)) and abs(v) <= 20 for k, v in o.items()) for o in w.values())
        return {**({'file': f} if f else {}), **({'w': w} if w else {})} if ok else None
    arms = []
    for a in (raw or [])[:4]:
        if not isinstance(a, dict): continue
        tag, main = str(a.get('tag', '')), spec(a)
        home = spec(a['home']) if 'home' in a else None       # fused arm: other weights on home requests ({} = committed)
        lqm = a.get('lq')                                      # T-028/T-034: "cold" | "cold_new" = corrected quality for today's products
        if tag.isalnum() and len(tag) <= 8 and main is not None and ('home' not in a or home is not None) and (lqm is None or lqm in lfm.LQ_MODES):
            arms.append({'tag': tag.lower(), **main, **({'home': home} if 'home' in a else {}), **({'lq': lqm} if lqm else {})})
    # one arm alone is allowed: that is how lfm_tuner.py leaves its best weights in place without a restart
    # ...and one bad arm rejects the whole list, so a typo can never leave a lopsided split running
    arms = arms if 1 <= len(arms) == len(raw or []) and len({a['tag'] for a in arms}) == len(arms) else []
    # T-034: a "cold_new" arm must have a control in the same list with exactly its weights (file, w, home): the trial's
    # only difference is the quality of new products, and the arm's untouched traffic is served and labelled as that control
    # Promotion form (D-340): when EVERY arm is "cold_new" (one promoted arm alone, or tuner rounds built on it) there is no
    # trial of the quality itself, so no control is needed and each arm keeps its own tag for every cohort.
    if arms and all(a.get('lq') == 'cold_new' for a in arms): return arms
    return arms if all(a.get('lq') != 'cold_new' or lfm_control(a, arms) for a in arms) else []
def lfm_control(arm, arms):
    """The arm of `arms` without "lq" whose weight spec equals `arm`'s (None if there is none)."""
    spec = {k: v for k, v in arm.items() if k not in ('tag', 'lq')}
    return next((c for c in arms if 'lq' not in c and {k: v for k, v in c.items() if k != 'tag'} == spec), None)
def lfm_route(arm, new, page, rv):
    """Tag that answers (and labels) a request of a user hashed to `arm`. A "cold_new" arm only owns new shoppers on
    product/category pages with recent views; everything else is the control's, so no duplicate label is created."""
    if arm is None: return None
    if arm.get('lq') == 'cold_new' and not lfm.lq_target('cold_new', new, page, rv):
        ctl = lfm_control(arm, POLICY['lfm_arms'])
        if ctl is not None: return ctl['tag']
    return arm['tag']
def lfm_arm(user_id):
    arms = POLICY['lfm_arms']
    return arms[zlib.crc32(('lfmarm:' + user_id).encode()) % len(arms)] if arms else None
# Optional tuning arms for plain-qrank requests, measured by the leaderboard's per-model_version breakdown:
#   {"variant": "qrank", "qrank_arms": [{"tag": "vf045", "viewed_factor": 0.45}, {"tag": "vf100", "viewed_factor": 1.0}]}
# Users are split evenly by hash across the arms; each arm is written as model_version "v2-qrank-<tag>".
def clean_arms(raw):
    arms = []
    for a in (raw or [])[:4]:
        tag, vf = str(a.get('tag', '')), float(a.get('viewed_factor', 0.45))
        if tag.isalnum() and len(tag) <= 12 and 0.05 <= vf <= 3: arms.append({'tag': tag.lower(), 'viewed_factor': vf})
    return arms if len(arms) >= 2 else []
def qrank_arm(user_id):
    arms = POLICY['qrank_arms']
    return arms[zlib.crc32(('arm:' + user_id).encode()) % len(arms)] if arms else None
# Public labels: the leaderboard shows model_version to every team, so the names above never leave this process when
# data/labels.json exists (untracked, hot-reloaded): {"salt": "<any string>", "map": {"<internal label>": "<public code>"}}.
# Labels missing from the map get a stable neutral code derived from the salt. Each pairing is logged once
# ({"event": "label", ...}) so results can be decoded locally. No file -> labels are written as they are.
LABELS = {"salt": None, "map": {}, "seen": {}}
def read_labels():
    try:
        conf = json.loads((DATA / 'labels.json').read_text())
        salt, mp = str(conf.get('salt') or ''), {str(k): str(v) for k, v in (conf.get('map') or {}).items()}
        if (salt, mp) != (LABELS['salt'], LABELS['map']): LABELS.update(salt=salt, map=mp, seen={})
    except FileNotFoundError:
        if LABELS['salt'] is not None: LABELS.update(salt=None, map={}, seen={})
    except Exception as e: print('labels.json ignored', type(e).__name__, flush=True)
def public_label(version):
    if LABELS['salt'] is None: return version
    code = LABELS['seen'].get(version)
    if code is None:
        code = LABELS['map'].get(version) or 'm%05x' % (zlib.crc32((LABELS['salt'] + '|' + version).encode()) & 0xfffff)
        LABELS['seen'][version] = code; print(json.dumps(dict(event='label', internal=version, public=code)), flush=True)
    return code
def treated(user_id): return zlib.crc32(user_id.encode()) % 2 == 1      # A/B arm, stable per user
def use_aff(r):
    """Does this request get the affinity policy under the active variant? Never if aff_policy failed to load."""
    v = POLICY['variant']
    return AP is not None and (v in ('aff', 'qrank_aff', 'attr_aff', 'ab_attr_aff') or (v in ('ab_aff', 'ab_qrank_aff') and treated(r['user_id'])))
def use_lfm(r):
    """Does lfm answer this request? Needs the affinity object (AP) and a catalogue snapshot; otherwise never."""
    v = POLICY['variant']
    return LF is not None and LF.ok and AP is not None and (v == 'lfm' or (v == 'ab_lfm' and treated(r['user_id'])))
def is_new(r): return r.get('is_new_user') in (True, 1, 'true', 'True', '1')
def use_qrank(r):
    v = POLICY['variant']
    if v == 'ab_lfm': return bool(r.get('rv')) and not treated(r['user_id'])     # control arm of the lfm A/B
    return bool(r.get('rv')) and (v in ('qrank', 'qrank_aff', 'ab_qrank_aff') or (v == 'ab_qrank' and treated(r['user_id']))
                                  or (v == 'ab_attr_aff' and not treated(r['user_id'])))
def use_attr(r):
    """None, or the model_version this request gets from attr_model under the active variant. Never if it failed to load."""
    v = POLICY['variant']
    if ATP is None or not r.get('rv') or v not in ('attr', 'attr_aff', 'ab_attr', 'ab_attr_aff'): return None
    if v.startswith('ab_') and not treated(r['user_id']): return None
    return VERSION_TA if v.endswith('_aff') else VERSION_T
def read_policy():
    try:
        conf = json.loads((DATA / 'policy.json').read_text()); v = conf.get('variant')
        if v in VARIANTS and v != POLICY['variant']:
            POLICY['variant'] = v; print(json.dumps(dict(event='policy', variant=v)), flush=True)
        arms = clean_arms(conf.get('qrank_arms'))
        if arms != POLICY['qrank_arms']:
            POLICY['qrank_arms'] = arms; print(json.dumps(dict(event='policy', qrank_arms=arms)), flush=True)
        arms = clean_lfm_arms(conf.get('lfm_arms'))
        if arms != POLICY['lfm_arms'] and LF is not None:
            try: LF.set_arms(arms)                 # weights first: a request never sees an arm without its weights
            except Exception as e: print('lfm_arms ignored', type(e).__name__, e, flush=True); arms = []; LF.set_arms([])
            POLICY['lfm_arms'] = arms; print(json.dumps(dict(event='policy', lfm_arms=arms)), flush=True)
    except FileNotFoundError: pass
    except Exception as e: print('policy.json ignored', type(e).__name__, flush=True)
    read_labels()

def query(sql, timeout=20):
    r = session().post(f"{API}/v1/query", json={"sql": sql}, timeout=timeout); r.raise_for_status(); return r.json()["data"]

# ---------- state ----------
MODEL, BASE, U_ITEMS = None, None, {}
QR = None                                  # qrank.Ranker, loaded by initialize() if data/qrank.joblib exists
BOUGHT = collections.defaultdict(set)      # user -> products bought today (organic stream + our carousel feedback)
AP = None                                  # aff_policy.AffPolicy, loaded by initialize(); None -> aff variants act as v1/qrank
ATP = None                                 # attr_policy.AttrPolicy, loaded by initialize(); None -> attr variants act as v1/qrank_aff
LF = None                                  # lfm.LiveFit, loaded by initialize(); None -> lfm variants act as v1/qrank
CLQ = None                                 # cold_lq_arm.Corrector (T-028), loaded by initialize(); None -> arms with "lq" serve the incumbent quality
def initialize():
    global MODEL, BASE, U_ITEMS, QR, AP, ATP, LF, CLQ
    try: CLQ = cold_lq_arm.Corrector()
    except Exception as e: print('cold_lq_arm not loaded, lq arms serve the incumbent quality:', type(e).__name__, e, flush=True)
    try: AP = aff_policy.AffPolicy.load(DATA)
    except Exception as e: print('aff_policy not loaded, affinity variants disabled:', type(e).__name__, e, flush=True)
    try: QR = qrank.Ranker.load(DATA / 'qrank.joblib')
    except Exception as e: print('qrank not loaded, serving v1 only:', type(e).__name__, flush=True)
    try: ATP = attr_policy.AttrPolicy.load(DATA, cold=AP.cold if AP is not None else None, aff=AP.aff if AP is not None else None)
    except Exception as e: print('attr_policy not loaded, attr variants disabled:', type(e).__name__, e, flush=True)
    MODEL = joblib.load(DATA / 'model_buy.joblib')
    history = pd.read_parquet(DATA / 'user_item_all.parquet')
    BASE = build_tables(history)
    U_ITEMS = history.query('a>0 or v>=2').groupby('u').i.apply(list).to_dict()
    # D-130 hook (home_cands): inert unless data/d130.json says {"mode": "nodead"|"home"}; never blocks start-up.
    try: d130.install(globals(), history)
    except Exception as e: print('d130 not installed, serving unchanged:', type(e).__name__, e, flush=True)
    # D-180 hook (live_quality): inert unless data/lq.json says {"mode": "on"|"ab"}; only touches plain qrank slates.
    try: live_quality.install(globals())
    except Exception as e: print('live_quality not installed, serving unchanged:', type(e).__name__, e, flush=True)
    try: LF = lfm.LiveFit.load(history)
    except Exception as e: print('lfm not loaded, lfm variants disabled:', type(e).__name__, e, flush=True)
    # T-025 hook (home_arms): inert unless data/home_arms.json lists arms; only swaps slates of requests without recent_views.
    try: home_arms.install(globals())
    except Exception as e: print('home_arms not installed, serving unchanged:', type(e).__name__, e, flush=True)

state = {"live": None, "cat": None, "unavail": set(), "stock_out": set(), "stock_checked": 0,
         "pools": None, "best": None, "ev_ts": os.environ.get("EVENTS_SINCE", "2026-11-14 07:00:00"), "cycles": 0}
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

EVENT_SQL = """SELECT user_id::String u, product_id::String i, toUInt32(countIf(event_type='view')) v,
      toUInt32(countIf(event_type='add_to_cart')) a, toUInt32(countIf(event_type='purchase')) p, max(ts::DateTime64(3))::String mx
      FROM shop.events WHERE ts::DateTime64(3) > toDateTime64('{lo}',3){hi} GROUP BY u,i"""
BACKFILL_WINDOW_H = 1.0     # first refresh after start: one query per hour of stream instead of one giant response
EVENT_CHUNK = 2000          # rows applied per feature_lock hold; the serving loop gets the lock between chunks

def event_windows(lo, now, hours=BACKFILL_WINDOW_H):
    """[(lo, hi)] covering (lo, now]; the last window is open-ended (hi=None), exactly like the old single query."""
    out, a = [], pd.Timestamp(lo)
    step = pd.Timedelta(hours=hours)
    while a + step < now:
        out.append((str(a), str(a + step))); a = a + step
    out.append((str(a), None))
    return out

def apply_events(rows, chunk=EVENT_CHUNK, pause=time.sleep):
    """Apply (user, product) deltas in small lock holds. One hold for a whole start-up backfill (1.3 M rows by
    15:00 UTC on 14 Nov) kept predict() waiting ~60 s for feature_lock: every restart lost ~300 requests to it."""
    for k in range(0, len(rows), chunk):
        with feature_lock:
            for r in rows[k:k + chunk]:
                LIVE.add(r["u"], r["i"], r["v"], r["a"], r["p"])
                if r["p"]: BOUGHT[r["u"]].add(r["i"])
                if AP is not None: AP.add(r["u"], r["i"], r["v"])
                if LF is not None: LF.add(r["u"], r["i"], r["v"], r["a"], r["p"])
        if k + chunk < len(rows): pause(0.002)      # threading.Lock is not fair: yield so a waiting predict() gets in

def fb_window():
    """Our own carousel purchases never reach shop.events, so after a (re)start the first read takes ALL of them (a
    shopper who bought through us is much less likely to buy the product again: organizer note, 14 Nov). Later reads
    take the last 10 minutes, which also covers a slow refresh cycle."""
    return " AND f.ts::DateTime64(3) > now() - INTERVAL 10 MINUTE" if state.get("fb_full") else ""

def refresh_events():
    now = pd.Timestamp.now("UTC").tz_localize(None)
    for lo, hi in event_windows(state["ev_ts"], now):
        rows = query(EVENT_SQL.format(lo=lo, hi=f" AND ts::DateTime64(3) <= toDateTime64('{hi}',3)" if hi else ""), timeout=60)
        apply_events(rows)
        gc.freeze()      # these objects live until the process ends: keep them out of every later full collection (see settle_gc)
        if hi: state["ev_ts"] = hi
        elif rows: state["ev_ts"] = max(r["mx"] for r in rows)
    try:  # our own carousel purchases: shopper won't want them again
        fb = query(f"SELECT r.user_id::String u, f.purchased::String i FROM {TEAM}.feedback f INNER JOIN shop.requests r ON r.request_id::String=f.request_id::String WHERE f.purchased::String != ''" + fb_window())
        state["fb_full"] = True
        for r in fb:
            if r["i"] not in fb_seen.setdefault(r["u"], set()):
                fb_seen[r["u"]].add(r["i"])
                with feature_lock:
                    LIVE.add(r["u"], r["i"], 0, 0, 1); BOUGHT[r["u"]].add(r["i"])
                    if LF is not None: LF.add(r["u"], r["i"], 0, 0, 1)
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
        self._cat, self._sk = None, {}
    def add(self, u, i, v, a, p):
        c = fe.C
        if c is not self._cat:      # new catalogue object (every refresh): product -> (sub, category) as a plain dict
            self._sk = dict(zip(c.index, zip(c["sub"], c["category"]))); self._cat = c
        sk = self._sk.get(i)
        if sk is None: return
        s, k = sk
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

COLD_LOG = {}
def cold_lq_for_arms(cat, T):
    """T-028: {product: corrected lq} for lfm arms with "lq": "cold"; None when no arm asks, when the corrector is not
    ready or on any error, and then those arms serve exactly the incumbent quality. Refresher thread only: no query."""
    try:
        if CLQ is None or QR is None or not LF.alt_lq or not CLQ.ready: return None
        out = CLQ.corrections(QR.q, QR.lq, cat, BASE["item"], T.item_frame(), AP.cold.desc, lq0=LF.lq0)
        if CLQ.last != COLD_LOG.get('last'):
            COLD_LOG['last'] = dict(CLQ.last); print(json.dumps(dict(event='cold_lq', **CLQ.last)), flush=True)
        return out or None
    except Exception as e:
        print('cold_lq for arms failed', type(e).__name__, e, flush=True); return None

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
            if ATP is not None:
                try: ATP.refresh(query, cat, unavail, T.item_frame(), sync=AP is None)
                except Exception as e: print('attr refresh failed', type(e).__name__, e, flush=True)
            if LF is not None and AP is not None:
                try: LF.set_catalog(cat, unavail, AP.aff, QR.lq if QR is not None else None, d130.HC, lq_cold=cold_lq_for_arms(cat, T))
                except Exception as e: print('lfm refresh failed', type(e).__name__, e, flush=True)
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
    quick.update(attr_slates(reqs, unavail, qver))   # D-170: requests answered by attr_model (disjoint from qrank's by variant)
    quick.update(lfm_slates(reqs, unavail, qver))   # requests answered by the live-fitted model (never overlaps qrank)
    aff = {k for k, r in enumerate(reqs) if k not in quick and use_aff(r)}   # GBM requests that get the affinity policy
    cold = AP.cold_tables if (AP is not None and POLICY['variant'] in ('aff', 'qrank_aff', 'attr_aff', 'ab_attr_aff')) else None   # new-product pseudo-counts
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

def lfm_slates(reqs, unavail, versions):
    """Slates from lfm for the requests the active variant routes to it. Any failure -> that request keeps the old path."""
    out = {}
    try:
        idx = [k for k, r in enumerate(reqs) if use_lfm(r)]
        if not idx: return out
        with feature_lock: states = [LF.user_state(reqs[k]['user_id']) for k in idx]
        for k, st in zip(idx, states):
            r = reqs[k]; new = is_new(r); tag = lfm_route(lfm_arm(r['user_id']), new, r.get('page', 'product'), r['rv'])
            req = dict(user_id=r['user_id'], rv=r['rv'], page=r.get('page', 'product'), is_new_user=new, device=r.get('device'), region=r.get('region'))
            try: s = LF.slate(req, st, AP.aff, exclude=unavail, model=tag)
            except Exception as e:
                print('lfm slate error', type(e).__name__, e, flush=True); s = None
            if s is None and tag is not None:      # a broken arm must not cost the request its lfm slate
                try: s = LF.slate(req, st, AP.aff, exclude=unavail); tag = None
                except Exception: s = None
            if s is not None:
                out[k] = s; versions[k] = (VERSION_L if tag is None else 'v3-lfm-' + tag) + ('-n' if new else '-k') + ('h' if not r['rv'] else '')
    except Exception as e:
        print('lfm error', type(e).__name__, e, flush=True)
    return out

def qrank_slates(reqs, unavail, versions=None):
    """Slates from qrank for the requests the active variant routes to it. Any failure -> {} (GBM path).
    `versions` (optional dict) receives index -> VERSION_QA for the slates re-ranked with affinity."""
    if QR is None or not QR.ok: return {}
    try:
        idx = [k for k, r in enumerate(reqs) if use_qrank(r) and not use_lfm(r)]
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
        groups = {}                                                   # tuning arm -> request positions (None = default)
        for j in todo:
            arm = qrank_arm(qreqs[j]['user_id'])
            groups.setdefault(arm['tag'] if arm else None, (arm, []))[1].append(j)
        for tag, (arm, js) in groups.items():
            for j, s in zip(js, QR.slates([qreqs[j] for j in js], viewed_factor=arm['viewed_factor'] if arm else None)):
                if s is not None and len(set(s)) == 10:
                    out[idx[j]] = s
                    if arm and versions is not None: versions[idx[j]] = 'v2-qrank-' + tag
        return out
    except Exception as e:
        print('qrank error', type(e).__name__, e, flush=True); return {}

def attr_slates(reqs, unavail, versions):
    """Slates from attr_model for the requests the active variant routes to it. Any failure -> {} (qrank/GBM path)."""
    if ATP is None or not ATP.ok: return {}
    try:
        ver = {k: v for k, v in ((k, use_attr(r)) for k, r in enumerate(reqs)) if v}
        if not ver: return {}
        idx = list(ver)
        with feature_lock: bought = [set(BOUGHT.get(reqs[k]['user_id'], ())) for k in idx]
        res = ATP.slates([{"user_id": reqs[k]['user_id'], "rv": reqs[k]['rv'], "page": reqs[k].get('page', 'product'), "bought": b | unavail}
                          for k, b in zip(idx, bought)], history=[ver[k] == VERSION_TA for k in idx])
        out = {k: s for k, s in zip(idx, res) if s is not None and len(set(s)) == 10}
        versions.update({k: ver[k] for k in out})
        return out
    except Exception as e:
        print('attr error', type(e).__name__, e, flush=True); return {}

def fallback_answers(reqs, version=None):
    _, unavail, _, _, best = snapshot()
    items = [p for p in best if p not in unavail][:10]
    return [{"request_id": r["request_id"], "items": items, "model_version": version or VERSION + "-guard"} for r in reqs]

def pull(seen):
    rows = query("SELECT request_id::String request_id, ts::String ts, user_id::String user_id, is_new_user, context.page::String page, context.device::String device, context.region::String region, toJSONString(recent_views) rv FROM shop.requests ORDER BY ts DESC LIMIT 60", timeout=(0.5, 2.0))
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

def post_batch(batch, remaining):
    """The ONE place that writes to submissions (tools/handoff_rehearsal.py swaps it for a recorder)."""
    response = session().post(f'{API}/v1/tables/submissions', params={'database': TEAM},
        json=batch, timeout=(min(0.3, remaining/2), max(0.05, remaining-0.3)))
    response.raise_for_status()

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
        answer = dict(request_id=rid, items=items, model_version=public_label(version))
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
        post_batch(batch, remaining)
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


STOP = threading.Event()          # set by SIGINT/SIGTERM: finish the current loop, release the lock, exit
def request_stop(signum=None, frame=None): STOP.set()

def arg_value(name, default=None, argv=None):
    argv = sys.argv if argv is None else argv
    return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else default

def settle_gc():
    """Move everything loaded so far out of the collector's reach. The process holds tens of millions of long-lived
    objects (history + today's stream); a full collection walks all of them with the GIL held and freezes every
    thread, the serving loop included. Frozen objects are skipped, so later full collections only see new garbage."""
    t = time.perf_counter(); gc.collect()
    print(json.dumps(dict(event='gc_settle', full_collection_ms=round(1000 * (time.perf_counter() - t), 1))), flush=True)
    gc.freeze()

_gc_started = [0.0]
def gc_watch(phase, info):
    """Log every collection that held the GIL for more than 200 ms (all threads are frozen meanwhile)."""
    if phase == 'start': _gc_started[0] = time.perf_counter()
    else:
        ms = 1000 * (time.perf_counter() - _gc_started[0])
        if ms > 200: print(json.dumps(dict(event='gc_pause', generation=info.get('generation'), ms=round(ms, 1))), flush=True)

def warm_up(seconds=8.0, pause=0.25):
    """Score real requests WITHOUT sending anything (takeover: the old writer is still answering them)."""
    seen, n, worst, end = set(), 0, 0.0, time.monotonic() + seconds
    while time.monotonic() < end and not STOP.is_set():
        try:
            reqs = [r for r in pull(seen) if age(r) <= 2.5][:8]
            seen.update(r['request_id'] for r in reqs)
            if reqs:
                t = time.perf_counter(); predict(reqs)
                n += len(reqs); worst = max(worst, time.perf_counter() - t)
        except Exception as exc: print('warm-up error', type(exc).__name__, str(exc), flush=True)
        time.sleep(pause)
    print(json.dumps(dict(event='warm_up', scored=n, worst_batch_ms=round(1000 * worst, 1))), flush=True)

def main():
    import tempfile
    directory = Path(os.environ.get('RAWTREE_LOCK_DIR') or Path(tempfile.gettempdir()) / ('rawtree-' + TEAM))
    lock_path = directory / 'writer.lock'
    # --takeover: load and warm up NEXT TO the running writer, then ask it to stop and start writing the moment the
    # OS hands the lock over. This process never writes without the lock, so there are never two writers.
    takeover = '--takeover' in sys.argv and not DRY
    old_pid = int(arg_value('--replace-pid', 0)) or None      # only for an old writer that left no pid file
    writer_lock = None if DRY or takeover else WriterLock(lock_path)
    journal = None
    try:
        signal.signal(signal.SIGINT, request_stop); signal.signal(signal.SIGTERM, request_stop)
        gc.callbacks.append(gc_watch)
        initialize()
        threading.Thread(target=refresher, daemon=True).start()
        threading.Thread(target=stock_refresher, daemon=True).start()
        while state['pools'] is None and not STOP.is_set():
            time.sleep(0.1)
        if takeover:
            while (state['live'] is None or not state['stock_checked']) and not STOP.is_set():
                time.sleep(0.1)              # first full refresh done: today's stream is applied, every model is live
            warm_up()
            settle_gc()
            if STOP.is_set(): return
            writer_lock = take_over(lock_path, old_pid)
        else:
            settle_gc()
        if not DRY:
            journal = Journal(directory / 'attempts.sqlite3')
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
        while not STOP.is_set():
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
        print(json.dumps(dict(event='stopped', reason='signal')), flush=True)
    finally:
        if journal:
            journal.close()
        if writer_lock:
            writer_lock.close()


if __name__ == '__main__':
    main()
