"""T-038: dry-run de `policy.home_cart_r3.json` (carritos pendientes primero en home, usuario que vuelve). Solo lectura.

    cd recsys && python lfm_build.py --pull --no-write      # o cualquier descarga reciente de data/lfm_*.parquet
    python explore_home_cart_first.py

Repite peticiones reales por el camino del writer (`live.clean_lfm_arms` + `LiveFit.set_arms` + `LiveFit.slate(model=tag)`)
con el estado del usuario a la hora de cada petición y comprueba, slate a slate: 10 ids distintos y vivos; en el brazo
los carritos pendientes van primero en el orden del campeón y el resto es el orden del campeón; fuera del objetivo
(producto/categoría y usuarios nuevos) las dos slates son idénticas. También imprime lo observado en home con el
feedback propio (compras y clics por tipo y slot). No escribe en RawTree ni toca el writer.
"""
from __future__ import annotations
import json, time, warnings
import numpy as np, pandas as pd
import lfm, lfm_build, live

warnings.filterwarnings("ignore")
CTL, ARM = "r3", "h3c"


def main(n_home=3000, n_other=1500, since="2026-11-14 16:30"):
    d, LF, aff, carts, buys = lfm_build.load(); S = LF.snap
    fbuys = lfm_build.feedback_buys(d)
    I = lfm_build.impressions(d, LF, aff, carts, buys).merge(d[["served_by"]], left_on="rid", right_index=True)
    H = I[(I.page == "home") & (~I.new_user) & (I.served_by == "team") & (I.dead == 0) & (I.ts >= pd.Timestamp(since))].copy()
    H["tipo"] = np.where((H.chn > 0) | (H.cl > 0), "carrito", "resto"); H["slots"] = pd.cut(H.slot, [0, 1, 3, 6, 10], labels=["1", "2-3", "4-6", "7-10"])
    t = H.groupby(["tipo", "slots"]).agg(impresiones=("buy", "size"), clics=("clk", "sum"), compras=("buy", "sum"))
    print(f"home, usuario que vuelve, desde {since} UTC: {H.rid.nunique()} peticiones, {int(H.buy.sum())} compras, {int(H.clk.sum())} clics\n", t.to_string())

    LF.set_arms(live.clean_lfm_arms(json.loads((lfm.HERE / "policy.home_cart_r3.json").read_text())["lfm_arms"]))

    class AsOf:
        def __init__(self, ts): self.ts = ts
        def affinity_all(self, u, rv): return lfm_build.aff_asof(aff, u, rv, self.ts)

    D = d[(d.served_by == "team") & (d.ts >= pd.Timestamp(since))]
    tgt = (D.page == "home") & (~D.new_user) & (D.rv.map(len) == 0)
    D = pd.concat([D[tgt].sample(min(n_home, int(tgt.sum())), random_state=0), D[~tgt].sample(min(n_other, int((~tgt).sum())), random_state=0)])
    bad = viol = fillviol = offdiff = n_t = n_o = 0; nc = []; shown_c = {CTL: [], ARM: []}; ms = {CTL: [], ARM: []}; changed = 0; overlap = []
    for r in D.itertuples():
        st = lfm_build.state_asof(LF, carts, buys, r.user_id, r.ts, fbuys) + (lfm_build.mix_asof(LF, aff, r.user_id, r.ts),)
        b, lc, hc = st[:3]
        req = dict(user_id=r.user_id, rv=r.rv, page=r.page, is_new_user=bool(r.new_user), device=r.device, region=r.region)
        sl = {}
        for m in (CTL, ARM):
            t0 = time.perf_counter(); sl[m] = LF.slate(req, st, AsOf(r.ts), model=m); ms[m].append(1000 * (time.perf_counter() - t0))
        _, s = LF.scores(req, st, AsOf(r.ts), model=CTL)
        for m in (CTL, ARM):
            x = sl[m]
            if not x or len(set(x)) != 10 or any(p in b or not np.isfinite(s[S.row[p]]) for p in x): bad += 1
        if bad: continue
        target = r.page == "home" and not r.new_user and not r.rv
        if not target:
            n_o += 1; offdiff += int(sl[CTL] != sl[ARM]); continue
        n_t += 1
        pend = sorted((p for p in list(hc) + list(lc) if p in S.row and np.isfinite(s[S.row[p]])), key=lambda p: -s[S.row[p]])
        k = min(len(pend), 10); nc.append(len(pend))
        viol += int(sl[ARM][:k] != pend[:k])
        order = [S.ids[j] for j in np.argsort(-s, kind="stable")[:40]]
        fillviol += int(sl[ARM][k:] != [p for p in order if p not in set(pend)][:10 - k])
        for m in (CTL, ARM): shown_c[m].append(len(set(sl[m]) & set(pend)))
        changed += int(sl[CTL] != sl[ARM]); overlap.append(len(set(sl[CTL]) & set(sl[ARM])))
    nc = np.array(nc)
    print(f"\ndry-run: {len(D)} peticiones ({n_t} objetivo, {n_o} fuera) · slates no válidas {bad} · objetivo: carritos-primero incumplido {viol}, relleno distinto del campeón {fillviol}"
          f" · fuera del objetivo slates distintas {offdiff}/{n_o}")
    print(f"carritos pendientes vivos por usuario: 0 → {np.mean(nc == 0):.1%}, 1–9 → {np.mean((nc > 0) & (nc < 10)):.1%}, 10 o más → {np.mean(nc >= 10):.1%} (mediana {np.median(nc):.0f})")
    print(f"carritos por slate: campeón {np.mean(shown_c[CTL]):.2f}, brazo {np.mean(shown_c[ARM]):.2f} · slates que cambian {changed / n_t:.1%} · productos en común {np.mean(overlap):.1f} de 10")
    for m in (CTL, ARM): print(f"latencia {m}: p50 {np.median(ms[m]):.2f} ms, p95 {np.percentile(ms[m], 95):.2f}, p99 {np.percentile(ms[m], 99):.2f}")


if __name__ == "__main__":
    main()
