"""T-025 hook: structurally different HOME slates as leaderboard arms. ONE line in live.py, hot-switchable, inert by default.

    live.py, inside initialize() after the d130 / live_quality hooks:
        try: home_arms.install(globals())
        except Exception as e: print('home_arms not installed, serving unchanged:', type(e).__name__, e, flush=True)

Why: home (requests without recent_views) is ~19% of the traffic and converts ~0.55% by the hidden model, at the level
of the baseline, while the rest of our traffic is at ~2.2%. "No signal in home" was concluded from a handful of real
purchases; the leaderboard's per-model_version row gives the hidden model's expectation without that noise, so the
cheap way to learn what home rewards is to show it very different slates and read the rows.

Switch (re-read at most once per second, no restart):  data/home_arms.json
    {"arms": ["control", "trend", "catbest", "conv"], "salt": "h1"}
  Missing file, empty list or any error = off = exactly the previous behaviour. "control" keeps the writer's own home
  slate (and its label). Users are split by hash(salt + user_id) over the list, so an arm can be repeated for weight.
  When one arm wins: {"arms": ["catbest"]} serves it to every home request.

Arms (all built from data the writer already holds; no extra query, rebuilt at every make_pools, ~20 s):
  trend    products with most organic purchases in the last WINDOW_MIN minutes (today's counts minus a snapshot)
  catbest  the best product of each category (today's shrunk purchase rate x volume), categories ordered by that score
  conv     highest shrunk purchase-per-view rate (history + today), whatever the volume
  trend and conv take at most MAX_PER_SUB products of a subcategory, so the slate is not ten near-duplicates.

Per request: products out of stock / inactive, bought today, or dead for that shopper (d130.HC.is_dead) are skipped and
the next of the arm's list (POOL long) takes the place. The slate replaces the answer only if it has 10 distinct
available ids; otherwise the writer's own answer stays. Label: "hx-<arm>-k" (returning) or "-n" (new shopper), so the
leaderboard gives each arm's conversion and its cold-start row separately.
"""
import collections, json, os, time, traceback, zlib
from pathlib import Path
import numpy as np, pandas as pd

DATA = Path(__file__).resolve().parent / "data"
POLICY = str(DATA / "home_arms.json")
ARMS = ("trend", "catbest", "conv")
WINDOW_MIN = 30          # look-back of the trend arm
MAX_PER_SUB = 2
POOL = 60                # length of each arm's ordered list (room for per-shopper filtering)
K_VIEWS = 200            # shrinkage of purchase / view towards the global rate, in views
_state = {"arms": [], "salt": "h1", "mtime": None, "checked": 0.0, "errors": 0, "t": time.time(), "served": collections.Counter()}
_lists = {}              # arm -> ordered product ids, replaced atomically by rebuild()
_snaps = collections.deque()   # (monotonic seconds, {product: purchases today}) for the trend arm


def read_policy(now=None):
    now = time.time() if now is None else now
    if now - _state["checked"] <= 1.0: return _state["arms"]
    _state["checked"] = now
    try:
        mt = os.path.getmtime(POLICY)
        if mt != _state["mtime"]:
            cfg = json.load(open(POLICY)); arms = cfg.get("arms") or []
            ok = isinstance(arms, list) and all(a in ARMS or a == "control" for a in arms)
            arms = list(arms) if ok else []
            if not ok: print("home_arms: invalid arms list, off", flush=True)
            if arms != _state["arms"]: print(f"home_arms arms -> {arms}", flush=True)
            _state.update(arms=arms, salt=str(cfg.get("salt", "h1")), mtime=mt)
    except FileNotFoundError:
        if _state["arms"]: print("home_arms -> off (no policy file)", flush=True)
        _state.update(arms=[], mtime=None)
    except Exception as e:
        print("home_arms policy read error (keeping arms)", e, flush=True)
    return _state["arms"]


def arm_of(user_id, arms=None, salt=None):
    arms = _state["arms"] if arms is None else arms
    if not arms: return "control"
    return arms[zlib.crc32(((_state["salt"] if salt is None else salt) + str(user_id)).encode()) % len(arms)]


def _capped(order, sub, n=POOL, cap=MAX_PER_SUB):
    out, seen = [], collections.Counter()
    for p in order:
        s = sub.get(p)
        if seen[s] >= cap: continue
        seen[s] += 1; out.append(p)
        if len(out) >= n: break
    return out


def rebuild(cat, unavail, hist_item=None, live_item=None, now=None):
    """Recompute the arms' lists. cat: frame indexed by product (category, sub); hist_item / live_item: frames indexed by
    product with it_v (views), it_a (carts), it_p (purchases); either may be None."""
    now = time.monotonic() if now is None else now
    idx = cat.index[~cat.index.isin(list(unavail))]
    z = pd.DataFrame(0.0, index=idx, columns=["it_v", "it_p"])
    h = hist_item.reindex(idx)[["it_v", "it_p"]].fillna(0.0) if hist_item is not None else z
    l = live_item.reindex(idx)[["it_v", "it_p"]].fillna(0.0) if live_item is not None else z
    sub = cat["sub"].to_dict(); category = cat.loc[idx, "category"]
    # conv: shrunk purchase / view over history + today
    v, p = h.it_v + l.it_v, h.it_p + l.it_p
    rate0 = float(p.sum() / max(v.sum(), 1.0))
    conv = (p + K_VIEWS * rate0) / (v + K_VIEWS)
    lists = {"conv": _capped(conv.sort_values(ascending=False, kind="stable").index.tolist(), sub)}
    # catbest: today's shrunk rate x log volume (history if the day has no data yet), best of each category first
    tv, tp = (l.it_v, l.it_p) if float(l.it_p.sum()) > 0 else (v, p)
    r0 = float(tp.sum() / max(tv.sum(), 1.0))
    score = (tp + K_VIEWS * r0) / (tv + K_VIEWS) * np.log1p(tp + 1.0)
    ranked = pd.DataFrame(dict(c=category, s=score)).sort_values("s", ascending=False, kind="stable")
    ranked["k"] = ranked.groupby("c").cumcount()                      # 0 = best of its category, 1 = second...
    lists["catbest"] = ranked.sort_values(["k", "s"], ascending=[True, False], kind="stable").index[:POOL].tolist()
    # trend: purchases since the oldest snapshot not older than WINDOW_MIN (needs a few minutes of snapshots)
    cur = l.it_p[l.it_p > 0].to_dict()
    _snaps.append((now, cur))
    while len(_snaps) > 1 and now - _snaps[1][0] >= WINDOW_MIN * 60: _snaps.popleft()
    t0, old = _snaps[0]
    if now - t0 >= 120:
        delta = pd.Series({i: c - old.get(i, 0.0) for i, c in cur.items()}, dtype=float)
        delta = delta[delta > 0]
        order = delta.sort_values(ascending=False, kind="stable").index.tolist()
        lists["trend"] = _capped(order + [i for i in lists["catbest"] if i not in delta.index], sub)
    else:
        lists["trend"] = list(lists["catbest"])                      # no window yet: same as catbest
    _lists.clear(); _lists.update(lists)
    return lists


def slate(arm, user_id, blocked=(), is_dead=None, k=10):
    """k ordered distinct ids of the arm for this shopper, or None if the arm cannot fill k."""
    out = []
    for p in _lists.get(arm, ()):
        if p in blocked: continue
        if is_dead is not None:
            try:
                if is_dead(user_id, p): continue
            except Exception: pass
        out.append(p)
        if len(out) == k: return out
    return None


def _err(where):
    _state["errors"] += 1
    if _state["errors"] <= 20: print("home_arms error in", where, flush=True); traceback.print_exc()


def install(g):
    """g = live.py's globals(). Wraps make_pools (to rebuild the lists) and predict (to swap home slates)."""
    o_pools = g["make_pools"]; o_predict = g["predict"]; state = g["state"]
    print(f"home_arms installed, arms={read_policy()}", flush=True)

    def make_pools(cat, unavail, T, *a, **k):
        out = o_pools(cat, unavail, T, *a, **k)
        try: rebuild(cat, unavail, g["BASE"]["item"] if g.get("BASE") else None, T.item_frame() if T is not None else None)
        except Exception: _err("rebuild")
        return out

    def predict(reqs):
        out = o_predict(reqs)
        try:
            arms = read_policy()
            if not arms or not _lists: return out
            by_id = {r["request_id"]: r for r in reqs}
            blocked = set(state.get("unavail") or ()) | set(state.get("stock_out") or ())
            hc = getattr(g.get("d130"), "HC", None); dead = hc.is_dead if hc is not None else None
            bought = g.get("BOUGHT") or {}
            for ans in out:
                r = by_id.get(ans["request_id"])
                if r is None or r.get("rv"): continue
                arm = arm_of(r["user_id"], arms)
                if arm == "control": continue
                items = slate(arm, r["user_id"], blocked | set(bought.get(r["user_id"], ())), dead)
                if items and len(set(items)) == 10:
                    new = r.get("is_new_user") in (True, 1, "true", "True", "1")
                    ans["items"] = items; ans["model_version"] = f"hx-{arm}-{'n' if new else 'k'}"; _state["served"][arm] += 1
            if time.time() - _state["t"] > 60:
                print(f"home_arms arms={arms} last ~60s served {dict(_state['served'])}, errors {_state['errors']}", flush=True)
                _state["t"] = time.time(); _state["served"].clear()
        except Exception: _err("predict")
        return out

    g["make_pools"] = make_pools; g["predict"] = predict
