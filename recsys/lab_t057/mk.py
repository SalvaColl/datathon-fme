from clfit import *
VARF = [f for f in VAR if f != "hot"]
out = {}
for name, segs, key in (("known", ["kS/page", "kR/page"], ("known", False)), ("new", ["new/page"], ("new", False))):
    Tb = tensor(segs, "buy"); Tc = tensor(segs, "clk"); sd = within_sd(Tc); th = fit_base(Tb)
    w, a = fit_w([Tb, Tc], th[0] * U1[key], 30, feats=[f for f in VARF if sd[FI[f]] > 0], alphas=[1, 0.3], sd=sd); w = w / th[0]
    out[name] = {f: round(float(w[FI[f]]), 2) for f in FE if abs(w[FI[f]] - json.load(open(RS + "lfm_coef_r3.json"))[name]["w"].get(f, 0.0)) > 0.004}
    print(name, Tb["n"], "buys", out[name])
u1 = json.load(open(RS + "policy.unified.json"))["lfm_arms"][0]
def arm(tag, known, new): return {"variant": "lfm", "lfm_arms": [{"tag": tag, "file": "lfm_coef_r3.json", "w": {"known": known, "new": new}, "home": u1["home"]}]}
json.dump(arm("u3", out["known"], out["new"]), open(RS + "policy.unified_u3.json", "w"))
json.dump(arm("u3k", out["known"], u1["w"]["new"]), open(RS + "policy.unified_u3k.json", "w"))
g = {"u1": {k: v for k, v in u1.items() if k != "tag"}, "u2c": {k: v for k, v in json.load(open(RS + "policy.unified_u2c.json"))["lfm_arms"][0].items() if k != "tag"},
     "u3": {k: v for k, v in arm("u3", out["known"], out["new"])["lfm_arms"][0].items() if k != "tag"}}
json.dump(g, open("grid.json", "w"))
