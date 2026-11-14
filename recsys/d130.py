"""D-130 hook for the single live writer — ONE line in live.py, hot-switchable, inert by default.

Add this line to live.py just above the final `if __name__ == "__main__":` and restart the writer once
(works with the original live.py and with the hardened one of salva/serving-reliability / javi/qrank-serving):

    import d130; d130.install(globals())

It wraps (does not edit) four things of live.py, so it works on top of any policy variant of the writer:
  LIVE.add      -> also feeds home_cands.HomeCands (bought / carted / category views per user, item counts)
  make_pools    -> also refreshes HomeCands' top lists with the current catalog and stock
  candidates    -> mode nodead|home: drops items the shopper already bought or viewed-without-carting (I-130)
  predict       -> mode home: requests without recent_views are answered by HomeCands.slate() (I-131)

Mode is read from data/d130.json at every batch (hot switch, no restart):  {"mode": "off" | "nodead" | "home"}
Missing file or any error = "off" = exactly the previous behaviour. Every wrapper falls back to the original
result on any exception, and a slate is only replaced if it has 10 distinct in-stock ids.
Answers touched by the hook get model_version "<old>+nd" (nodead) or "<old>+home" for attribution in feedback.
Composes with policy.json variants: qrank slates (requests WITH views) are never modified; mode `home` only changes
requests WITHOUT views, which qrank does not serve. `d130.HC.is_dead(user, item)` is available to other rankers.
"""
import json, os, time, traceback
from pathlib import Path
import pandas as pd
import home_cands

DATA = Path(__file__).resolve().parent / "data"
POLICY = str(DATA / "d130.json")
_state = {"mode": "off", "mtime": None, "checked": 0.0, "dropped": 0, "cands": 0, "home": 0, "reqs": 0, "errors": 0, "t": time.time()}
HC = None
_touched = set()

def mode():
    now = time.time()
    if now - _state["checked"] > 1.0:                      # at most one stat() per second
        _state["checked"] = now
        try:
            mt = os.path.getmtime(POLICY)
            if mt != _state["mtime"]:
                m = json.load(open(POLICY)).get("mode", "off"); m = m if m in ("off", "nodead", "home") else "off"
                if m != _state["mode"]: print(f"d130 mode -> {m}", flush=True)
                _state.update(mode=m, mtime=mt)
        except FileNotFoundError:
            if _state["mode"] != "off": print("d130 mode -> off (no policy file)", flush=True)
            _state.update(mode="off", mtime=None)
        except Exception as e:
            print("d130 policy read error (keeping mode)", e, flush=True)
    return _state["mode"]

def _err(where):
    _state["errors"] += 1
    if _state["errors"] <= 20: print("d130 error in", where, flush=True); traceback.print_exc()

def install(g):
    """g = live.py's globals()."""
    global HC
    t = time.time()
    HC = home_cands.HomeCands(pd.read_parquet(DATA / "user_item_all.parquet"), g["fe"].C)
    print(f"d130 installed: HomeCands built in {time.time() - t:.1f}s, mode={mode()}", flush=True)
    LIVE = g["LIVE"]; o_add = LIVE.add; o_pools = g["make_pools"]; o_cands = g["candidates"]; o_predict = g["predict"]; state = g["state"]

    def add(u, i, v, a, p):
        o_add(u, i, v, a, p)
        try: HC.add(u, i, v, a, p)
        except Exception: _err("add")
    LIVE.add = add

    def make_pools(cat, unavail, *a, **k):
        out = o_pools(cat, unavail, *a, **k)
        try: HC.refresh(cat, unavail)
        except Exception: _err("refresh")
        return out

    def candidates(req, *a, **k):
        out = o_cands(req, *a, **k)
        if _state["mode"] == "off": return out
        try:
            kept = HC.drop_dead(req["user_id"], out)
            _state["cands"] += len(out); _state["dropped"] += len(out) - len(kept); _touched.add(req.get("request_id"))
            return kept
        except Exception:
            _err("candidates"); return out

    def predict(reqs):
        m = mode(); _touched.clear()
        out = o_predict(reqs)
        if m == "off": return out
        try:
            by_id = {r["request_id"]: r for r in reqs}; _state["reqs"] += len(out)
            unavail = set(state.get("unavail") or ()) | set(state.get("stock_out") or ())   # stock_out: hardened writer only
            for ans in out:
                r = by_id.get(ans["request_id"])
                if r is None: continue
                if m == "home" and not r["rv"]:
                    items = HC.slate(r["user_id"])
                    if len(items) == 10 and len(set(items)) == 10 and not (set(items) & unavail):
                        ans["items"] = items; ans["model_version"] = ans["model_version"] + "+home"; _state["home"] += 1; continue
                if ans["request_id"] in _touched:            # only answers whose candidates went through the filter
                    ans["model_version"] = ans["model_version"] + "+nd"   # (e.g. qrank slates are left untouched)
            if time.time() - _state["t"] > 60:
                print(f"d130 mode={m} last ~60s: requests {_state['reqs']}, home slates {_state['home']}, dead candidates dropped "
                      f"{_state['dropped']}/{_state['cands']}, errors {_state['errors']}", flush=True)
                _state.update(t=time.time(), reqs=0, home=0, dropped=0, cands=0)
        except Exception: _err("predict")
        return out

    g["make_pools"] = make_pools; g["candidates"] = candidates; g["predict"] = predict
