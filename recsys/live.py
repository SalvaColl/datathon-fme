"""Live recommender v1: candidate generation + gradient-boosting purchase model.

    .venv/bin/python live.py --dry-run     # compute answers, measure latency, do NOT write submissions
    .venv/bin/python live.py               # LIVE: writes to TEAM_ID.submissions (only ONE writer per team!)
    .venv/bin/python live.py --takeover    # restart with no gap: warm up next to the running writer, then take its lock

pull -> predict -> push like the starter. Falls back to in-stock best sellers on any per-request error.
"""
from __future__ import annotations
import os, sys, time, json, threading, traceback, zlib, collections, gc, signal, copy, math
from pathlib import Path
os.environ.setdefault('OMP_NUM_THREADS', '1')
import numpy as np, pandas as pd, requests, joblib
if __package__:
    from . import fe, qrank, aff_policy, d130, live_quality, attr_policy, lfm, home_arms, cold_lq_arm, trends
    from .serving import Journal, WriterLock, age, repair, serve, take_over
else:
    import fe, qrank, aff_policy, d130, live_quality, attr_policy, lfm, home_arms, cold_lq_arm, trends
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
def urgent_age(raw=None, default=2.2):
    """Age (s) from which a request gets the generic guard list instead of the model (T-043). It was 1.8 s, set when
    inference took hundreds of ms; lfm takes ~5 ms, and since 14 Nov 20:30 UTC the POST is ~75 ms slower, so 3% of the
    requests were crossing 1.8 s and getting the guard list (0.7% conversion against ~1.9%). 2.2 s still leaves room
    for a slow inference (0.3 s) plus a p95 POST (0.47 s) inside the 3 s deadline. URGENT_AGE overrides; clamped to
    1.5-2.4 so a typo can neither starve the model nor push answers past serving.py's max_age (2.5 s)."""
    try: v = float(raw) if raw not in (None, '') else default
    except (TypeError, ValueError): v = default
    return min(2.4, max(1.5, v))
URGENT_AGE = urgent_age(os.environ.get('URGENT_AGE'))
def connect_retry_age(raw=None, default=2.0):
    """T-047: oldest request age (s) up to which a batch whose POST failed with ConnectTimeout gets its ONE retry.
    0 disables the retry (CONNECT_RETRY_AGE=0). Clamped to 0-2.2: beyond that a normal POST (p99 0.52 s on 14 Nov)
    plus the connect allowance no longer fits inside the 3 s deadline."""
    try: v = float(raw) if raw not in (None, '') else default
    except (TypeError, ValueError): v = default
    return min(2.2, max(0.0, v)) if math.isfinite(v) else default
CONNECT_RETRY_AGE = connect_retry_age(os.environ.get('CONNECT_RETRY_AGE'))
def never_sent(exc):
    """True only for requests' ConnectTimeout: the TCP/TLS connection was never established, so no byte of the request
    left this process and the server cannot have accepted it (requests documents it as safe to retry). ReadTimeout,
    the Timeout base class, ConnectionError (resets, refused, DNS, proxy, TLS errors: some of them can happen after the
    body was written), HTTP errors and anything unknown stay ambiguous."""
    return isinstance(exc, requests.exceptions.ConnectTimeout)
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
POLICY = {"variant": next((v for v in VARIANTS[1:] if "--" + v.replace("_", "-") in sys.argv), "v1"), "qrank_arms": [], "lfm_arms": [], "state_window": None, "prior_purchases": None}
# T-036: day / phase window of the lfm shopper state, e.g. {"state_window": {"day_start": "2026-11-15 00:00:00", "carts": "persistent"}}.
# Absent or invalid = no day window (everything since EVENTS_SINCE counts as today). Purchases stay excluded either way.
def clean_state_window(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get('day_start'), str) or set(raw) - {'day_start', 'carts'}: return None
    w = {'day_start': raw['day_start'], 'carts': raw.get('carts', 'persistent')}
    try: lfm.LiveFit({k: dict(w={}, b=0.0) for k in ('known', 'new')}).set_window(**w)
    except Exception: return None
    return w
# T-063: {"prior_purchases": {"boundary": "2026-11-15 09:00:00", "mode": "exclude" | "allow"}}. Live purchases before the
# boundary: "exclude" keeps them out (as always) and only counts them in the shadow diagnosis; "allow" lets them back in.
# Absent or null = no boundary, behaviour before T-063. Hot-reloadable; nothing is erased in either direction.
def clean_prior_purchases(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get('boundary'), str) or set(raw) - {'boundary', 'mode'}: return None
    w = {'boundary': raw['boundary'], 'mode': raw.get('mode', 'exclude')}
    try: lfm.LiveFit({k: dict(w={}, b=0.0) for k in ('known', 'new')}).set_prior(**w)
    except Exception: return None
    return w
# T-021: tuning arms for lfm requests, read by the leaderboard per model_version ("v3-lfm-<tag>-k|-n|-kh|-nh"):
#   {"variant": "lfm", "lfm_arms": [{"tag": "r1"}, {"tag": "r2", "file": "lfm_coef_r2.json"}, {"tag": "x1", "w": {"known": {"islast": 3.0}}}]}
# An arm with only a tag is the committed weights (control). Users are split evenly by hash across 2-4 arms.
def clean_newcap(c):
    """T-061 arm key "newcap": {"known" | "new" | "home_known" | "home_new": 0..10}, the most launched products a list
    of that segment may carry (lfm.cap_launched). A bare integer is the same cap for the four segments. Returns the
    dict form ({} = no cap), or None if anything is off."""
    if isinstance(c, int) and not isinstance(c, bool): c = {k: c for k in lfm.CAP_KEYS}
    if not isinstance(c, dict) or not set(c) <= set(lfm.CAP_KEYS): return None
    if not all(isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 10 for v in c.values()): return None
    return {k: c[k] for k in lfm.CAP_KEYS if k in c}
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
        lqm = a.get('lq')                                      # T-028/T-034/T-047: "cold" | "cold_new" | "cold_known" = corrected quality for today's products
        xp = a.get('explore')                                  # T-039: true = exploration arm (last slot from ranks 11..60); "new" / "known" = only for that kind of shopper
        rc = a.get('recart')                                   # T-046: true = re-cart bonus (LiveFit.set_arms); anything else but absent rejects the list
        cap = clean_newcap(a['newcap']) if 'newcap' in a else None   # T-061: max launched products per list, by segment; a bad one rejects the list
        if tag.isalnum() and len(tag) <= 8 and main is not None and ('home' not in a or home is not None) and (lqm is None or lqm in lfm.LQ_MODES) and (xp is None or xp is True or xp in lfm.X_MODES) and (rc is None or rc is True) and ('newcap' not in a or cap is not None):
            arms.append({'tag': tag.lower(), **main, **({'home': home} if 'home' in a else {}), **({'lq': lqm} if lqm else {}), **({'explore': xp} if xp else {}), **({'recart': True} if rc else {}), **({'newcap': cap} if cap else {})})
    # one arm alone is allowed: that is how lfm_tuner.py leaves its best weights in place without a restart
    # ...and one bad arm rejects the whole list, so a typo can never leave a lopsided split running
    arms = arms if 1 <= len(arms) == len(raw or []) and len({a['tag'] for a in arms}) == len(arms) else []
    # T-034: a "cold_new" arm must have a control in the same list with exactly its weights (file, w, home): the trial's
    # only difference is the quality of new products, and the arm's untouched traffic is served and labelled as that control
    # Promotion form (D-340): when EVERY arm is "cold_new" (one promoted arm alone, or tuner rounds built on it) there is no
    # trial of the quality itself, so no control is needed and each arm keeps its own tag for every cohort.
    # T-047: "cold_known" (returning shoppers only) follows the same two rules; the two selective modes are never mixed
    # in a promotion form (every arm must carry the SAME mode).
    if arms and any(all(a.get('lq') == m for a in arms) for m in lfm.LQ_COHORT): return arms
    return arms if all(a.get('lq') not in lfm.LQ_COHORT or lfm_control(a, arms) for a in arms) else []
def lfm_control(arm, arms):
    """The arm of `arms` without "lq" whose weight spec equals `arm`'s (None if there is none)."""
    spec = {k: v for k, v in arm.items() if k not in ('tag', 'lq')}
    return next((c for c in arms if 'lq' not in c and {k: v for k, v in c.items() if k != 'tag'} == spec), None)
def lfm_route(arm, new, page, rv):
    """Tag that answers (and labels) a request of a user hashed to `arm`. A "cold_new" arm only owns new shoppers on
    product/category pages with recent views ("cold_known", T-047: returning shoppers on those pages); everything else
    is the control's, so no duplicate label is created. Same rule as the scoring: lfm.lq_target."""
    if arm is None: return None
    if arm.get('lq') in lfm.LQ_COHORT and not lfm.lq_target(arm['lq'], new, page, rv):
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
class PolicyRejected(ValueError): pass
POLICY_REJECTED = {'sig': None, 'n': 0}      # last rejected candidate (logged once per distinct content and reason)
def lfm_arm_weights(arms):
    """Weights of `arms` built on a scratch copy of LF (nothing is published), checked: every weight file present and
    complete, every coefficient a finite number. Returns what publish_policy() installs. Raises on any problem."""
    tmp = copy.copy(LF); tmp.set_arms(arms)
    for tag, (w, b) in tmp.alt.items():
        for seg in ('known', 'new'):
            if not (np.all(np.isfinite(np.asarray(w[seg], dtype=float))) and math.isfinite(b[seg])):
                raise PolicyRejected('non-finite coefficient in arm ' + tag)
    return tmp.alt, tmp.alt_lq, tmp.alt_x, tmp.alt_cap
def check_policy(conf):
    """T-043: the whole candidate policy.json, validated BEFORE anything is published. Returns the new values of the
    keys that change ({} = nothing to do); raises PolicyRejected and touches nothing if any part is wrong. A key that
    is absent, null or empty keeps its old meaning (no arms, no window, same variant): that is the documented rollback.
    A key that is present and wrong rejects the update as a whole, so a typo or a missing weight file can no longer
    erase the arms or switch the variant half-way."""
    if not isinstance(conf, dict): raise PolicyRejected('not an object')
    new = {}
    v = conf.get('variant')
    if v is not None and v not in VARIANTS: raise PolicyRejected('unknown variant')
    if v is not None and v != POLICY['variant']: new['variant'] = v
    raw = conf.get('qrank_arms')
    try: arms = clean_arms(raw) if raw else []
    except Exception: arms = None
    if arms is None or (raw and not arms): raise PolicyRejected('invalid qrank_arms')
    if arms != POLICY['qrank_arms']: new['qrank_arms'] = arms
    raw = conf.get('lfm_arms')
    try: arms = clean_lfm_arms(raw) if raw else []
    except Exception: arms = None
    if arms is None or (raw and not arms): raise PolicyRejected('invalid lfm_arms')
    if arms != POLICY['lfm_arms'] and LF is not None:
        try: new['lfm_weights'] = lfm_arm_weights(arms)
        except PolicyRejected: raise
        except Exception as e: raise PolicyRejected('lfm weights: ' + type(e).__name__ + ' ' + str(e)[:120])
        new['lfm_arms'] = arms
    raw = conf.get('state_window')
    win = clean_state_window(raw) if raw is not None else None
    if raw is not None and win is None: raise PolicyRejected('invalid state_window')
    if win != POLICY['state_window'] and LF is not None: new['state_window'] = win
    raw = conf.get('prior_purchases')
    pri = clean_prior_purchases(raw) if raw is not None else None
    if raw is not None and pri is None: raise PolicyRejected('invalid prior_purchases')
    if pri != POLICY['prior_purchases'] and LF is not None: new['prior_purchases'] = pri
    return new
def publish_policy(new):
    """Install a candidate that check_policy() accepted. Weights first (a request never sees an arm without its
    weights), then the routing keys in one dict update."""
    if 'lfm_weights' in new: LF.alt, LF.alt_lq, LF.alt_x, LF.alt_cap = new.pop('lfm_weights')
    if 'state_window' in new: LF.set_window(**(new['state_window'] or {}))
    if 'prior_purchases' in new: prior_report(final=True); LF.set_prior(**(new['prior_purchases'] or {}))
    POLICY.update(new)
    for k in ('variant', 'qrank_arms', 'lfm_arms', 'state_window', 'prior_purchases'):
        if k in new: print(json.dumps({'event': 'policy', k: new[k]}), flush=True)
PRIOR_LOG = {'t': 0.0}
def prior_report(final=False, every=300.0):
    """T-063: one log line with the shadow counters of the prior purchases, at most every five minutes (and once more,
    with final=True, just before the configuration changes). Silent without a boundary. Never raises."""
    try:
        lf = LF
        if lf is None or lf.prior_start is None: return
        now = time.monotonic()
        if not final and now - PRIOR_LOG['t'] < every: return
        PRIOR_LOG['t'] = now
        print(json.dumps(dict(event='prior_purchases', boundary=lf.prior_start, mode='allow' if lf.prior_allow else 'exclude',
                              final=final, **dict(lf.prior_stats))), flush=True)
    except Exception: pass
def read_policy():
    try:
        text = (DATA / 'policy.json').read_text()
        try: new = check_policy(json.loads(text))
        except Exception as e:                    # truncated JSON, wrong config, missing / incomplete / non-finite weights
            sig = (text, type(e).__name__, str(e))
            if sig != POLICY_REJECTED['sig']:
                POLICY_REJECTED.update(sig=sig, n=POLICY_REJECTED['n'] + 1)
                print(json.dumps(dict(event='policy_rejected', error=type(e).__name__, reason=str(e)[:200],
                                      kept=dict(variant=POLICY['variant'], lfm_arms=[a['tag'] for a in POLICY['lfm_arms']]))), flush=True)
        else:
            if POLICY_REJECTED['sig'] is not None:
                POLICY_REJECTED['sig'] = None; print(json.dumps(dict(event='policy_recovered')), flush=True)
            if new: publish_policy(new)
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
    # T-054: views of earlier requests over the last 30 days (download_prev_views.py). Absent file = event requests only.
    try:
        if LF is not None and (DATA / 'prev_views.parquet').exists():
            print('prev views history:', LF.load_prev_hist(pd.read_parquet(DATA / 'prev_views.parquet')), 'users', flush=True)
    except Exception as e: print('prev views history not loaded:', type(e).__name__, e, flush=True)
    # T-055: products bought / clicked in the history carousel (download_prev_views.py). Absent file = features stay 0.
    try:
        if LF is not None and (DATA / 'hist_carousel.parquet').exists():
            print('history carousel:', LF.load_hist_carousel(pd.read_parquet(DATA / 'hist_carousel.parquet')), 'users', flush=True)
    except Exception as e: print('history carousel not loaded:', type(e).__name__, e, flush=True)
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
      toUInt32(countIf(event_type='add_to_cart')) a, toUInt32(countIf(event_type='purchase')) p, max(ts::DateTime64(3))::String mx,
      maxIf(ts::DateTime64(3), event_type='add_to_cart')::String ta, maxIf(ts::DateTime64(3), event_type='purchase')::String tp
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
                LIVE.add_organic(r["i"], r["v"], r["a"], r["p"])      # T-047: shop.events is the only organic source
                if r["p"]: BOUGHT[r["u"]].add(r["i"])
                if AP is not None: AP.add(r["u"], r["i"], r["v"])
                if LF is not None: LF.add(r["u"], r["i"], r["v"], r["a"], r["p"], r.get("ta"), r.get("tp"))
        if k + chunk < len(rows): pause(0.002)      # threading.Lock is not fair: yield so a waiting predict() gets in

PRV_SINCE = os.environ.get("PRV_SINCE", "2026-11-14 07:00:00")      # start of the event's requests; NOT tied to EVENTS_SINCE
PRV_SQL = """SELECT request_id::String rid, user_id::String u, ts::DateTime64(3)::String t, toJSONString(recent_views) rv
      FROM shop.requests WHERE ts::DateTime64(3) > toDateTime64('{lo}',3){hi}"""
PRV_OVERLAP_S = 5       # each incremental read goes back this far (rows can land late); request ids seen there are skipped

def refresh_prev_views():
    """T-054: feed LF with the recent views of every request of the event. They never appear in shop.events, so this is
    the only source. First call = backfill by the hour (the store is rebuilt from RawTree at every start, nothing to
    persist); later calls read from the watermark. Never raises; without it the `prv` feature is simply 0."""
    if LF is None: return
    try:
        now = pd.Timestamp.now("UTC").tz_localize(None)
        seen = state.setdefault("prv_seen", {})
        for lo, hi in event_windows(state.setdefault("prv_ts", PRV_SINCE), now):
            rows = query(PRV_SQL.format(lo=lo, hi=f" AND ts::DateTime64(3) <= toDateTime64('{hi}',3)" if hi else ""), timeout=60)
            mx = max((r["t"] for r in rows), default=None)
            for k in range(0, len(rows), 500):
                for r in rows[k:k + 500]:
                    if r["rid"] in seen or not r.get("rv") or r["rv"] == "[]": continue
                    try: rv = [x["product_id"] for x in json.loads(r["rv"]) if isinstance(x, dict) and x.get("product_id")]
                    except (ValueError, TypeError): continue
                    LF.add_request(r["u"], r["rid"], rv)
                if k + 500 < len(rows): time.sleep(0.002)          # let the serving loop run between chunks
            if hi: state["prv_ts"] = hi
            elif mx:
                wm = str(pd.Timestamp(mx) - pd.Timedelta(seconds=PRV_OVERLAP_S))[:23]
                state["prv_seen"] = seen = {r["rid"]: 1 for r in rows if r["t"] > wm} | {k: 1 for k in list(seen)[-2000:]}
                state["prv_ts"] = max(wm, lo)
    except Exception as e: print('prev views refresh failed', type(e).__name__, e, flush=True)

FB_OVERLAP_S = 600      # every incremental feedback read goes back this far from the last successful one (late rows)

def utcnow(): return pd.Timestamp.now("UTC").tz_localize(None)

def fb_window(hi=None):
    """Our own carousel purchases never reach shop.events, so after a (re)start the first read takes ALL of them (a
    shopper who bought through us is much less likely to buy the product again: organizer note, 14 Nov). Later reads
    start at the upper bound of the last read that was fetched AND applied (state["fb_ts"]) minus FB_OVERLAP_S: a
    reader outage of any length is read again from where it began, instead of losing everything older than 10 minutes.
    The old `now() - 10 min` bound stays as an OR, so a read never covers less than it did (also with a skewed local
    clock). Rows that land more than FB_OVERLAP_S after their own ts are only recovered by the next start."""
    up = f" AND f.ts::DateTime64(3) <= toDateTime64('{hi}',3)" if hi else ""
    wm = state.get("fb_ts")
    if not wm: return up
    lo = str(pd.Timestamp(wm) - pd.Timedelta(seconds=FB_OVERLAP_S))[:23]
    return f" AND (f.ts::DateTime64(3) > toDateTime64('{lo}',3) OR f.ts::DateTime64(3) > now() - INTERVAL 10 MINUTE)" + up

def refresh_events():
    now = utcnow()
    for lo, hi in event_windows(state["ev_ts"], now):
        rows = query(EVENT_SQL.format(lo=lo, hi=f" AND ts::DateTime64(3) <= toDateTime64('{hi}',3)" if hi else ""), timeout=60)
        apply_events(rows)
        gc.freeze()      # these objects live until the process ends: keep them out of every later full collection (see settle_gc)
        if hi: state["ev_ts"] = hi
        elif rows: state["ev_ts"] = max(r["mx"] for r in rows)
    try:  # our own carousel purchases: shopper won't want them again
        fb = query(f"SELECT r.user_id::String u, f.purchased::String i, f.ts::DateTime64(3)::String t FROM {TEAM}.feedback f INNER JOIN shop.requests r ON r.request_id::String=f.request_id::String WHERE f.purchased::String != ''" + fb_window(fb_hi := str(utcnow())[:23]))
        for r in fb:
            if r["i"] not in fb_seen.setdefault(r["u"], set()):
                fb_seen[r["u"]].add(r["i"])
                with feature_lock:
                    # T-047: a carousel purchase is user state and an exclusion, NOT an organic purchase: it goes to
                    # LIVE.add only, never to LIVE.add_organic (its carousel impressions are in nobody's view counts).
                    LIVE.add(r["u"], r["i"], 0, 0, 1); BOUGHT[r["u"]].add(r["i"])
                    if LF is not None: LF.add(r["u"], r["i"], 0, 0, 1, tp=r.get("t"))
        state["fb_ts"] = fb_hi      # only here: fetched and applied (an empty answer counts); a failure keeps the old mark
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
        # T-047: organic-only product counts (views, carts, purchases of shop.events). "item" above also receives the
        # purchases of our own carousel (refresh_events), whose impressions are not views: a purchases/view rate must
        # be computed from this accumulator. Not a dict entry on purpose: fe.featurize and the tables' consumers
        # never see it. Rebuilt from the stream on every start, like "item"; never touched by the feedback read.
        self.organic = _Lookup(["it_v", "it_a", "it_p"])
    def _place(self, i):
        c = fe.C
        if c is not self._cat:      # new catalogue object (every refresh): product -> (sub, category) as a plain dict
            self._sk = dict(zip(c.index, zip(c["sub"], c["category"]))); self._cat = c
        return self._sk.get(i)
    def add_organic(self, i, v, a, p):
        """Product counts from shop.events do not need category metadata. A launch can arrive after refresh_catalog()
        but before refresh_events(); dropping it here would lose its counts permanently when ev_ts advances. Retain
        those counts now; snapshots still control product existence/stock before any recommendation can include it.
        Carousel purchases never call this method. Per-user category tables keep their separate metadata gate."""
        self.organic.add(i, (v, a, p))
    def organic_item_frame(self):
        """Per-product ORGANIC counts so far (it_v, it_a, it_p), or None: the input of every quality / rate estimate."""
        d = self.organic.d
        return pd.DataFrame.from_dict(d, orient="index", columns=self.organic.cols) if d else None
    def add(self, u, i, v, a, p):
        sk = self._place(i)
        if sk is None: return
        s, k = sk
        self["item"].add(i, (v, a, p)); self["uit"].add((u, i), (v, a, p)); self["usub"].add((u, s), (v, p))
        self["ucat"].add((u, k), (v, p)); self["utot"].add(u, (v, p))
    def item_frame(self):
        """Per-product counts of everything we know: organic stream PLUS purchases of our own carousel (it_p). For
        popularity lists and model features; for a purchases/view rate use organic_item_frame() (T-047)."""
        d = self["item"].d
        return pd.DataFrame.from_dict(d, orient="index", columns=self["item"].cols) if d else None

LIVE = LiveTables(); fb_seen = {}

def organic_frame(T):
    """T-047: the organic-only product counts of `T` (LiveTables). An object without them (older test doubles) gives its
    item_frame(), which is what every caller received before."""
    f = getattr(T, 'organic_item_frame', None)
    return f() if f is not None else T.item_frame()

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

def new_products(cat, max_share=0.25):
    """T-039: products launched during the event = in the live catalogue without a 60-day quality (QR.q). None (the lfm
    feature `newp` stays 0, every arm serves as before) when qrank is not loaded or the set looks wrong (over 25%)."""
    try:
        if QR is None or not QR.q: return None
        new = set(cat.index) - set(QR.q)
        return new if 0 < len(new) <= max_share * len(cat) else None
    except Exception as e:
        print('new_products failed', type(e).__name__, e, flush=True); return None

OQ_HIST = {}
def organic_counts(T):
    """T-049: ({product: (organic views, organic purchases)} over the 60-day history plus today, products with history) for
    the lfm features `orate` / `opop`. (None, None) (the features stay 0, every arm serves as before) when no arm weights
    them or on any error. Today's part is the organic-only accumulator (T-047): never purchases made through our carousel.
    Refresher thread only: no query."""
    try:
        if LF is None or not LF.wants_oq(): return None, None
        if not OQ_HIST:
            b = BASE["item"]; OQ_HIST.update(zip(b.index, zip(b["it_v"].values.astype(float), b["it_p"].values.astype(float))))
        out = dict(OQ_HIST)
        li = organic_frame(T) if T is not None else None
        if li is not None and len(li):
            for i, v, p in zip(li.index, li["it_v"].values, li["it_p"].values):
                h = out.get(i); out[i] = (float(v) + h[0], float(p) + h[1]) if h else (float(v), float(p))
        return out, set(OQ_HIST)
    except Exception as e:
        print('organic_counts failed', type(e).__name__, e, flush=True); return None, None

HOT_LOG = {}
def hot_products(cat, max_share=0.10):
    """T-044: products of the subcategories in a live burst (trends.py: share of views of the last 15 minutes at least twice
    the usual one), for lfm arms that weight the feature `hot`. None (the feature stays 0, every arm serves as before) when
    no arm asks, when nothing is hot, when the set looks wrong (over 10% of the catalogue) or on any error. Refresher thread
    only; one aggregate query per cycle, and only while an arm asks."""
    try:
        if LF is None or not LF.wants_hot(): return None
        snap = trends.snapshot(query, cat["sub"].to_dict())
        if snap.hot != HOT_LOG.get('hot'):
            HOT_LOG['hot'] = list(snap.hot); print(json.dumps(dict(event='hot', subcategories=snap.hot)), flush=True)
        if not snap.hot: return None
        hs = set(snap.hot); out = set(cat.index[cat["sub"].isin(hs)])
        return out if 0 < len(out) <= max_share * len(cat) else None
    except Exception as e:
        print('hot_products failed', type(e).__name__, e, flush=True); return None

COLD_LOG = {}
def cold_lq_for_arms(cat, T):
    """T-028: {product: corrected lq} for lfm arms with "lq": "cold"; None when no arm asks, when the corrector is not
    ready or on any error, and then those arms serve exactly the incumbent quality. Refresher thread only: no query."""
    try:
        if CLQ is None or QR is None or not LF.alt_lq or not CLQ.ready: return None
        out = CLQ.corrections(QR.q, QR.lq, cat, BASE["item"], organic_frame(T), AP.cold.desc, lq0=LF.lq0)   # T-047: organic counts only
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
            refresh_prev_views()
            if AP is not None:
                try: AP.refresh(query, cat, BASE["item"], T.item_frame(), organic_item=organic_frame(T))
                except Exception as e: print('aff refresh failed', type(e).__name__, e, flush=True)
            if ATP is not None:
                try: ATP.refresh(query, cat, unavail, organic_frame(T), sync=AP is None)   # T-047: attr_model reads these as organic totals
                except Exception as e: print('attr refresh failed', type(e).__name__, e, flush=True)
            if LF is not None and AP is not None:
                try:
                    oq, oq_hist = organic_counts(T)
                    LF.set_catalog(cat, unavail, AP.aff, QR.lq if QR is not None else None, d130.HC, lq_cold=cold_lq_for_arms(cat, T), newp=new_products(cat), hot=hot_products(cat), oq=oq, oq_hist=oq_hist)
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
            req = dict(user_id=r['user_id'], rv=r['rv'], page=r.get('page', 'product'), is_new_user=new, device=r.get('device'), region=r.get('region'), request_id=r.get('request_id'))
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

def user_bought(u):
    """Everything the shopper already bought, from the three sources: 60-day history (LF.hbought), today's organic
    stream and our own carousel feedback (BOUGHT, mirrored in LF.lbought). Lock-free and never raises: it runs on the
    send path, where a stalled or failed call would cost the answer."""
    for _ in range(2):
        try:
            b = set(BOUGHT.get(u, ()))
            if LF is not None:
                b |= set(LF.lbought.get(u, ()))
                if getattr(LF, 'prior_allow', False) and b: b -= LF.prior_bought(u)      # T-063: prior purchases are servable in "allow" mode
                b |= set(LF.hbought.get(u, ()))
            return b
        except RuntimeError: continue      # a set changed size under us (refresher thread): try once more
        except Exception: break
    return set()

def bought_in(u, items):
    """Does `items` hold something the shopper already bought (same three sources as user_bought)? Membership tests
    only: nothing is copied and no shared set is iterated, so it is lock-free and costs well under a microsecond per
    product. Any doubt answers True: the caller then decides with user_bought()."""
    try:
        lf = LF
        sets = [s for s in (BOUGHT.get(u), lf.hbought.get(u) if lf is not None else None, lf.lbought.get(u) if lf is not None else None) if s]
        return bool(sets) and any(p in s for s in sets for p in items)
    except Exception: return True

GUARD_SHORT = [0]                 # slates sent with an already-bought product because fewer than ten others were left
def repair_for(u, items, best, active):
    """serving.repair that also keeps already-bought products out of the answer, the ranked ones included (T-043; the
    quick return of a valid slate used to skip the check, so a purchase known after the ranking was still sent).
    Returns `items` itself when it is valid and holds nothing bought. Otherwise: the ranked products that are still
    eligible and not bought, in their order, then `best` (active, unique, not bought). Ten valid products come first:
    when fewer than ten unbought ones exist, the slate is completed with bought ones and the exception is logged."""
    try: valid = isinstance(items, list) and len(items) == 10 and len(set(items)) == 10 and all(isinstance(p, str) and p in active for p in items)
    except TypeError: valid = False
    if valid and not bought_in(u, items): return items
    bought = user_bought(u)
    if not bought: return items if valid else repair(items, best, active)
    out, seen = [], set()
    for src in (items or (), best):
        for p in src:
            if isinstance(p, str) and p in active and p not in seen and p not in bought:
                seen.add(p); out.append(p)
                if len(out) == 10: return out
    full = repair(out + list(items or []), best, active)      # raises, as before, if there are not even ten active products
    GUARD_SHORT[0] += 1
    if GUARD_SHORT[0] <= 20 or GUARD_SHORT[0] % 100 == 0:
        print(json.dumps(dict(event='guard_bought_short', n=GUARD_SHORT[0], unbought=len(out), bought_sent=10 - len(out))), flush=True)
    return full

def fallback_answers(reqs, version=None):
    _, unavail, _, _, best = snapshot()
    avail = [p for p in best if p not in unavail]
    out = []
    for r in reqs:
        bought = user_bought(r.get("user_id"))
        items = [p for p in avail if p not in bought][:10] if bought else avail[:10]
        if len(items) < 10: items = avail[:10]
        out.append({"request_id": r["request_id"], "items": items, "model_version": version or VERSION + "-guard"})
    return out

GATE = None      # T-063: failover.Gate when started with --standby or WRITER_LEASE=1; None = behaviour unchanged
def scratch_insert(row):
    """Lease rows only (T-063). Never called unless WRITER_LEASE=1."""
    r = session().post(f'{API}/v1/tables/scratch', params={'database': TEAM}, json=[row], timeout=5); r.raise_for_status()

def make_gate(standby, lock_path, argv=None, env=None):
    """--standby: load, score without sending, write only after a promote file (runbook, T-063). WRITER_LEASE=1: remote
    fencing token in <team>.scratch. Neither given -> None."""
    if __package__: from . import failover
    else: import failover
    env = os.environ if env is None else env
    lease_on = env.get('WRITER_LEASE') == '1'
    if not standby and not lease_on: return None
    token = arg_value('--promote-token', env.get('PROMOTE_TOKEN'), argv)
    if standby and not token: raise SystemExit('--standby needs --promote-token <word> (or PROMOTE_TOKEN)')
    lease = failover.Lease(TEAM, query, scratch_insert, failover.holder_name(),
                           max_stale=float(env.get('WRITER_LEASE_MAX_STALE', 20))) if lease_on else None
    return failover.Gate(TEAM, query, lambda: WriterLock(lock_path), standby,
                         promote_path=arg_value('--promote-file', str(DATA / 'PROMOTE'), argv), token=token, lease=lease,
                         yield_to_foreign=env.get('STANDBY_YIELD', '1') != '0')

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
    if GATE is not None: GATE.before_post(batch)      # T-063: standby / lease gate; None (the default) = no gate
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
        items = repair_for(r.get('user_id'), original.get('items'), best, active)
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
    ids = {a['request_id'] for a in batch}
    oldest = lambda: max(age(r) for r in reqs if r['request_id'] in ids)
    attempts, retry = 1, None
    try:
        post_batch(batch, 3-oldest())
    except Exception as exc:
        # A timeout can mean accepted-but-acknowledgement-lost. Never blindly retry.
        # T-047, the one exception: ConnectTimeout = the connection was never established, nothing was sent. The SAME
        # claimed payload gets ONE more POST if the oldest request is still young enough, with the deadline budget
        # measured again right now (the failed connect used up to 0.3 s). Whatever the second attempt raises,
        # ConnectTimeout included, is final.
        if never_sent(exc):
            first_ms, seconds = round(1000*(time.perf_counter()-started), 1), oldest()
            retry = 'ok' if 0 < CONNECT_RETRY_AGE and seconds <= CONNECT_RETRY_AGE else 'no_budget'
            if retry == 'ok':
                attempts = 2
                print(json.dumps(dict(event='push_retry', n=len(batch), first_ms=first_ms, oldest_age_ms=round(1000*seconds, 1))), flush=True)
                try:
                    post_batch(batch, 3-seconds)
                    exc = None
                except Exception as second:
                    exc = second
        if exc is not None:
            journal.finish([a['request_id'] for a in batch], 'uncertain')
            print(json.dumps(dict(event='push_uncertain', n=len(batch), error=type(exc).__name__,
                                  post_ms=round(1000*(time.perf_counter()-started), 1), attempts=attempts,
                                  **({'retry': retry} if retry else {}))), flush=True)
            return
    journal.finish([a['request_id'] for a in batch], 'acknowledged')
    print(json.dumps(dict(event='push_ack', n=len(batch),
        post_ms=round(1000*(time.perf_counter()-started), 1),
        oldest_age_ms=round(1000*max(age(r) for r in reqs), 1), **({'attempts': 2} if attempts == 2 else {}))), flush=True)


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

def failover_idle(idle_seen, limit=8):
    """Standby loop body: score a few real requests and send NOTHING (keeps caches and code paths warm)."""
    reqs = [r for r in pull(idle_seen) if age(r) <= 2.5][:limit]
    idle_seen.update(r['request_id'] for r in reqs)
    if len(idle_seen) > 5000: idle_seen.clear()
    if reqs: predict(reqs)

def main():
    import tempfile
    directory = Path(os.environ.get('RAWTREE_LOCK_DIR') or Path(tempfile.gettempdir()) / ('rawtree-' + TEAM))
    lock_path = directory / 'writer.lock'
    # --takeover: load and warm up NEXT TO the running writer, then ask it to stop and start writing the moment the
    # OS hands the lock over. This process never writes without the lock, so there are never two writers.
    global GATE
    standby = '--standby' in sys.argv and not DRY          # T-063: never writes until promoted by hand
    takeover = '--takeover' in sys.argv and not DRY and not standby
    old_pid = int(arg_value('--replace-pid', 0)) or None      # only for an old writer that left no pid file
    GATE = None if DRY else make_gate(standby, lock_path)
    writer_lock = None if DRY or takeover or standby else WriterLock(lock_path)
    journal = None
    try:
        signal.signal(signal.SIGINT, request_stop); signal.signal(signal.SIGTERM, request_stop)
        gc.callbacks.append(gc_watch)
        initialize()
        threading.Thread(target=refresher, daemon=True).start()
        threading.Thread(target=stock_refresher, daemon=True).start()
        while state['pools'] is None and not STOP.is_set():
            time.sleep(0.1)
        if takeover or standby:
            while (state['live'] is None or not state['stock_checked']) and not STOP.is_set():
                time.sleep(0.1)              # first full refresh done: today's stream is applied, every model is live
            warm_up()
            settle_gc()
            if STOP.is_set(): return
            if takeover: writer_lock = take_over(lock_path, old_pid)
        else:
            settle_gc()
        if GATE is not None:
            if not standby: GATE.start(writer_lock)          # lease-only writer: take the token or die before writing
            threading.Thread(target=GATE.run_checks, args=(STOP,), daemon=True).start()
        if not DRY:
            journal = Journal(directory / 'attempts.sqlite3')
        print('ready', 'DRY RUN' if DRY else 'STANDBY (not writing)' if standby else 'LIVE', 'A/B 50/50' if AB else '', flush=True)
        seen = set()
        def reconcile():
            # First migration from the old writer has no local journal. Reconcile
            # newest IDs with remote submissions before serving any of them.
            seen.update(r['request_id'] for r in query(f"""SELECT DISTINCT s.request_id::String request_id
                FROM {TEAM}.submissions s INNER JOIN
                (SELECT request_id FROM shop.requests ORDER BY ts DESC LIMIT 60) r
                ON s.request_id::String = r.request_id::String"""))
        if not DRY:
            reconcile()
        idle_seen = set()
        def deliver(reqs, answers):
            send_answers(reqs, answers, journal, seen, dry=DRY)
        def score(reqs):
            ctrl = [r for r in reqs if AB and zlib.crc32(r['user_id'].encode()) % 2 == 0]
            model = [r for r in reqs if r not in ctrl]
            return (predict(model) if model else []) + fallback_answers(ctrl, 'baseline-ctrl')
        while not STOP.is_set():
            started = time.perf_counter()
            try:
                if GATE is not None:          # T-063; with no gate this block does not exist
                    verdict = GATE.tick()
                    if verdict == 'stop': break
                    if verdict == 'promoted':
                        reconcile(); idle_seen.clear()
                        print('ready LIVE (promoted)', flush=True)
                    elif verdict != 'write':
                        if verdict == 'idle': failover_idle(idle_seen)
                        time.sleep(0.25); continue
                reqs = pull(seen)
                if journal:
                    reqs = [r for r in reqs if not journal.contains(r['request_id'])]
                expired_ids = {r['request_id'] for r in reqs if age(r) > 2.5}
                seen.update(expired_ids)
                expired = serve(reqs, score, fallback_answers, deliver, urgent_age=URGENT_AGE)
                if reqs:
                    prior_report()
                    print(json.dumps(dict(event='loop', n=len(reqs), expired=expired,
                        loop_ms=round(1000*(time.perf_counter()-started), 1),
                        stock_age_s=round(time.monotonic()-state['stock_checked'], 2))), flush=True)
            except Exception as exc:
                print('loop error', type(exc).__name__, str(exc), flush=True)
                time.sleep(0.1)
            # Network round trips already consumed time; don't add a fixed .25s tax.
            time.sleep(max(0, 0.1-(time.perf_counter()-started)))
        print(json.dumps(dict(event='stopped', reason='signal' if STOP.is_set() else 'gate')), flush=True)
    finally:
        if GATE is not None:
            GATE.close()
        if journal:
            journal.close()
        if writer_lock:
            writer_lock.close()


if __name__ == '__main__':
    main()
