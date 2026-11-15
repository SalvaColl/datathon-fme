import sys, json, numpy as np, pandas as pd
sys.path.insert(0, "/home/user/datathon-fme/recsys"); import lfm
FE = lfm.FEATS; FI = {f: k for k, f in enumerate(FE)}; RS = "/home/user/datathon-fme/recsys/"
def load():
    I = pd.concat([pd.read_parquet(f"I{j}.parquet") for j in range(4)], ignore_index=True)
    F = np.hstack([np.concatenate([np.load(f"F{j}.npy") for j in range(4)]), np.load("E.npy")]).astype(np.float64)
    R = pd.concat([pd.read_parquet(f"R{j}.parquet") for j in range(4)], ignore_index=True).set_index("rid")
    R["trait"] = (R.ha + 1) / (R.hv + 20)
    R["seg"] = np.where(R.new, "new", np.where(R.trait >= 0.12, "kS", "kR")) + "/" + R.coh
    return I, F, R
def wvec(spec):
    """policy arm spec -> {(seg, home?): weight vector}"""
    def build(a):
        c = json.load(open(RS + a["file"]))
        w = {k: np.array([c[k]["w"].get(f, 0.0) for f in FE]) for k in ("known", "new")}
        for s, o in (a.get("w") or {}).items():
            for f, v in o.items(): w[s][FI[f]] = v
        return w
    p = build(spec); h = build(spec["home"]) if isinstance(spec.get("home"), dict) else p
    return {("known", False): p["known"], ("new", False): p["new"], ("known", True): h["known"], ("new", True): h["new"]}
def pol(name): return wvec(json.load(open(RS + name))["lfm_arms"][0])
