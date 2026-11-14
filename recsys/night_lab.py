"""night_lab — rota variantes del writer único durante la noche y las mide contra el leaderboard (T-016).

    python night_lab.py check  --arms v1,qrank,qrank+home            # valida el plan contra live.py; no escribe nada
    python night_lab.py run    --arms v1,qrank,qrank+home --until 08:30
    python night_lab.py run    --arms v1,qrank --dry-run              # hace todo menos escribir policy.json / d130.json
    python night_lab.py report                                        # reconstruye la tabla desde los logs

Qué hace `run`: cada bloque (65 min por defecto) escribe `data/policy.json` ({"variant": ...}) y, si algún brazo lo
usa, `data/d130.json` ({"mode": ...}); el writer (`live.py`) los relee en caliente. Cada minuto guarda el snapshot
público del leaderboard. Al acabar cada bloque actualiza `data/night_lab/report.md`.

Qué NO hace: no importa `live.py`, no usa la API key, no habla con RawTree y no escribe en `team_26.submissions`.
Solo lee https://datathon.rawtree.dev/api/state (público) y escribe esos dos JSON y sus propios logs.

Un brazo es `variante` o `variante+modo_d130`, por ejemplo `qrank_aff+home`. Sin `+modo`, d130 queda en `off`.

Medida (verificado el 14/11 13:25 UTC: el leaderboard se recalcula cada 60 s sobre la última hora exacta):
  * directa: snapshots cuya ventana de 1 h cae entera dentro del bloque, pasados `--settle-min` desde el cambio.
    No necesita ningún supuesto. Por eso el bloque por defecto dura 65 min (60 + 3 de asentamiento + 2 de margen).
  * ajuste: mínimos cuadrados sobre todos los snapshots (cada ventana es una mezcla de bloques). Sirve para bloques
    cortos o abortados, pero supone conversión constante dentro de cada bloque y en la hora previa. Es una estimación.
  Siempre se compara con las filas `baseline` y `reference` de la MISMA ventana: lift = conv - baseline (en puntos),
  norm = lift / (reference - baseline). `lift_ot` = lift / on_time: lift de lo que llegó a tiempo (lo tardío lo sirve
  el baseline), para separar la calidad del ranking de los problemas de latencia.

Guardia: si el on_time o el lift implícitos del bloque caen mucho respecto al brazo seguro (su medida de esta noche, o
la hora previa al laboratorio) durante `--guard-consec` snapshots seguidos, vuelve al mejor brazo hasta el final del
bloque y retira el brazo culpable. Al terminar (hora límite, Ctrl-C, SIGTERM o comienzo de la final) deja los dos
JSON como estaban antes de empezar (`--finish restore`): promocionar una variante lo decide el equipo.
"""
from __future__ import annotations
import argparse, json, os, re, signal, sys, time, urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path

STATE_URL = "https://datathon.rawtree.dev/api/state"
TEAM = "team_26"
HOUR = 3600.0
D130_MODES = ("off", "nodead", "home")
METRICS = ("lift", "norm", "lift_ot", "cold_lift", "on_time", "rev")


# ---------------------------------------------------------------- brazos y ficheros de política
@dataclass(frozen=True)
class Arm:
    name: str       # tal cual se escribió: "qrank+home"
    variant: str    # -> policy.json
    mode: str       # -> d130.json

def parse_arm(text):
    variant, _, mode = text.strip().partition("+")
    mode = mode or "off"
    if not variant or mode not in D130_MODES:
        raise ValueError(f"brazo no válido: {text!r} (formato variante[+{'|'.join(D130_MODES[1:])}])")
    return Arm(text.strip(), variant, mode)

def writer_support(live_py):
    """(variantes que acepta live.py en disco, ¿tiene el hook d130?). Variante desconocida = el writer la ignora."""
    text = Path(live_py).read_text(encoding="utf-8")
    found = re.findall(r"^VARIANTS\s*=\s*\(([^)]*)\)", text, flags=re.M)
    variants = tuple(re.findall(r"[\"']([\w-]+)[\"']", found[-1])) if found else ()
    return variants, "d130.install" in text

def check_plan(arms, live_py):
    """Lista de problemas (vacía = el writer en disco entiende todos los brazos)."""
    try: variants, has_d130 = writer_support(live_py)
    except OSError as e: return [f"no puedo leer {live_py}: {e}"]
    problems = []
    for a in dict.fromkeys(arms):
        if a.variant not in variants:
            problems.append(f"{a.name}: live.py no conoce la variante {a.variant!r} (conoce {', '.join(variants) or 'ninguna'})")
        if a.mode != "off" and not has_d130:
            problems.append(f"{a.name}: live.py no tiene el hook d130 (PR #3), el modo {a.mode!r} no haría nada")
    return problems

def write_json(path, obj):
    tmp = Path(str(path) + ".night_lab.tmp")
    tmp.write_text(json.dumps(obj) + "\n", encoding="utf-8")
    os.replace(tmp, path)      # atómico: el writer nunca lee un fichero a medias

def append(path, obj):
    with open(path, "a", encoding="utf-8") as f: f.write(json.dumps(obj) + "\n")

def read_jsonl(path):
    try: return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    except FileNotFoundError: return []


# ---------------------------------------------------------------- leaderboard
def fetch_state(url=STATE_URL, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "night-lab"})
    with urllib.request.urlopen(req, timeout=timeout) as r: return json.load(r)

def snapshot_row(state, team=TEAM):
    """Una fila plana por snapshot: el equipo frente a baseline y reference de la misma ventana."""
    t = next((x for x in state["teams"] if x["team_id"] == team), None)
    if t is None: return None
    b, r = state["baseline"], state["reference"]
    lift = t["conversion"] - b["conversion"]
    gap = r["conversion"] - b["conversion"]
    return dict(ts=state["updated_at"], w0=state["window"][0], w1=state["window"][1], lb_mode=state.get("mode"),
                final_start=state.get("final_start"), requests=t.get("requests"), version=t.get("model_version"),
                conv=t["conversion"], base=b["conversion"], ref=r["conversion"], lift=lift,
                norm=lift / gap if gap > 0 else None,
                lift_ot=lift / (t["on_time"] / 100) if t.get("on_time") else None,
                cold=t["cold_conversion"], cold_lift=t["cold_conversion"] - b["cold_conversion"],
                on_time=t["on_time"], rev=t["revenue_per_request"])


# ---------------------------------------------------------------- análisis (puro: solo listas de dicts)
def cells(segments, settle):
    """Cada segmento se parte en transición [t0, t0+settle) y limpio [t0+settle, t1)."""
    out = []
    for k, s in enumerate(segments):
        cut = min(s["t0"] + settle, s["t1"])
        out.append((k, "trans", s["t0"], cut)); out.append((k, "clean", cut, s["t1"]))
    return out

def overlap(a0, a1, b0, b1): return max(0.0, min(a1, b1) - max(a0, b0))

def direct(snaps, seg, settle):
    """Media de los snapshots cuya ventana cae entera en la parte limpia del segmento. None si no hay ninguno."""
    pure = [s for s in snaps if s["w0"] >= seg["t0"] + settle and s["w1"] <= seg["t1"]]
    if not pure: return None
    out = {m: _mean([s[m] for s in pure]) for m in METRICS + ("conv", "base", "ref")}
    out["n"] = len(pure); out["versions"] = sorted({s["version"] for s in pure if s.get("version")})
    return out

def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None

def fit(snaps, segments, settle, by_arm=False):
    """Mínimos cuadrados: metrica(snapshot) = suma(fracción de ventana en cada celda x valor de la celda).
    Devuelve {clave: {metrica: valor, 'w': peso total}}; clave = índice de segmento o brazo."""
    try: import numpy as np
    except ImportError: return {}
    if not snaps or not segments: return {}
    cs = cells(segments, settle)
    keys = [("pre",)] + sorted({("trans",)} | {((segments[k]["arm"],) if by_arm else (k,)) for k, kind, _, _ in cs if kind == "clean"}, key=str)
    col = {key: j for j, key in enumerate(keys)}
    first = segments[0]["t0"]
    A = np.zeros((len(snaps), len(keys)))
    for i, s in enumerate(snaps):
        A[i, col[("pre",)]] = overlap(s["w0"], s["w1"], -1e18, first) / HOUR
        for k, kind, c0, c1 in cs:
            key = ("trans",) if kind == "trans" else ((segments[k]["arm"],) if by_arm else (k,))
            A[i, col[key]] += overlap(s["w0"], s["w1"], c0, c1) / HOUR
    out = {key[0]: {"w": float(A[:, j].sum())} for key, j in col.items()}   # w = snapshots-hora que sostienen el valor
    for m in ("lift", "cold_lift", "on_time", "rev"):
        y = np.array([s[m] if s[m] is not None else np.nan for s in snaps]); ok = ~np.isnan(y)
        if ok.sum() < len(keys): continue
        x = np.linalg.lstsq(A[ok], y[ok], rcond=None)[0]
        for key, j in col.items(): out[key[0]][m] = float(x[j])
    return out

def analyze(snaps, segments, settle):
    """-> (filas por bloque, filas por brazo). Solo cuentan para la tabla por brazo los bloques completos."""
    per_block = fit(snaps, segments, settle)
    per_arm_fit = fit(snaps, segments, settle, by_arm=True)
    blocks = []
    for k, s in enumerate(segments):
        blocks.append(dict(k=k, arm=s["arm"], kind=s["kind"], status=s.get("status", "open"), t0=s["t0"], t1=s["t1"],
                           direct=direct(snaps, s, settle), fit=per_block.get(k)))
    arms = {}
    for b in blocks:
        if b["kind"] == "block" and b["status"] == "done" and b["direct"]: arms.setdefault(b["arm"], []).append(b["direct"])
    rows = []
    for arm in dict.fromkeys(s["arm"] for s in segments):
        ds = arms.get(arm, [])
        row = dict(arm=arm, blocks=len(ds), fit=per_arm_fit.get(arm))
        for m in METRICS: row[m] = _mean([d[m] for d in ds])
        lifts = [d["lift"] for d in ds]
        row["lift_min"], row["lift_max"] = (min(lifts), max(lifts)) if lifts else (None, None)
        rows.append(row)
    return blocks, rows

def best_arm(arm_rows, safe, ot_tolerance=10.0):
    """Mejor lift directo entre los brazos cuyo on_time no está más de `ot_tolerance` puntos por debajo del mejor."""
    ok = [r for r in arm_rows if r["blocks"] and r["lift"] is not None and r["on_time"] is not None]
    if not ok: return safe
    top_ot = max(r["on_time"] for r in ok)
    ok = [r for r in ok if r["on_time"] >= top_ot - ot_tolerance]
    return max(ok, key=lambda r: r["lift"])["arm"]

def _f(x, nd=3, pct=False):
    if x is None: return "—"
    return f"{100 * x:.0f}%" if pct else f"{x:.{nd}f}"

def _hm(ts): return time.strftime("%H:%M", time.localtime(ts))

def report_md(snaps, segments, settle, safe):
    blocks, arms = analyze(snaps, segments, settle)
    L = ["# night_lab — ablación en vivo contra el leaderboard", "",
         f"Generado {time.strftime('%Y-%m-%d %H:%M')} (hora local). {len(snaps)} snapshots, {len(segments)} segmentos. "
         "Evidencia: `LIVE FEEDBACK` (conversión esperada del modelo oculto, publicada por la organización).", "",
         "lift = conversión − baseline de la misma ventana (puntos). norm = lift / (reference − baseline). "
         "lift_ot = lift / on_time. Directo = ventanas de 1 h enteras dentro del bloque. Ajuste = mínimos cuadrados (estimación).", "",
         "## Por brazo (solo bloques completos, lectura directa)", "",
         "| brazo | bloques | lift | rango lift | norm | lift_ot | lift cold | on_time | €/petición | lift (ajuste) |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(arms, key=lambda r: -(r["lift"] if r["lift"] is not None else -9)):
        rng = f"{_f(r['lift_min'])}–{_f(r['lift_max'])}" if r["blocks"] > 1 else "—"
        L.append(f"| `{r['arm']}` | {r['blocks']} | {_f(r['lift'])} | {rng} | {_f(r['norm'], pct=True)} | {_f(r['lift_ot'])} | {_f(r['cold_lift'])} | "
                 f"{_f(r['on_time'], 1)} | {_f(r['rev'])} | {_f((r['fit'] or {}).get('lift'))} |")
    L += ["", f"Mejor brazo medido: **`{best_arm(arms, safe)}`** (brazo seguro: `{safe}`). "
          "Con un solo bloque por brazo la diferencia puede ser deriva del tráfico: mira el rango entre réplicas.", "",
          "## Por bloque", "",
          "| # | hora local | brazo | tipo | estado | n | conv | baseline | reference | lift | norm | on_time | lift (ajuste) | on_time (ajuste) | model_version |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for b in blocks:
        d, f = b["direct"] or {}, b["fit"] or {}
        L.append(f"| {b['k']} | {_hm(b['t0'])}–{_hm(b['t1'])} | `{b['arm']}` | {b['kind']} | {b['status']} | {d.get('n', 0)} | {_f(d.get('conv'))} | {_f(d.get('base'))} | "
                 f"{_f(d.get('ref'))} | {_f(d.get('lift'))} | {_f(d.get('norm'), pct=True)} | {_f(d.get('on_time'), 1)} | {_f(f.get('lift'))} | {_f(f.get('on_time'), 1)} | {', '.join(d.get('versions', [])) or '—'} |")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- el laboratorio
class Lab:
    def __init__(self, arms, data_dir, out_dir, safe, block_s=65 * 60, settle_s=180, deadline=None, dry=False, finish="restore",
                 guard_after_s=600, guard_ot_drop=10.0, guard_lift_drop=0.5, guard_consec=3, freeze_s=HOUR,
                 fetch=fetch_state, now=time.time, sleep=time.sleep, log=print):
        self.arms, self.safe, self.block_s, self.settle_s, self.deadline = list(arms), safe, block_s, settle_s, deadline
        self.dry, self.finish_mode = dry, finish
        self.guard_after_s, self.guard_ot_drop, self.guard_lift_drop, self.guard_consec, self.freeze_s = guard_after_s, guard_ot_drop, guard_lift_drop, guard_consec, freeze_s
        self.fetch, self.now, self.sleep, self.log = fetch, now, sleep, log
        self.policy, self.d130 = Path(data_dir) / "policy.json", Path(data_dir) / "d130.json"
        self.out = Path(out_dir); self.out.mkdir(parents=True, exist_ok=True)
        self.snap_path, self.seg_path, self.report_path = self.out / "snapshots.jsonl", self.out / "segments.jsonl", self.out / "report.md"
        self.uses_d130 = any(a.mode != "off" for a in self.arms + [safe])
        self.snaps, self.segments = read_jsonl(self.snap_path), read_jsonl(self.seg_path)
        self.last, self.next_update, self.banned, self.stop, self.pre = (self.snaps[-1] if self.snaps else None), 0.0, set(), None, {}
        self.original = {p: (p.read_text(encoding="utf-8") if p.exists() else None) for p in (self.policy, self.d130)}

    # -- ficheros de política: lo único que el laboratorio cambia fuera de su carpeta de logs
    def apply(self, arm):
        self.log(f"[{_hm(self.now())}] -> {arm.name}  (policy.json variant={arm.variant}" + (f", d130.json mode={arm.mode})" if self.uses_d130 else ")") + ("  [dry-run: no escribo]" if self.dry else ""))
        if self.dry: return
        write_json(self.policy, {"variant": arm.variant})
        if self.uses_d130: write_json(self.d130, {"mode": arm.mode})

    def restore(self):
        if self.dry: return
        for p, text in self.original.items():
            if p is self.d130 and not self.uses_d130: continue
            if text is None: p.unlink(missing_ok=True)
            else: p.write_text(text, encoding="utf-8")

    # -- leaderboard
    def poll(self):
        """Espera al siguiente recálculo y devuelve el snapshot nuevo (None si no hay o falla la descarga)."""
        self.sleep(min(90.0, max(5.0, self.next_update + 3 - self.now())))
        try: state = self.fetch()
        except Exception as e:
            self.log(f"[{_hm(self.now())}] leaderboard no disponible: {type(e).__name__}"); self.next_update = self.now() + 30; return None
        self.next_update = state.get("next_update") or self.now() + 60
        if self.next_update < self.now(): self.next_update = self.now() + 20
        row = snapshot_row(state)
        if row is None or (self.last and row["ts"] <= self.last["ts"]): return None
        if row["lb_mode"] != "practice": self.stop = f"el leaderboard ya no está en práctica (mode={row['lb_mode']})"
        elif row["final_start"] and self.now() > row["final_start"] - self.freeze_s: self.stop = "falta menos del margen de congelación para la final"
        row["arm"] = self.segments[-1]["arm"] if self.segments and self.segments[-1].get("status") == "open" else None
        self.snaps.append(row); self.last = row; append(self.snap_path, row)
        return row

    def save_segments(self):
        tmp = Path(str(self.seg_path) + ".tmp")
        tmp.write_text("".join(json.dumps(s) + "\n" for s in self.segments), encoding="utf-8"); os.replace(tmp, self.seg_path)

    def open_segment(self, arm, kind, until, reason=""):
        self.apply(arm)
        self.segments.append(dict(arm=arm.name, kind=kind, t0=self.now(), t1=until, status="open", reason=reason, dry=self.dry,
                                  start={m: self.last[m] for m in ("lift", "on_time")} if self.last else None))
        self.save_segments()

    def close_segment(self, status):
        s = self.segments[-1]; s["t1"] = min(s["t1"], self.now()) if status != "done" else s["t1"]; s["status"] = status
        self.save_segments(); self.write_report()

    def write_report(self):
        self.report_path.write_text(report_md(self.snaps, self.segments, self.settle_s, self.safe.name), encoding="utf-8")

    # -- guardia
    def reference(self):
        """(lift, on_time) del brazo seguro: su media medida esta noche o, si aún no hay, la hora previa al laboratorio.
        La vara de medir es el brazo seguro y no el mejor, para que la guardia no retire el control por ser peor."""
        _, rows = analyze(self.snaps, self.segments, self.settle_s)
        row = next((r for r in rows if r["arm"] == self.safe.name and r["blocks"]), None)
        if row: return row["lift"], row["on_time"]
        return self.pre.get("lift"), self.pre.get("on_time")

    def fallback(self):
        """Brazo al que volver: el mejor medido esta noche, o el seguro si aún no hay medidas."""
        name = best_arm(analyze(self.snaps, self.segments, self.settle_s)[1], self.safe.name)
        return next(a for a in self.arms + [self.safe] if a.name == name)

    def implied(self, seg, row, metric):
        """Valor del bloque que explica el movimiento de la media horaria, suponiendo que lo que sale de la ventana valía lo del inicio."""
        start, el = (seg.get("start") or {}).get(metric), row["ts"] - seg["t0"]
        if start is None or el <= 0: return None
        return row[metric] if el >= HOUR else start + (row[metric] - start) * HOUR / el

    def guard_trips(self, seg, row):
        if row["ts"] - seg["t0"] < self.guard_after_s: return None
        if seg["arm"] in (self.safe.name, self.fallback().name): return None   # el control no se retira; y no hay a dónde volver
        ref_lift, ref_ot = self.reference(); ref_arm = self.safe.name
        ot, lift = self.implied(seg, row, "on_time"), self.implied(seg, row, "lift")
        if ot is not None and ref_ot is not None and ot < ref_ot - self.guard_ot_drop:
            return f"on_time implícito {ot:.1f} frente a {ref_ot:.1f} de la referencia ({ref_arm})"
        if lift is not None and ref_lift is not None and ref_lift > 0 and lift < ref_lift * (1 - self.guard_lift_drop):
            return f"lift implícito {lift:.3f} frente a {ref_lift:.3f} de la referencia ({ref_arm})"
        return None

    # -- bucle principal
    def run_block(self, arm):
        end = self.now() + self.block_s
        self.open_segment(arm, "block", end); trips = 0
        while self.now() < end and not self.stop:
            row = self.poll()
            seg = self.segments[-1]
            if row is None or seg["kind"] != "block": continue
            self.log(f"[{_hm(self.now())}] {seg['arm']:<16} conv {row['conv']:.3f}  base {row['base']:.3f}  ref {row['ref']:.3f}  lift {row['lift']:+.3f}  on_time {row['on_time']:.1f}  {row['version']}")
            why = self.guard_trips(seg, row)
            trips = trips + 1 if why else 0
            if trips >= self.guard_consec:
                back = self.fallback()
                self.log(f"[{_hm(self.now())}] GUARDIA: {why}. Retiro {arm.name} y vuelvo a {back.name} hasta el final del bloque.")
                self.close_segment("aborted"); self.segments[-1]["reason"] = why; self.banned.add(arm.name)
                self.open_segment(back, "revert", end, reason=why)
        self.close_segment("done" if self.now() >= end else "interrupted")

    def run(self):
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
        self.log(f"night_lab: {len(self.arms)} brazos en rotación, bloques de {self.block_s / 60:.0f} min, hasta {_hm(self.deadline) if self.deadline else 'Ctrl-C'}" + ("  [DRY-RUN]" if self.dry else ""))
        try:
            self.next_update = 0; self.pre = self.poll() or {}      # hora previa: referencia inicial de la guardia
            k = 0
            while not self.stop:
                if all(a.name in self.banned for a in self.arms): self.stop = "todos los brazos retirados por la guardia"; break
                if self.deadline and self.now() + self.block_s > self.deadline: self.stop = "no cabe otro bloque antes de la hora límite"; break
                arm = self.arms[k % len(self.arms)]; k += 1
                if arm.name not in self.banned: self.run_block(arm)      # un brazo retirado se salta; el orden del resto no cambia
        except KeyboardInterrupt:
            self.stop = "interrumpido"
            if self.segments and self.segments[-1]["status"] == "open": self.close_segment("interrupted")
        finally:
            self.finish()

    def finish(self):
        best = self.fallback().name
        if self.finish_mode == "restore": self.restore(); left = "policy.json y d130.json como estaban antes de empezar"
        else:
            arm = self.safe if self.finish_mode == "safe" else self.fallback()
            self.apply(arm); left = f"el writer en {arm.name}"
        self.write_report()
        self.log(f"night_lab terminado ({self.stop}). Dejo {left}. Mejor brazo medido: {best}. Tabla: {self.report_path}")


# ---------------------------------------------------------------- CLI
def parse_until(text, now=None):
    """'08:30' -> próximo instante con esa hora local (epoch)."""
    now = time.time() if now is None else now
    h, m = (int(x) for x in text.split(":"))
    lt = time.localtime(now)
    t = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, h, m, 0, 0, 0, -1))
    return t if t > now else t + 86400

def lock(out_dir):
    """Un solo laboratorio a la vez: dos rotando a la vez invalidarían la noche."""
    path = Path(out_dir) / "lab.pid"
    try:
        pid = int(path.read_text())
        os.kill(pid, 0); sys.exit(f"ya hay un night_lab corriendo (pid {pid}). Si no es así, borra {path}")
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError): pass
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(str(os.getpid()))
    return path

def main(argv=None):
    here = Path(__file__).resolve().parent
    p = argparse.ArgumentParser(description="Rota variantes del writer único y las mide contra el leaderboard. Nunca escribe en RawTree.")
    p.add_argument("cmd", choices=("check", "run", "report"))
    p.add_argument("--arms", default="v1,qrank", help="brazos en orden de rotación, p. ej. v1,qrank,qrank+home,qrank_aff+home")
    p.add_argument("--safe", default="v1", help="brazo al que volver si la guardia salta antes de tener medidas (por defecto v1)")
    p.add_argument("--block-min", type=float, default=65, help="duración del bloque; 65 o más permite la lectura directa")
    p.add_argument("--settle-min", type=float, default=3, help="minutos tras el cambio que no cuentan como bloque limpio")
    p.add_argument("--until", default="08:30", help="hora local límite HH:MM; no empieza bloques que no quepan")
    p.add_argument("--finish", choices=("restore", "safe", "best"), default="restore", help="qué dejar al terminar (por defecto, lo que había)")
    p.add_argument("--guard-after-min", type=float, default=10)
    p.add_argument("--guard-on-time-drop", type=float, default=10, help="puntos de on_time por debajo de la referencia")
    p.add_argument("--guard-lift-drop", type=float, default=0.5, help="fracción del lift de referencia perdida")
    p.add_argument("--guard-consec", type=int, default=3, help="snapshots seguidos necesarios para saltar")
    p.add_argument("--freeze-min", type=float, default=60, help="para si falta menos de esto para la final")
    p.add_argument("--data-dir", default=str(here / "data")); p.add_argument("--out", default=None, help="carpeta de logs (por defecto data/night_lab)")
    p.add_argument("--live-py", default=str(here / "live.py"))
    p.add_argument("--force", action="store_true", help="arrancar aunque live.py en disco no entienda algún brazo")
    p.add_argument("--dry-run", action="store_true", help="no escribe policy.json ni d130.json")
    a = p.parse_args(argv)
    out = Path(a.out) if a.out else Path(a.data_dir) / "night_lab"
    settle = a.settle_min * 60
    if a.cmd == "report":
        md = report_md(read_jsonl(out / "snapshots.jsonl"), read_jsonl(out / "segments.jsonl"), settle, a.safe)
        (out / "report.md").write_text(md, encoding="utf-8"); print(md); return 0
    arms, safe = [parse_arm(x) for x in a.arms.split(",") if x.strip()], parse_arm(a.safe)
    problems = check_plan(arms + [safe], a.live_py)
    deadline = parse_until(a.until)
    n = int((deadline - time.time()) // (a.block_min * 60))
    print(f"Plan: {n} bloques de {a.block_min:g} min hasta las {a.until}: " + " → ".join(arms[k % len(arms)].name for k in range(n)))
    if a.block_min < 60 + a.settle_min: print("Aviso: con bloques de menos de 60 min + asentamiento no hay lectura directa, solo el ajuste (estimación).")
    for x in problems: print("PROBLEMA:", x)
    if a.cmd == "check": return 1 if problems else 0
    if problems and not a.force and not a.dry_run: print("No arranco. Corrige el plan o usa --force."); return 1
    pid = lock(out)
    try:
        Lab(arms, a.data_dir, out, safe, block_s=a.block_min * 60, settle_s=settle, deadline=deadline, dry=a.dry_run, finish=a.finish,
            guard_after_s=a.guard_after_min * 60, guard_ot_drop=a.guard_on_time_drop, guard_lift_drop=a.guard_lift_drop,
            guard_consec=a.guard_consec, freeze_s=a.freeze_min * 60).run()
    finally: pid.unlink(missing_ok=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
