from clfit import *
Tb = tensor(["kS/page", "kR/page"], "buy"); Tc = tensor(["kS/page", "kR/page"], "clk"); sd = within_sd(Tc); th = fit_base(Tb); key = ("known", False)
w, a = fit_w([Tb, Tc], th[0] * U1[key], 30, feats=[f for f in VAR if sd[FI[f]] > 0], alphas=[1, 0.3], sd=sd); w = w / th[0]
r3 = json.load(open(RS + "lfm_coef_r3.json"))["known"]["w"]
known = {f: round(float(w[FI[f]]), 2) for f in FE if abs(w[FI[f]] - r3.get(f, 0.0)) > 0.004}; known["lq"] = 0.0; known["hot"] = 3.0
print(known)
u1 = json.load(open(RS + "policy.unified.json"))["lfm_arms"][0]
json.dump({"variant": "lfm", "lfm_arms": [{"tag": "u4k", "file": "lfm_coef_r3.json", "w": {"known": known, "new": u1["w"]["new"]}, "home": u1["home"]}]}, open(RS + "policy.unified_u4k.json", "w"))
