"""T-043: cost of the purchase check in live.repair_for (send path) and of the policy validation (refresher thread).
No network, no model: synthetic catalogue of 20,000 products, shoppers with 0 / 30 / 300 purchases in each source.
    python tools/bench_guard.py
"""
import contextlib, io, json, random, statistics, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recsys import lfm, live
from recsys.serving import repair


def old_repair_for(u, items, best, active):          # main 6150ffc, verbatim
    if isinstance(items, list) and len(items) == 10 and len(set(items)) == 10 and all(isinstance(p, str) and p in active for p in items):
        return items
    bought = live.user_bought(u)
    if bought:
        try: return repair(items, [p for p in best if p not in bought], active)
        except ValueError: pass
    return repair(items, best, active)


def timeit(fn, n=20000, rounds=7):
    out = []
    for _ in range(rounds):
        t = time.perf_counter()
        for _ in range(n): fn()
        out.append((time.perf_counter() - t) / n * 1e6)
    return statistics.median(out)


def main():
    rnd = random.Random(7); best = ["p%05d" % k for k in range(20000)]; active = set(best)
    class LF: hbought = {}; lbought = {}
    live.LF = LF; rows = []
    for nb in (0, 30, 300):
        u = "u%d" % nb
        if nb:
            live.BOUGHT[u] = set(rnd.sample(best[200:], nb)); LF.hbought[u] = set(rnd.sample(best[200:], nb)); LF.lbought[u] = set(live.BOUGHT[u])
        clean = best[40:50]; assert not live.bought_in(u, clean)
        rows.append((nb, "lista válida sin comprados (camino habitual)", timeit(lambda: old_repair_for(u, clean, best, active)), timeit(lambda: live.repair_for(u, clean, best, active))))
        if nb:
            dirty = best[40:49] + [next(iter(live.BOUGHT[u]))]
            rows.append((nb, "lista válida con 1 comprado (antes se enviaba)", timeit(lambda: old_repair_for(u, dirty, best, active)), timeit(lambda: live.repair_for(u, dirty, best, active), n=2000)))
        short = best[40:47]
        rows.append((nb, "lista corta, hay que rellenar", timeit(lambda: old_repair_for(u, short, best, active), n=300), timeit(lambda: live.repair_for(u, short, best, active), n=300)))
    print("| Compras por fuente | Caso | Antes (µs) | Ahora (µs) |\n|---:|---|---:|---:|")
    for nb, case, a, b in rows: print(f"| {nb} | {case} | {a:.2f} | {b:.2f} |")

    # policy validation: one read_policy() cycle with an unchanged file, a changed valid file and a rejected file
    from tests.test_lfm import build
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp); live.DATA = d; real = lfm.HERE; live.LF, _ = build()
        arms = [{"tag": "r3", "file": "lfm_coef_r3.json"}, {"tag": "np2", "file": "lfm_coef_r3.json", "w": {"known": {"newp": 2.0}}},
                {"tag": "cn1", "file": "lfm_coef_r3.json", "lq": "cold_new"}, {"tag": "r2", "file": "lfm_coef_r2.json"}]
        (d / "policy.json").write_text(json.dumps({"variant": "lfm", "lfm_arms": arms}))
        sink = io.StringIO()
        with contextlib.redirect_stdout(sink):
            live.read_policy(); assert len(live.POLICY["lfm_arms"]) == 4, sink.getvalue()
            same = timeit(live.read_policy, n=2000)
            def flip(k=[0]):
                k[0] += 1; a = arms if k[0] % 2 else arms[:3]
                (d / "policy.json").write_text(json.dumps({"variant": "lfm", "lfm_arms": a})); live.read_policy()
            changed = timeit(flip, n=300)
            (d / "policy.json").write_text(json.dumps({"variant": "lfm", "lfm_arms": arms[:1] + [{"tag": "bad", "file": "lfm_coef_missing.json"}]}))
            bad = timeit(live.read_policy, n=2000)
        print(f"\nread_policy(), hilo de refresco (un ciclo cada ~20 s): fichero sin cambios {same:.0f} µs, "
              f"cambio válido de 4 brazos {changed:.0f} µs (incluye escribir el fichero), candidato rechazado {bad:.0f} µs")


if __name__ == "__main__":
    main()
