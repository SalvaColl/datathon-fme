"""T-022: páginas de producto y categoría con usuario conocido. Solo lectura; no escribe en RawTree ni toca el writer.

    cd recsys && python lfm_build.py --pull --no-write      # deja data/lfm_*.parquet (feedback propio, eventos, catálogo)
    python explore_known_session.py                         # E-220: qué vende por tipo y slot; E-221: brazos de arms_t022.json

Qué hace
  1. Reconstruye cada impresión servida (lfm_build.impressions) y la clasifica: carrito pendiente, último visto, otro
     visto reciente, relacionado (misma subcategoría o categoría que el último visto) o genérico.
  2. Tabla de compras por tipo y tramo de slot (tasas observadas, todas las políticas del equipo).
  3. Repite peticiones recientes con los brazos de `arms_t022.json` por el MISMO camino que el writer
     (`LiveFit.set_arms` + `LiveFit.slate(model=tag)`): comprueba 10 ids distintos y vivos, mide la composición de la
     slate y estima compras por 100 peticiones con las tasas observadas por celda (tipo × slot × afinidad × calidad).

La estimación es optimista para los brazos que suben carritos: los carritos que añaden son de menos afinidad y calidad
que los ya observados, y la celda solo lo recoge en tres tramos. El juez es la fila del brazo en el leaderboard.
"""
from __future__ import annotations
import json, time, warnings
import numpy as np, pandas as pd
import lfm, lfm_build

warnings.filterwarnings("ignore")
F = lfm.FEATS; FI = {f: k for k, f in enumerate(F)}
TYPES = ["carrito", "ultimo_visto", "otro_visto", "relacionado", "generico"]


def cells(X, slots):
    g = lambda f: X[:, FI[f]]
    cart = (g("chn") > 0) | (g("cl") > 0)
    typ = np.select([cart, g("islast") > 0, g("oinrv") > 0, (g("ssub2") > 0) | (g("scat2") > 0)], [0, 1, 2, 3], 4)
    return typ, np.digitize(slots, [1.5, 3.5, 6.5]), np.digitize(g("aff10"), [0.5, 1.0]), np.digitize(g("lq"), [4.5, 5.5])


def main(n_replay=3000, since="2026-11-14 13:30"):
    d, LF, aff, carts, buys = lfm_build.load(); S = LF.snap
    I = lfm_build.impressions(d, LF, aff, carts, buys)
    I = I.merge(d[["served_by"]], left_on="rid", right_index=True)
    A = I[(I.page != "home") & (I.served_by == "team") & (I.dead == 0) & (~I.new_user)].copy()
    A["typ"], A["sb"], A["ab"], A["lb"] = cells(A[F].values, A.slot.values)
    p = A.groupby(["typ", "sb"]).buy.agg(["sum", "size"]); p["r"] = (p["sum"] + 0.5) / (p["size"] + 500)
    t = p.copy(); t.index = pd.MultiIndex.from_tuples([(TYPES[a], ["1", "2-3", "4-6", "7-10"][b]) for a, b in t.index])
    print(f"E-220 · usuario conocido, producto/categoría: {A.rid.nunique()} peticiones, {int(A.buy.sum())} compras, {int(A.clk.sum())} clics")
    print("impresiones:\n", t["size"].unstack().to_string()); print("compras:\n", t["sum"].unstack().to_string())
    print("compras por 10.000 impresiones:\n", (1e4 * t["sum"] / t["size"]).round(1).unstack().to_string())
    c = A.groupby(["typ", "sb", "ab", "lb"]).buy.agg(["sum", "size"]).reset_index(); c["pr"] = [p.r[(a, b)] for a, b in zip(c.typ, c.sb)]
    c["r"] = (c["sum"] + 800 * c.pr) / (c["size"] + 800); tab = c.set_index(["typ", "sb", "ab", "lb"]).r.to_dict(); par = p.r.to_dict()

    arms = json.loads((lfm.HERE / "arms_t022.json").read_text())["lfm_arms"]
    LF.set_arms(arms)

    class AsOf:
        def __init__(self, ts): self.ts = ts
        def affinity_all(self, u, rv): return lfm_build.aff_asof(aff, u, rv, self.ts)

    D = d[(d.served_by == "team") & (~d.new_user) & (d.ts >= pd.Timestamp(since))]
    D = D.sample(min(n_replay, len(D)), random_state=2)
    val = {a["tag"]: [] for a in arms}; comp = {a["tag"]: np.zeros(5) for a in arms}; bad = 0; secs = 0.0; home = {a["tag"]: [] for a in arms}
    for r in D.itertuples():
        st = lfm_build.state_asof(LF, carts, buys, r.user_id, r.ts); b, lc, hc, bt = st
        req = dict(user_id=r.user_id, rv=r.rv, page=r.page, is_new_user=False, device=r.device, region=r.region)
        X = lfm.features(S, lfm_build.aff_asof(aff, r.user_id, r.rv, r.ts), r.rv, r.page, hc, lc, bought_today=bt, seg=lfm.in_segment(r.device, r.region))
        stale = S.stale(r.user_id)
        for a in arms:
            t0 = time.time(); s = LF.slate(req, st, AsOf(r.ts), model=a["tag"]); secs += time.time() - t0
            ks = [S.row[x] for x in s] if s else []
            if not s or len(set(s)) != 10 or any(x in b or (stale is not None and stale[k] and x not in hc and x not in lc) for x, k in zip(s, ks)):
                bad += 1; continue
            typ, sb, ab, lb = cells(X[ks], np.arange(1, 11))
            if r.page == "home": home[a["tag"]].append(int((typ == 0).sum())); continue
            val[a["tag"]].append(sum(tab.get(k, par[(k[0], k[1])]) for k in zip(typ, sb, ab, lb))); comp[a["tag"]] += np.bincount(typ, minlength=5)
    n = len(val[arms[0]["tag"]]); base = np.array(val[arms[0]["tag"]])
    print(f"\nE-221 · repetición de {len(D)} peticiones de usuario conocido ({n} con sesión) · slates no válidas {bad} · {1000 * secs / (len(D) * len(arms)):.2f} ms por slate")
    for a in arms:
        v = np.array(val[a["tag"]]); dl = v - base
        print(f"  {a['tag']:4s} compras estimadas por 100 peticiones {100 * v.mean():.2f} (delta {100 * dl.mean():+.2f}, ee {100 * dl.std() / np.sqrt(n):.3f}) | por slate: "
              + ", ".join(f"{TYPES[k]} {comp[a['tag']][k] / n:.2f}" for k in range(5)) + f" | home: carritos por slate {np.mean(home[a['tag']]):.2f}")


if __name__ == "__main__":
    main()
