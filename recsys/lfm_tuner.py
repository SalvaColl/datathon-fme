"""lfm_tuner — afina los pesos de lfm contra el leaderboard, por rondas, sin tocar RawTree (T-021, D-211; T-023b, D-231).

En cristiano: las compras reales ya no distinguen una versión de lfm de otra (I-211), pero el leaderboard da la
conversión del modelo oculto por `model_version` y por ventana exacta. Este script parte del CAMPEÓN que está puesto
en `data/policy.json` y prueba, ronda a ronda, si mover UN peso mejora a UNA cohorte, sin tocar nada más:

  1. Campeón = el brazo de `lfm_arms` que está sirviendo (o `--champion TAG` si hay varios; sin `lfm_arms`, los pesos
     publicados). Se copia entero: fichero de pesos, ajustes por segmento, pesos de home y cualquier otra clave.
  2. Cohorte (`--cohort`, obligatoria): qué tráfico se optimiza y qué etiqueta se lee. `known-pages` = usuarios que
     vuelven en páginas de producto/categoría (etiqueta `-k`, sin home). Solo se mueven pesos de esa cohorte; el
     otro segmento y home quedan idénticos al campeón en TODOS los brazos.
  3. Ronda de búsqueda: referencia (el campeón, siempre el mismo brazo y la misma etiqueta), control (lo mejor
     confirmado, si ya difiere del campeón), "más" y "menos" (control con un peso movido +paso / -paso).
  4. Se lee UNA ventana exacta y común a todos los brazos (múltiplos de 5 min, después de activar y calentar). Si el
     leaderboard devuelve otra ventana o falta la fila de un brazo, el dato NO está disponible: nunca cuenta como 0.
  5. Un brazo que gana al control por más que el ruido NO se promociona todavía: la ronda siguiente es un bloque de
     confirmación (referencia, control, candidato) en una ventana nueva. Solo si vuelve a ganar pasa a ser el mejor.
  6. Convivencia: un único controlador de `policy.json` (cerrojo `data/policy_controller.lock` + `data/policy_owner.json`).
     Si alguien cambia `policy.json` (una prueba manual, otro controlador), el afinador para SIN escribir nada.

Solo escribe la clave `lfm_arms` de `data/policy.json` (el resto de claves no se toca) y sus logs en
`data/lfm_tuner/`. No es un writer: `live.py` tiene que estar corriendo con la variante `lfm`.

    python lfm_tuner.py check --cohort known-pages            # campeón capturado y brazos de la primera ronda; no escribe
    python lfm_tuner.py run --cohort known-pages --until 08:30
    python lfm_tuner.py run --cohort known-pages --rounds 1 --dry     # ensayo: no escribe policy.json
    python lfm_tuner.py report

Al terminar (`--finish best`, por defecto) deja un solo brazo `best` = campeón + cambios CONFIRMADOS, con el mismo
home; si no se confirmó nada, o con `--finish restore`, deja `lfm_arms` exactamente como estaba al arrancar.
El estado guardado lleva una huella del campeón, los pesos base, las features y la cohorte: con otra huella no se
retoma (`--fresh` archiva el estado viejo y empieza de cero).
"""
from __future__ import annotations
import argparse, hashlib, json, math, os, signal, sys, time, urllib.request, zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE_URL = "https://datathon.rawtree.dev/api/state?by=model"
TEAM = "team_26"
OWNER = "lfm_tuner"
# Cohorte -> (segmento cuyos pesos se mueven, sufijo de la etiqueta que se lee, ¿son peticiones de home?)
COHORTS = {"known-pages": ("known", "-k", False), "new-pages": ("new", "-n", False),
           "known-home": ("known", "-kh", True), "new-home": ("new", "-nh", True)}
# Orden de búsqueda por cohorte: (peso, paso inicial). En usuarios que vuelven, primero el reparto de categorías
# (E-260: ucat 1,5 y usub 0,7). En páginas con vistas no aparecen `hcart` ni `home`: allí valen 0 y moverlos no cambia nada.
PLAN = {
    "known-pages": [("ucat", 1.5), ("usub", 0.7), ("aff10", 0.5), ("islast", 0.7), ("chn", 0.5), ("scat2", 0.5), ("ssub2", 0.5),
                    ("oinrv", 0.7), ("lq", 0.25), ("cl", 0.7), ("bsub", 0.4), ("na", 0.3), ("p40", 0.5)],
    "new-pages": [("ucat", 1.0), ("aff10", 0.4), ("cl", 0.7), ("nbp", 0.5), ("bsub", 0.5), ("islast", 0.7), ("scat2", 0.5), ("ssub2", 0.5),
                  ("oinrv", 0.7), ("lq", 0.25), ("segcheap", 0.4), ("na", 0.3)],
    "known-home": [("hcart", 1.0), ("ucat", 1.5), ("usub", 0.7), ("aff10", 0.5), ("chn", 0.5), ("lq", 0.25), ("cl", 0.7)],
    "new-home": [("hcart", 1.0), ("ucat", 1.0), ("aff10", 0.4), ("cl", 0.7), ("nbp", 0.5), ("lq", 0.25)],
}
W_LIMIT = 15.0
STEP, WIN_MIN, WIN_MAX = 300, 900, 10800            # límites de ventana del leaderboard (api/state: limits)
# Desviación típica por petición de la conversión esperada (puntos), medida el 14-nov con ventanas de 5-10 min del
# propio leaderboard: ~3.5 para usuarios que vuelven, ~5-6.5 para nuevos. No es significación estadística formal:
# es el margen de ruido de UNA ronda; la confirmación en ventana nueva es la que protege de elegir el máximo por azar.
SD = {"known": 4.0, "new": 6.0}


class Foreign(Exception):
    """policy.json cambió sin que lo escribiera el afinador, u otro controlador es el dueño: parar sin escribir."""


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

def window_after(t, warmup_s, length_s):
    """Primera ventana exacta [inicio, fin) que empieza al menos `warmup_s` después de `t` (bordes en múltiplos de 5 min)."""
    start = int(math.ceil((t + warmup_s) / STEP) * STEP)
    return start, start + int(length_s)

def read_row(state, tag, suffix, window, labels=None, team=TEAM):
    """(peticiones, conversión %) de un brazo en la cohorte, o None si el dato NO está disponible: el leaderboard
    devolvió otra ventana, falta la fila (menos peticiones que su mínimo, brazo que no sirvió) o la fila se paró
    antes del final de la ventana. None nunca se convierte en 0."""
    if [int(x) for x in (state.get("window") or [])] != [int(window[0]), int(window[1])]: return None
    rows = next((t.get("versions", []) for t in state.get("teams", []) if t.get("team_id") == team), [])
    v = next((v for v in rows if v.get("model_version") == public_label(f"v3-lfm-{tag}{suffix}", labels)), None)
    if not v or not v.get("requests") or v.get("conversion") is None: return None
    if v.get("last") is not None and v["last"] < window[1] - 2 * STEP: return None          # dejó de servir a mitad de ventana
    return int(v["requests"]), float(v["conversion"])


# ---- campeón ----
def spec_of(arm):
    """Parte de un brazo que define sus pesos principales: todo menos la etiqueta y `home`."""
    return {k: v for k, v in (arm or {}).items() if k not in ("tag", "home")}

def capture_champion(policy, tag=None):
    """-> (brazo campeón tal cual está en policy.json, lista original de lfm_arms). Sin brazos: pesos publicados."""
    arms = list(policy.get("lfm_arms") or [])
    if not arms:
        if tag: raise SystemExit(f"--champion {tag}: policy.json no tiene lfm_arms")
        return {"tag": "ref"}, arms
    if tag:
        hit = [a for a in arms if a.get("tag") == tag]
        if len(hit) != 1: raise SystemExit(f"--champion {tag}: no hay exactamente un brazo con esa etiqueta en policy.json")
        return json.loads(json.dumps(hit[0])), arms
    if len(arms) > 1:
        raise SystemExit("policy.json tiene varios brazos (" + ", ".join(str(a.get("tag")) for a in arms) + "): indica cuál es el campeón con --champion TAG")
    return json.loads(json.dumps(arms[0])), arms

def fingerprint(champion, cohort, coef_dir, feats):
    """Huella de todo lo que da sentido al estado guardado: campeón (pesos, ajustes, home y demás claves), contenido
    de sus ficheros de pesos, lista de features, cohorte y plan de búsqueda."""
    files = {}
    for sp in (champion, champion.get("home") or {}):
        name = sp.get("file") or "lfm_coef.json"
        c = json.loads((Path(coef_dir) / name).read_text())
        files[name] = {s: dict(w=c[s]["w"], b=c[s]["b"]) for s in ("known", "new")}
    blob = json.dumps(dict(champion={k: v for k, v in champion.items() if k != "tag"}, files=files, feats=list(feats), cohort=cohort,
                           plan=PLAN[cohort], limit=W_LIMIT), sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


class Tuner:
    def __init__(self, data_dir, cohort, champion_tag=None, coef_dir=HERE, out_dir=None, window_s=30 * 60, warmup_s=60, settle_s=120,
                 margin=0.15, z=1.5, sd=None, min_requests=250, dry=False, fresh=False, feats=None,
                 fetch_fn=fetch, now=time.time, sleep=time.sleep, log=print):
        if cohort not in COHORTS: raise SystemExit(f"cohorte desconocida: {cohort!r}; opciones: {', '.join(COHORTS)}")
        if window_s % STEP or not WIN_MIN <= window_s <= WIN_MAX: raise SystemExit("la ventana tiene que ser múltiplo de 5 min, entre 15 min y 3 h")
        self.data = Path(data_dir); self.out = Path(out_dir or self.data / "lfm_tuner"); self.out.mkdir(parents=True, exist_ok=True)
        self.cohort = cohort; self.seg, self.suffix, self.home = COHORTS[cohort]
        self.window_s, self.warmup_s, self.settle_s = int(window_s), warmup_s, settle_s
        self.margin, self.z, self.min_requests, self.dry = margin, z, min_requests, dry
        self.sd = {**SD, **(sd or {})}
        self.fetch, self.now, self.sleep, self.log = fetch_fn, now, sleep, log
        self.policy_path = self.data / "policy.json"
        self.seen = read_json(self.policy_path, {}) or {}              # policy.json tal y como lo vimos / escribimos por última vez
        self.champion, self.original = capture_champion(self.seen, champion_tag)
        if feats is None:
            import lfm; feats = lfm.FEATS
        self.feats = list(feats)
        # pesos de partida de la cohorte: fichero del campeón (el de home si la cohorte es home) + sus ajustes
        src = (self.champion.get("home") if self.home and "home" in self.champion else self.champion) or {}
        coef = json.loads((Path(coef_dir) / (src.get("file") or "lfm_coef.json")).read_text())
        self.base = {**coef[self.seg]["w"], **((src.get("w") or {}).get(self.seg) or {})}
        bad = [f for f, _ in PLAN[cohort] if f not in self.feats]
        if bad: raise SystemExit(f"el plan usa features que este lfm no tiene: {bad}")
        self.fp = fingerprint(self.champion, cohort, coef_dir, self.feats)
        st = read_json(self.out / "state.json")
        if st and st.get("fingerprint") != self.fp:
            if not fresh:
                raise SystemExit(f"el estado guardado en {self.out / 'state.json'} es de otro campeón, otros pesos base u otra cohorte "
                                 f"(huella {st.get('fingerprint')} != {self.fp}). No lo retomo: usa --fresh para archivarlo y empezar de cero.")
            os.replace(self.out / "state.json", self.out / f"state.{st.get('fingerprint') or 'old'}.{int(self.now())}.json"); st = None
        st = st or {}
        self.best = st.get("best") or {}             # pesos CONFIRMADOS que difieren del campeón (solo los de la cohorte)
        self.pending = st.get("pending")             # {"f", "value", "step"}: ganó una búsqueda y espera su bloque de confirmación
        self.pos = int(st.get("pos", 0)); self.scale = float(st.get("scale", 1.0)); self.round = int(st.get("round", 0))
        self.stop = False; self.guard = None

    # ---- pesos y brazos ----
    def weight(self, f, over=None): return float({**self.base, **self.best, **(over or {})}.get(f, 0.0))

    def arm(self, tag, over):
        """Brazo = campeón con `over` (pesos de la cohorte) encima. Home queda IDÉNTICO al del campeón en todos los brazos:
        si la cohorte es de páginas, home lleva explícitamente los pesos de home del campeón (o sus pesos principales,
        que es lo que el campeón sirve en home cuando no tiene `home`)."""
        main = json.loads(json.dumps(spec_of(self.champion)))
        home = json.loads(json.dumps(self.champion["home"])) if "home" in self.champion else {k: v for k, v in main.items() if k in ("file", "w")}
        tgt = home if self.home else main
        if over:
            w = dict(tgt.get("w") or {}); w[self.seg] = {**(w.get(self.seg) or {}), **over}; tgt["w"] = w
        return {"tag": tag, **main, "home": home}

    def plan_step(self):
        f, step = PLAN[self.cohort][self.pos % len(PLAN[self.cohort])]
        return f, step * self.scale

    def arms_for_round(self):
        """-> (brazos para lfm_arms, descripción de la ronda). La referencia es SIEMPRE el brazo campeón sin tocar y va
        primero; el resto rota para que no les toque siempre el mismo grupo de usuarios."""
        r = self.round; ref = json.loads(json.dumps(self.champion)); clip = lambda v: round(max(-W_LIMIT, min(W_LIMIT, v)), 4)
        rest = [self.arm(f"c{r:03d}", dict(self.best))] if self.best else []          # control = mejor confirmado (si ya no es el campeón)
        if self.pending:
            p = self.pending; info = dict(kind="confirm", feature=p["f"], step=p["step"], value=p["value"])
            rest.append(self.arm(f"x{r:03d}", {**self.best, p["f"]: p["value"]}))
        else:
            f, step = self.plan_step(); info = dict(kind="search", feature=f, step=step, value=self.weight(f))
            rest += [self.arm(f"p{r:03d}", {**self.best, f: clip(self.weight(f) + step)}), self.arm(f"m{r:03d}", {**self.best, f: clip(self.weight(f) - step)})]
        k = r % len(rest); rest = rest[k:] + rest[:k]
        if ref["tag"] in {a["tag"] for a in rest}: raise SystemExit(f"la etiqueta del campeón ({ref['tag']}) choca con las del afinador")
        return [ref] + rest, info

    def final_arms(self, mode):
        if mode != "best" or not self.best: return json.loads(json.dumps(self.original))      # tal y como estaba al arrancar
        return [self.arm("best", dict(self.best))]

    # ---- policy.json: solo `lfm_arms`, y solo si nadie más lo ha tocado ----
    def foreign_change(self):
        return (read_json(self.policy_path, {}) or {}) != self.seen

    def set_arms(self, arms):
        if self.dry: self.log("  (dry) policy.json no se toca:", json.dumps(arms)); return
        if self.foreign_change(): raise Foreign("policy.json ha cambiado desde la última vez que lo escribí; no lo piso")
        pol = dict(self.seen)
        if arms: pol["lfm_arms"] = arms
        else: pol.pop("lfm_arms", None)
        write_json(self.policy_path, pol); self.seen = pol

    def save(self):
        write_json(self.out / "state.json", dict(fingerprint=self.fp, cohort=self.cohort, champion=self.champion, best=self.best,
                                                 pending=self.pending, pos=self.pos, scale=self.scale, round=self.round))

    # ---- una ronda ----
    def decide(self, ctrl, cand):
        """¿El candidato (n, conv) gana al control con margen de ruido? None en cualquiera = dato no disponible = no."""
        if ctrl is None or cand is None: return False, float("nan")
        (nc, cc), (nx, cx) = ctrl, cand
        if min(nc, nx) < self.min_requests: return False, float("nan")
        need = max(self.margin, self.z * self.sd[self.seg] * math.sqrt(1.0 / nc + 1.0 / nx))
        return (cx - cc) > need, need

    def wait_until(self, t):
        while self.now() < t and not self.stop:
            if not self.dry and self.foreign_change(): raise Foreign("policy.json ha cambiado durante la ronda; la ronda no vale y no lo piso")
            if self.guard: self.guard.beat(self.now())
            self.sleep(min(30, max(1, t - self.now())))

    def read_window(self, window, tries=5):
        """Estado del leaderboard para EXACTAMENTE esa ventana, o None si no lo da (se reintenta unas cuantas veces)."""
        for _ in range(tries):
            try:
                st = self.fetch(window[0], window[1])
                if [int(x) for x in (st.get("window") or [])] == list(window): return st
                self.log("  el leaderboard devolvió otra ventana:", st.get("window"), "pedida:", list(window))
            except Exception as e: self.log("  leaderboard no disponible:", type(e).__name__)
            if self.stop: break
            self.sleep(60)
        return None

    def run_round(self, labels=None):
        arms, info = self.arms_for_round()
        t0 = self.now(); self.set_arms(arms)
        window = window_after(t0, self.warmup_s, self.window_s)
        f = info["feature"]
        self.log(f"ronda {self.round} ({'confirmación' if info['kind'] == 'confirm' else 'búsqueda'}, {self.cohort}): {f} "
                 + (f"= {info['value']:+.2f}" if info["kind"] == "confirm" else f"{info['value']:+.2f} ± {info['step']:.2f}")
                 + f"; ventana {time.strftime('%H:%M', time.localtime(window[0]))}–{time.strftime('%H:%M', time.localtime(window[1]))}")
        self.wait_until(window[1] + self.settle_s)
        rec = dict(round=self.round, cohort=self.cohort, fingerprint=self.fp, written=t0, window=list(window), arms=arms, **info)
        if self.stop and self.now() < window[1]:
            rec["outcome"] = "interrupted"; self._log_round(rec); return rec          # ventana incompleta: no se lee
        state = self.read_window(window)
        res = {a["tag"]: (read_row(state, a["tag"], self.suffix, window, labels) if state else None) for a in arms}
        ref = arms[0]["tag"]; ctrl_tag = next((a["tag"] for a in arms if a["tag"].startswith("c") and a["tag"] != ref), ref)
        ctrl = res[ctrl_tag]; rec.update(results=res, reference=ref, control=ctrl_tag)
        ref_row = None
        if state and isinstance(state.get("reference"), dict) and state["reference"].get("conversion") is not None:
            ref_row = [state["reference"].get("requests"), state["reference"]["conversion"]]
        rec["global_reference"] = ref_row            # tráfico global de la misma ventana (no es la misma cohorte): solo contexto
        cands = [a["tag"] for a in arms if a["tag"] not in (ref, ctrl_tag)]
        if ctrl is None or all(res[t] is None for t in cands):
            rec["outcome"] = "unavailable"                      # nada cambia: ni se promociona ni se pasa al peso siguiente
        elif info["kind"] == "confirm":
            ok, need = self.decide(ctrl, res[cands[0]]); rec["need"] = need
            if ok: self.best[f] = self.pending["value"]; rec["outcome"] = "confirmed"            # y sigue empujando este peso
            else: self.pos += 1; rec["outcome"] = "not_confirmed"
            self.pending = None
        else:
            picked = None
            for t in cands:
                ok, need = self.decide(ctrl, res[t]); rec.setdefault("need", {})[t] = need
                if ok and (picked is None or res[t][1] > res[picked][1]): picked = t
            if picked:
                arm = next(a for a in arms if a["tag"] == picked); tgt = arm["home"] if self.home else arm
                self.pending = dict(f=f, value=tgt["w"][self.seg][f], step=info["step"]); rec["outcome"] = "candidate"; rec["picked"] = picked
            else:
                self.pos += 1; rec["outcome"] = "no_change"
        if rec["outcome"] in ("not_confirmed", "no_change") and self.pos % len(PLAN[self.cohort]) == 0: self.scale = max(0.25, self.scale / 2)
        fmt = lambda x: "sin dato" if x is None else f"{x[1]:.3f}% ({x[0]})"
        self.log("  " + "  ".join(f"{t}: {fmt(res[t])}" for t in res) + f"  -> {rec['outcome']}")
        self._log_round(rec); self.round += 1; self.save()
        return rec

    def _log_round(self, rec):
        with open(self.out / "rounds.jsonl", "a") as fh: fh.write(json.dumps(rec) + "\n")

    def run(self, rounds=None, deadline=None, finish="best", freeze_s=3600, max_unavailable=2):
        done = miss = 0; foreign = False
        round_s = self.window_s + self.warmup_s + self.settle_s + STEP
        try:
            if not self.dry: self.guard = Guard(self.data, self.cohort, self.now())
            while not self.stop and (rounds is None or done < rounds):
                if deadline and self.now() + round_s > deadline: self.log("no cabe otra ronda antes de la hora límite"); break
                try:
                    st = self.fetch(int(self.now() // STEP) * STEP - WIN_MIN)
                    if st.get("mode") != "practice" or st.get("final_start", 1e18) - self.now() < freeze_s + round_s:
                        self.log("fuera de práctica o demasiado cerca de la final: paro"); break
                except Exception as e: self.log("leaderboard no disponible, reintento en 60 s:", type(e).__name__); self.sleep(60); continue
                labels = read_json(self.data / "labels.json")
                rec = self.run_round(labels); done += 1
                miss = miss + 1 if rec["outcome"] == "unavailable" else 0
                if rec["outcome"] == "interrupted": break
                if miss >= max_unavailable: self.log("el leaderboard no da los datos de las rondas: paro"); break
        except Foreign as e:
            foreign = True; self.log("PARO SIN ESCRIBIR:", e)
        finally:
            try:
                if foreign or (not self.dry and self.foreign_change()):
                    self.log("fin. policy.json lo ha cambiado otro: lo dejo como está. Mejores pesos confirmados:", json.dumps(self.best))
                else:
                    arms = self.final_arms(finish); self.set_arms(arms)
                    self.log("fin. policy.json queda con lfm_arms =", json.dumps(arms) if arms else "(sin brazos, pesos publicados)")
            finally:
                if self.guard: self.guard.close(); self.guard = None


class Guard:
    """Un solo controlador de policy.json a la vez. Dos piezas, las dos locales a la máquina del writer:
    - `policy_controller.lock`: cerrojo del sistema operativo (el mismo `serving.WriterLock` que usa el writer); se
      suelta solo si el proceso muere.
    - `policy_owner.json`: quién manda y desde cuándo, legible por personas y por otros controladores. Para reservar
      policy.json a mano (por ejemplo una prueba de cold_lq) basta con crear ese fichero con otro `owner`: el afinador
      no arranca mientras exista."""
    def __init__(self, data_dir, cohort, now):
        from serving import WriterLock
        self.path = Path(data_dir) / "policy_owner.json"
        cur = read_json(self.path)
        if cur and cur.get("owner") != OWNER: raise Foreign(f"policy.json está reservado por {cur.get('owner')!r} ({self.path.name}); no arranco")
        try: self.lock = WriterLock(Path(data_dir) / "policy_controller.lock")
        except Exception as e: raise Foreign(f"ya hay otro controlador de policy.json en marcha ({type(e).__name__})")
        self.info = dict(owner=OWNER, pid=os.getpid(), cohort=cohort, since=now, heartbeat=now); write_json(self.path, self.info)
    def beat(self, now):
        self.info["heartbeat"] = now; write_json(self.path, self.info)
    def close(self):
        try:
            if (read_json(self.path) or {}).get("pid") == os.getpid(): self.path.unlink()
        except OSError: pass
        self.lock.close()


def report(out_dir):
    rows = [json.loads(l) for l in (Path(out_dir) / "rounds.jsonl").read_text().splitlines() if l.strip()] if (Path(out_dir) / "rounds.jsonl").exists() else []
    print("| Ronda | Ventana | Cohorte | Tipo | Peso | Valor / paso | Brazos: conversión (peticiones) | Resultado |\n|---|---|---|---|---|---:|---|---|")
    for r in rows:
        if "window" not in r: continue                       # rondas del formato anterior a T-023b
        w = "–".join(time.strftime("%H:%M", time.localtime(t)) for t in r["window"])
        res = "; ".join(f"{t}: " + ("sin dato" if x is None else f"{x[1]:.2f}% ({x[0]})") for t, x in (r.get("results") or {}).items())
        val = f"{r['value']:.2f}" if r["kind"] == "confirm" else f"{r['value']:.2f} ± {r['step']:.2f}"
        print(f"| {r['round']} | {w} | {r['cohort']} | {r['kind']} | {r['feature']} | {val} | {res} | {r['outcome']} |")
    st = read_json(Path(out_dir) / "state.json") or {}
    print(f"\nCohorte {st.get('cohort')}, huella {st.get('fingerprint')}. Pesos confirmados que difieren del campeón:", json.dumps(st.get("best", {})),
          "| pendiente de confirmar:", json.dumps(st.get("pending")))


def check(data_dir, live_py):
    problems = []
    try:
        text = Path(live_py).read_text(encoding="utf-8")
        if "lfm_arms" not in text: problems.append("live.py en disco no entiende lfm_arms (falta el PR #11)")
        if "@home" not in Path(live_py).with_name("lfm.py").read_text(encoding="utf-8"): problems.append("lfm.py en disco no entiende brazos con `home` (falta T-025)")
    except OSError as e: problems.append(f"no puedo leer {live_py}: {e}")
    pol = read_json(Path(data_dir) / "policy.json", {}) or {}
    if pol.get("variant") != "lfm": problems.append(f"policy.json tiene variant={pol.get('variant')!r}; el afinador necesita 'lfm'")
    own = read_json(Path(data_dir) / "policy_owner.json")
    if own and own.get("owner") != OWNER: problems.append(f"policy.json está reservado por {own.get('owner')!r} (policy_owner.json)")
    return problems


def parse_until(text, now=None):
    now = now or time.time(); h, m = (int(x) for x in text.split(":"))
    t = time.mktime(time.localtime(now)[:3] + (h, m, 0, 0, 0, -1))
    return t if t > now else t + 86400


def main(argv=None):
    p = argparse.ArgumentParser(description="Afina los pesos de lfm por rondas contra el leaderboard. Nunca escribe en RawTree.")
    p.add_argument("cmd", choices=("check", "run", "report"))
    p.add_argument("--data", default=str(HERE / "data"))
    p.add_argument("--cohort", choices=tuple(COHORTS), default=None, help="tráfico que se optimiza (obligatoria en run)")
    p.add_argument("--champion", default=None, help="etiqueta del brazo campeón cuando policy.json tiene varios")
    p.add_argument("--window-min", type=float, default=30, help="ventana de lectura, múltiplo de 5 min")
    p.add_argument("--warmup-s", type=float, default=60); p.add_argument("--settle-s", type=float, default=120)
    p.add_argument("--rounds", type=int, default=None)
    p.add_argument("--until", default=None, help="hora local HH:MM; no empieza rondas que no quepan")
    p.add_argument("--margin", type=float, default=0.15, help="ventaja mínima en puntos de conversión para aceptar un cambio")
    p.add_argument("--z", type=float, default=1.5, help="cuántas veces el error típico tiene que ganar un brazo al control")
    p.add_argument("--min-requests", type=int, default=250)
    p.add_argument("--finish", choices=("best", "restore", "off"), default="best", help="off = restore (compatibilidad)")
    p.add_argument("--fresh", action="store_true", help="archiva un estado guardado incompatible y empieza de cero")
    p.add_argument("--dry", action="store_true", help="no escribe policy.json")
    a = p.parse_args(argv)
    out = Path(a.data) / "lfm_tuner"
    if a.cmd == "report": report(out); return 0
    problems = check(a.data, HERE / "live.py")
    for x in problems: print("PROBLEMA:", x)
    if a.cmd == "check":
        if a.cohort:
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:           # estado vacío y desechable: check no escribe nada en data/
                t = Tuner(a.data, a.cohort, a.champion, dry=True, out_dir=tmp)
                arms, info = t.arms_for_round()
            print("campeón:", json.dumps(t.champion), "| huella", t.fp); print("primera ronda:", json.dumps(info)); print(json.dumps({"lfm_arms": arms}))
        print("ok" if not problems else "no arrancar hasta resolverlo"); return 1 if problems else 0
    if not a.cohort: p.error("run necesita --cohort (por ejemplo known-pages)")
    if problems and not a.dry: return 1
    t = Tuner(a.data, a.cohort, a.champion, HERE, out, a.window_min * 60, a.warmup_s, a.settle_s, a.margin, a.z, None, a.min_requests, a.dry, a.fresh)
    def stop(*_): t.stop = True; print("parando al final de esta espera...", flush=True)
    signal.signal(signal.SIGINT, stop); signal.signal(signal.SIGTERM, stop)
    t.run(a.rounds, parse_until(a.until) if a.until else None, "restore" if a.finish == "off" else a.finish)
    return 0


if __name__ == "__main__":
    sys.exit(main())
