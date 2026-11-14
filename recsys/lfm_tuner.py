"""lfm_tuner — afina los pesos de lfm contra el leaderboard, por rondas, sin tocar RawTree (T-021, D-211).

En cristiano: las compras reales ya no distinguen una versión de lfm de otra (I-211), pero el leaderboard da la
conversión del modelo oculto por `model_version` y por ventana corta. Este script hace, cada ronda (30 min):

  1. Reparte a los usuarios en 3 brazos con `lfm_arms` en `data/policy.json` (el writer lo relee solo):
     control = los mejores pesos hasta ahora; "más" y "menos" = el mismo juego con UN peso movido +paso / -paso.
     Se mueve un peso del modelo de usuarios que vuelven y otro del de usuarios nuevos a la vez: cada segmento
     tiene su propia etiqueta en el leaderboard, así que las dos búsquedas no se estorban.
  2. Espera, y lee `api/state?by=model&from=<inicio de la ronda>` (solo lectura, público).
  3. Por segmento: si un brazo supera al control por más que el margen de ruido, sus pesos pasan a ser los mejores y
     la siguiente ronda sigue empujando ese mismo peso; si no, pasa al siguiente peso de la lista.

Solo escribe `data/policy.json` (la clave `lfm_arms`; el resto de claves no se toca) y sus logs en
`data/lfm_tuner/`. No es un writer: `live.py` tiene que estar corriendo con la variante `lfm`.

    python lfm_tuner.py check                      # ¿el writer en disco entiende lfm_arms? ¿policy.json está en lfm?
    python lfm_tuner.py run --until 08:30          # rondas hasta esa hora local; Ctrl-C deja los mejores pesos puestos
    python lfm_tuner.py run --rounds 1 --dry       # ensayo: no escribe policy.json
    python lfm_tuner.py report                     # tabla de rondas y pesos actuales

Al terminar deja un solo brazo con los mejores pesos (`--finish best`, por defecto) o quita `lfm_arms`
(`--finish off`, vuelve a los pesos publicados). Vuelta atrás manual: borrar `lfm_arms` de `data/policy.json`.
"""
from __future__ import annotations
import argparse, json, math, os, signal, sys, time, urllib.request, zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE_URL = "https://datathon.rawtree.dev/api/state?by=model"
TEAM = "team_26"
SEGS = {"known": ("-k", "-kh"), "new": ("-n", "-nh")}       # sufijos de versión de cada segmento (páginas con vistas, home)
# Orden de búsqueda: (peso, paso inicial). Primero lo que más mueve el slate según E-210 y el tablero de ideas.
PLAN = {
    "known": [("aff10", 0.5), ("hcart", 1.0), ("islast", 0.7), ("chn", 0.5), ("scat2", 0.5), ("ssub2", 0.5), ("oinrv", 0.7),
              ("lq", 0.25), ("cl", 0.7), ("bsub", 0.4), ("na", 0.3), ("p40", 0.5)],
    "new": [("aff10", 0.4), ("cl", 0.7), ("nbp", 0.5), ("bsub", 0.5), ("islast", 0.7), ("scat2", 0.5), ("ssub2", 0.5), ("oinrv", 0.7),
            ("lq", 0.25), ("segcheap", 0.4), ("na", 0.3), ("hcart", 1.0)],
}
W_LIMIT = 15.0
# Desviación típica por petición de la conversión esperada (puntos), medida el 14-nov con ventanas de 5-10 min del
# propio leaderboard: ~3.5 para usuarios que vuelven, ~5-6.5 para nuevos. Con ~1.100 y ~470 peticiones por brazo en
# 30 min, una ronda distingue ~0.25 puntos en los que vuelven y ~0.6 en los nuevos; efectos menores se quedan sin tocar.
SD = {"known": 4.0, "new": 6.0}


def write_json(path, obj):
    path = Path(path); tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj)); os.replace(tmp, path)          # el writer nunca ve un fichero a medias

def read_json(path, default=None):
    try: return json.loads(Path(path).read_text())
    except FileNotFoundError: return default

def fetch(start, end=None, url=STATE_URL, timeout=15):
    u = f"{url}&from={int(start)}" + (f"&to={int(end)}" if end else "")
    with urllib.request.urlopen(u, timeout=timeout) as r: return json.loads(r.read())

def public_label(version, labels):
    """Mismo cálculo que live.public_label: con data/labels.json el leaderboard ve un código, no el nombre interno."""
    if not labels or labels.get("salt") is None: return version
    return (labels.get("map") or {}).get(version) or "m%05x" % (zlib.crc32((str(labels["salt"]) + "|" + version).encode()) & 0xfffff)

def read_segment(state, tag, seg, labels=None, team=TEAM):
    """(peticiones, conversión %) de un brazo en un segmento: páginas con vistas + home, ponderado por peticiones."""
    rows = next((t.get("versions", []) for t in state.get("teams", []) if t.get("team_id") == team), [])
    by = {v["model_version"]: v for v in rows}
    n = buys = 0.0
    for suf in SEGS[seg]:
        v = by.get(public_label(f"v3-lfm-{tag}{suf}", labels))
        if v: n += v["requests"]; buys += v["requests"] * v["conversion"]
    return int(n), (buys / n if n else float("nan"))


class Tuner:
    def __init__(self, data_dir, base_coef, out_dir=None, round_s=30 * 60, margin=0.15, z=1.5, sd=None, min_requests=250, dry=False,
                 fetch_fn=fetch, now=time.time, sleep=time.sleep, log=print):
        self.data = Path(data_dir); self.out = Path(out_dir or self.data / "lfm_tuner"); self.out.mkdir(parents=True, exist_ok=True)
        self.round_s, self.margin, self.z, self.min_requests, self.dry = round_s, margin, z, min_requests, dry
        self.sd = {**SD, **(sd or {})}
        self.fetch, self.now, self.sleep, self.log = fetch_fn, now, sleep, log
        self.base = {s: dict(base_coef[s]["w"]) for s in SEGS}
        st = read_json(self.out / "state.json") or {}
        self.best = st.get("best") or {s: {} for s in SEGS}             # solo los pesos que difieren de la base
        self.pos = st.get("pos") or {s: 0 for s in SEGS}                # índice en PLAN
        self.scale = st.get("scale") or {s: 1.0 for s in SEGS}          # los pasos se reducen a la mitad tras cada vuelta completa
        self.round = int(st.get("round", 0))
        self.stop = False

    # ---- pesos ----
    def weight(self, seg, f): return float(self.best[seg].get(f, self.base[seg].get(f, 0.0)))

    def arms_for_round(self):
        """[control, más, menos] para lfm_arms y, por segmento, (peso, paso) que se mueve."""
        r = self.round; moves = {}
        arms = [{"tag": f"c{r:03d}", "w": {}}, {"tag": f"p{r:03d}", "w": {}}, {"tag": f"m{r:03d}", "w": {}}]
        for seg in SEGS:
            f, step = PLAN[seg][self.pos[seg] % len(PLAN[seg])]; step *= self.scale[seg]; moves[seg] = (f, step)
            for a, d in zip(arms, (0.0, step, -step)):
                w = dict(self.best[seg]); w[f] = round(max(-W_LIMIT, min(W_LIMIT, self.weight(seg, f) + d)), 4)
                if not d: w = dict(self.best[seg])
                a["w"][seg] = w
        for a in arms: a["w"] = {s: w for s, w in a["w"].items() if w}
        arms = [{k: v for k, v in a.items() if v} for a in arms]
        k = r % 3; arms = arms[k:] + arms[:k]      # el writer reparte usuarios por posición: rotar evita que el control sea siempre el mismo tercio
        return arms, moves

    # ---- policy.json ----
    def set_arms(self, arms):
        if self.dry: self.log("  (dry) policy.json no se toca:", json.dumps(arms)); return
        pol = read_json(self.data / "policy.json", {}) or {}
        if arms: pol["lfm_arms"] = arms
        else: pol.pop("lfm_arms", None)
        write_json(self.data / "policy.json", pol)

    def final_arms(self, mode):
        best = {s: w for s, w in self.best.items() if w}
        return [{"tag": "best", "w": best}] if (mode == "best" and best) else []

    # ---- una ronda ----
    def decide(self, ctrl, cand, seg="known"):
        """¿El candidato (n, conv) gana al control con margen de ruido? sd = desviación típica por petición, en puntos."""
        (nc, cc), (nx, cx) = ctrl, cand
        if min(nc, nx) < self.min_requests or math.isnan(cc) or math.isnan(cx): return False, float("nan")
        need = max(self.margin, self.z * self.sd[seg] * math.sqrt(1.0 / nc + 1.0 / nx))
        return (cx - cc) > need, need

    def run_round(self, labels=None):
        arms, moves = self.arms_for_round()
        start = self.now(); self.set_arms(arms)
        self.log(f"ronda {self.round}: " + "; ".join(f"{s}: {f} {self.weight(s, f):+.2f} ± {st:.2f}" for s, (f, st) in moves.items()))
        end = start + self.round_s
        while self.now() < end and not self.stop: self.sleep(min(30, max(1, end - self.now())))
        state = self.fetch(start + 30, None)                      # 30 s: el writer relee policy.json cada ~20 s
        rec = dict(round=self.round, start=start, end=self.now(), moves={s: list(m) for s, m in moves.items()}, segs={})
        for seg, (f, step) in moves.items():
            res = {a["tag"][0]: read_segment(state, a["tag"], seg, labels) for a in arms}
            ctrl = res["c"]; picked = None
            for key, d in (("p", step), ("m", -step)):
                ok, need = self.decide(ctrl, res[key], seg)
                if ok and (picked is None or res[key][1] > res[picked[0]][1]): picked = (key, d)
            if picked:
                self.best[seg][f] = round(max(-W_LIMIT, min(W_LIMIT, self.weight(seg, f) + picked[1])), 4)   # y repite este peso
            else:
                self.pos[seg] += 1
                if self.pos[seg] % len(PLAN[seg]) == 0: self.scale[seg] = max(0.25, self.scale[seg] / 2)
            rec["segs"][seg] = dict(feature=f, step=step, control=ctrl, plus=res["p"], minus=res["m"], picked=picked[0] if picked else None,
                                    weight_after=self.weight(seg, f))
            self.log(f"  {seg:5s} {f:8s} control {ctrl[1]:.3f}% ({ctrl[0]})  +{step:.2f}: {res['p'][1]:.3f}% ({res['p'][0]})  "
                     f"-{step:.2f}: {res['m'][1]:.3f}% ({res['m'][0]})  -> " + (f"se queda {'+' if picked[0] == 'p' else '-'}" if picked else "sin cambio"))
        with open(self.out / "rounds.jsonl", "a") as fh: fh.write(json.dumps(rec) + "\n")
        self.round += 1
        write_json(self.out / "state.json", dict(best=self.best, pos=self.pos, scale=self.scale, round=self.round))
        return rec

    def run(self, rounds=None, deadline=None, finish="best", freeze_s=3600):
        done = 0
        try:
            while not self.stop and (rounds is None or done < rounds):
                if deadline and self.now() + self.round_s > deadline: self.log("no cabe otra ronda antes de la hora límite"); break
                try:
                    st = self.fetch(self.now() - 600)
                    if st.get("mode") != "practice" or st.get("final_start", 1e18) - self.now() < freeze_s + self.round_s:
                        self.log("fuera de práctica o demasiado cerca de la final: paro"); break
                except Exception as e: self.log("leaderboard no disponible, reintento en 60 s:", type(e).__name__); self.sleep(60); continue
                labels = read_json(self.data / "labels.json")
                try: self.run_round(labels)
                except Exception as e: self.log("ronda fallida, no cambio nada:", type(e).__name__, e); self.sleep(30)
                done += 1
        finally:
            arms = self.final_arms(finish); self.set_arms(arms)
            self.log("fin. policy.json queda con", json.dumps(arms) if arms else "lfm sin brazos (pesos publicados)")


def report(out_dir):
    rows = [json.loads(l) for l in (Path(out_dir) / "rounds.jsonl").read_text().splitlines() if l.strip()] if (Path(out_dir) / "rounds.jsonl").exists() else []
    print("| Ronda | Hora | Segmento | Peso | Paso | Control | Más | Menos | Decisión | Peso después |\n|---|---|---|---|---:|---:|---:|---:|---|---:|")
    for r in rows:
        for seg, s in r["segs"].items():
            f = lambda x: f"{x[1]:.2f}% ({x[0]})"
            print(f"| {r['round']} | {time.strftime('%H:%M', time.localtime(r['start']))} | {seg} | {s['feature']} | {s['step']:.2f} | {f(s['control'])} | "
                  f"{f(s['plus'])} | {f(s['minus'])} | {s['picked'] or '-'} | {s['weight_after']:.2f} |")
    st = read_json(Path(out_dir) / "state.json") or {}
    print("\nPesos cambiados respecto a lfm_coef.json:", json.dumps(st.get("best", {})))


def check(data_dir, live_py):
    problems = []
    try:
        text = Path(live_py).read_text(encoding="utf-8")
        if "lfm_arms" not in text: problems.append("live.py en disco no entiende lfm_arms (falta el PR #11)")
    except OSError as e: problems.append(f"no puedo leer {live_py}: {e}")
    pol = read_json(Path(data_dir) / "policy.json", {}) or {}
    if pol.get("variant") != "lfm": problems.append(f"policy.json tiene variant={pol.get('variant')!r}; el afinador necesita 'lfm'")
    return problems


def parse_until(text, now=None):
    now = now or time.time(); h, m = (int(x) for x in text.split(":"))
    t = time.mktime(time.localtime(now)[:3] + (h, m, 0, 0, 0, -1))
    return t if t > now else t + 86400


def main(argv=None):
    p = argparse.ArgumentParser(description="Afina los pesos de lfm por rondas contra el leaderboard. Nunca escribe en RawTree.")
    p.add_argument("cmd", choices=("check", "run", "report"))
    p.add_argument("--data", default=str(HERE / "data")); p.add_argument("--coef", default=str(HERE / "lfm_coef.json"))
    p.add_argument("--round-min", type=float, default=30); p.add_argument("--rounds", type=int, default=None)
    p.add_argument("--until", default=None, help="hora local HH:MM; no empieza rondas que no quepan")
    p.add_argument("--margin", type=float, default=0.15, help="ventaja mínima en puntos de conversión para aceptar un cambio")
    p.add_argument("--z", type=float, default=1.5, help="cuántas veces el error típico tiene que ganar un brazo al control")
    p.add_argument("--min-requests", type=int, default=250)
    p.add_argument("--finish", choices=("best", "off"), default="best")
    p.add_argument("--dry", action="store_true", help="no escribe policy.json")
    a = p.parse_args(argv)
    out = Path(a.data) / "lfm_tuner"
    if a.cmd == "report": report(out); return 0
    problems = check(a.data, HERE / "live.py")
    for x in problems: print("PROBLEMA:", x)
    if a.cmd == "check": print("ok" if not problems else "no arrancar hasta resolverlo"); return 1 if problems else 0
    if problems and not a.dry: return 1
    t = Tuner(a.data, json.loads(Path(a.coef).read_text()), out, a.round_min * 60, a.margin, a.z, None, a.min_requests, a.dry)
    def stop(*_): t.stop = True; print("parando al final de esta espera...", flush=True)
    signal.signal(signal.SIGINT, stop); signal.signal(signal.SIGTERM, stop)
    t.run(a.rounds, parse_until(a.until) if a.until else None, a.finish)
    return 0


if __name__ == "__main__":
    sys.exit(main())
