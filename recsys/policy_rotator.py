"""policy_rotator — alterna políticas completas de lfm en bloques fijos (T-042; seguridad y verificación T-044).

    python policy_rotator.py check --plan r3,cx3,r3,og1 --block-min 15 --until "2026-11-15 07:00"
    python policy_rotator.py run   --plan r3,cx3,r3,og1 --block-min 15 --until "2026-11-15 07:00" --epoch e2

Cada nombre del plan es un fichero `policy.rot_<nombre>.json` junto a este script (una política entera, normalmente de
un solo brazo). `run` espera al siguiente múltiplo de 5 minutos UTC (o a `--start`), copia el fichero a
`data/policy.json` (escritura atómica; el writer lo relee en caliente) y repite el plan en bucle hasta `--until`. Cada
cambio queda en `data/policy_changes.log` con hora UTC y motivo. Al terminar (hora límite, Ctrl-C, SIGTERM o guardia)
deja la política segura (`--safe`, por defecto r3).

Hora de fin (T-044): `--until` es una fecha y hora UTC ABSOLUTA ("YYYY-MM-DD HH:MM"). Una hora suelta ("07:00") se
rechaza: relanzada pasada esa hora saltaba al día siguiente y habría rotado durante la final. No arranca si el fin ya
pasó, si el fin cae después del congelado (`--freeze`, por defecto 2026-11-15 08:00 UTC = 09:00 CET), si no cabe ningún
bloque entero, o si `--block-min` no es un múltiplo positivo de 5.

Guardia: cada minuto lee el leaderboard público (ventana exacta de los últimos 15 minutos, sin clave). Si el on_time
del equipo queda por debajo de `--min-on-time` en dos lecturas seguidas, o la conversión del equipo cae por debajo del
baseline en dos lecturas seguidas, escribe la política segura y termina.

Qué se sirvió de verdad (T-044): escribir `policy.json` no demuestra que el writer lo cargara. El leaderboard público
da, por `model_version`, las peticiones de cada ventana y la hora de la primera y la última. El rotador calcula las
etiquetas que debe emitir el brazo del bloque (las internas `v3-lfm-<tag>-k|-n|-kh|-nh`, o sus códigos públicos si
existe `data/labels.json`, con la misma regla que live.py) y:
  * durante el bloque avisa en el log si a los 3 minutos ninguna petición lleva una etiqueta del brazo;
  * al acabar el bloque apunta en `data/rotation_blocks.jsonl` una línea con la época, el brazo previsto, el reparto
    real de etiquetas y `verified` (true si al menos `--min-served` % de las peticiones del bloque son del brazo).
Un bloque sin verificar no debe entrar en la lectura. Las etiquetas públicas no se escriben ni en el log ni en ese fichero
con su significado: solo cuentas por grupo (previsto / otro).

Calendario y fase (T-044): `check` imprime, para el calendario completo, cuántos bloques de cada brazo caen en cada
cuarto de hora y cuántos dentro de una ráfaga de tendencia (`--bursts`, por defecto :30 de las horas UTC impares, 45
minutos), y el sesgo esperado de cada retador frente al campeón si la ráfaga mueve nuestra distancia a la referencia
`--burst-effect` puntos. Un cambio de plan es una época nueva (`--epoch`): se anota en el log y en cada línea de
bloques, y se lee aparte de las anteriores.

No importa live.py, no usa la API key y no escribe en submissions: solo `data/policy.json`, su log y el fichero de bloques.
"""
from __future__ import annotations
import argparse, calendar, json, os, signal, sys, time, urllib.request, zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE_URL = "https://datathon.rawtree.dev/api/state"
TEAM = "team_26"
FREEZE_UTC = "2026-11-15 08:00"        # 09:00 CET del 15 nov: nada cambia en el writer a partir de aquí
BURST_MIN = 45                         # duración de una ráfaga de tendencia (I-080, auditoría del 14 nov)
SUFFIXES = ("-k", "-n", "-kh", "-nh")  # live.py: conocido / nuevo, con h en home


def load_plan(names, folder=HERE):
    """[(name, policy dict)] in plan order; raises ValueError on a missing or malformed file."""
    plan = []
    for name in names:
        path = Path(folder) / f"policy.rot_{name}.json"
        if not path.exists(): raise ValueError(f"falta {path.name}")
        conf = json.loads(path.read_text())
        if conf.get("variant") != "lfm" or not isinstance(conf.get("lfm_arms"), list) or not conf["lfm_arms"]:
            raise ValueError(f"{path.name}: se espera variant lfm con lfm_arms")
        plan.append((name, conf))
    if not plan: raise ValueError("plan vacío")
    return plan


def next_boundary(now, step=300):
    """First multiple of `step` seconds strictly after `now` (epoch seconds)."""
    return (int(now) // step + 1) * step


def schedule(start, plan_len, block_s, until):
    """[(t0, index into the plan)] for every block that fits entirely before `until`."""
    if block_s <= 0 or plan_len <= 0: raise ValueError("el bloque y el plan deben ser positivos")
    out, t, k = [], start, 0
    while t + block_s <= until:
        out.append((t, k % plan_len)); t += block_s; k += 1
    return out


def write_policy(conf, data_dir):
    path = Path(data_dir) / "policy.json"; tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(conf)); os.replace(tmp, path)


def log_change(data_dir, text, now=None):
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now if now is not None else time.time()))
    with open(Path(data_dir) / "policy_changes.log", "a") as f: f.write(f"{stamp} UTC {text}\n")
    print(stamp, text, flush=True)


def guard_reading(state, team=TEAM):
    """(on_time, conversion, baseline conversion) from an /api/state payload, or None if the team row is missing."""
    row = next((t for t in state.get("teams", []) if t.get("team_id") == team), None)
    base = state.get("baseline") or {}
    if not row or row.get("on_time") is None: return None
    return float(row["on_time"]), float(row.get("conversion") or 0.0), float(base.get("conversion") or 0.0)


def guard_trips(reading, min_on_time):
    if reading is None: return None
    on_time, conv, base = reading
    if on_time < min_on_time: return f"on_time {on_time:.2f} < {min_on_time}"
    if conv < base: return f"conversion {conv:.2f} bajo el baseline {base:.2f}"
    return None


def fetch_state(now, by_model=False, frm=None, to=None):
    if to is None: to = int(now) // 300 * 300
    if frm is None: frm = to - 900
    url = f"{STATE_URL}?from={frm}&to={to}" + ("&by=model" if by_model else "")
    with urllib.request.urlopen(url, timeout=10) as r: return json.loads(r.read())


# ---- absolute deadline ----
def parse_utc(text):
    """Epoch seconds of "YYYY-MM-DD HH:MM" (UTC). Raises ValueError on anything else, a bare "HH:MM" included."""
    try: return calendar.timegm(time.strptime(str(text).strip().replace("T", " "), "%Y-%m-%d %H:%M"))
    except ValueError:
        raise ValueError(f"'{text}': se espera fecha y hora UTC absoluta, 'YYYY-MM-DD HH:MM' (una hora suelta saltaría al día siguiente)")


def fmt(t): return time.strftime("%Y-%m-%d %H:%M", time.gmtime(t))


def plan_window(now, until, freeze, block_s, start=None):
    """(start, until) in epoch seconds for a run launched at `now`, or ValueError with the reason not to start."""
    if block_s <= 0 or block_s % 300: raise ValueError("--block-min debe ser un múltiplo positivo de 5")
    if until > freeze: raise ValueError(f"el fin ({fmt(until)} UTC) cae después del congelado ({fmt(freeze)} UTC)")
    if now >= freeze: raise ValueError(f"ya ha pasado el congelado ({fmt(freeze)} UTC): no se arranca")
    if now >= until: raise ValueError(f"el fin ({fmt(until)} UTC) ya ha pasado: no se arranca")
    first = next_boundary(now)
    if start is None: start = first
    elif start % 300: raise ValueError("--start debe caer en un múltiplo de 5 minutos")
    elif start < first: raise ValueError(f"--start ({fmt(start)} UTC) ya ha pasado o es inmediato; el primer inicio posible es {fmt(first)}")
    if start + block_s > until: raise ValueError("no cabe ningún bloque entero antes del fin")
    return start, until


# ---- which policy really served a block ----
def read_labels(data_dir):
    """(salt, map) of data/labels.json as live.py reads it, or (None, {}) when there is no usable file."""
    try:
        conf = json.loads((Path(data_dir) / "labels.json").read_text())
        return str(conf.get("salt") or ""), {str(k): str(v) for k, v in (conf.get("map") or {}).items()}     # exactly live.read_labels
    except Exception: pass
    return None, {}


def expected_labels(conf, labels=(None, {})):
    """Every model_version the arms of policy `conf` can emit, as the leaderboard shows them (live.public_label)."""
    salt, mp = labels; out = set()
    for a in conf.get("lfm_arms") or []:
        for sfx in SUFFIXES:
            v = "v3-lfm-" + str(a.get("tag", "")).lower() + sfx
            out.add(v if salt is None else (mp.get(v) or "m%05x" % (zlib.crc32((salt + "|" + v).encode()) & 0xfffff)))
    return out


def served(state, expected, t0=None, team=TEAM):
    """What the team really served in the window of `state` (an /api/state?by=model payload): requests carrying a label
    of the planned arm, the rest, and when the planned arm was last seen. None if the team row is missing."""
    row = next((t for t in state.get("teams", []) if t.get("team_id") == team), None)
    if not row: return None
    vs = row.get("versions") or []
    exp = [v for v in vs if v.get("model_version") in expected]
    n_exp = sum(int(v.get("requests") or 0) for v in exp); n_all = sum(int(v.get("requests") or 0) for v in vs)
    hidden = int(row.get("more_versions") or 0)
    last = max((float(v.get("last") or 0) for v in exp), default=None)
    return dict(requests=n_all, planned=n_exp, other=n_all - n_exp, other_labels=len(vs) - len(exp) + hidden,
                share=round(100.0 * n_exp / n_all, 2) if n_all else None,
                last_planned_after_s=None if last is None or t0 is None else round(last - t0, 1))


def verify_block(t0, block_s, name, expected, min_served, fetch=fetch_state):
    """One line for rotation_blocks.jsonl: the real label mix of the block [t0, t0 + block_s)."""
    rec = dict(start=fmt(t0), t0=int(t0), block_min=block_s / 60, planned=name, verified=False)
    try:
        frm = t0 if block_s >= 900 else t0 + block_s - 900          # the API serves windows of at least 15 minutes
        s = served(fetch(t0 + block_s, True, frm, t0 + block_s), expected, t0)
    except Exception as e:
        rec["error"] = type(e).__name__; return rec
    if s is None: rec["error"] = "sin fila del equipo"; return rec
    rec.update(s); rec["verified"] = bool(block_s >= 900 and s["share"] is not None and s["share"] >= min_served)
    return rec


def loaded(now, t0, expected, fetch=fetch_state):
    """True once the leaderboard shows a request answered by the block's arm at least 30 s into the block; None = no reading."""
    try: s = served(fetch(now, True, int(now) // 300 * 300 - 900, int(now) // 300 * 300 + 300), expected, t0)
    except Exception: return None
    if s is None: return None
    return s["last_planned_after_s"] is not None and s["last_planned_after_s"] >= 30


# ---- time-phase balance of a schedule ----
def parse_bursts(text):
    """Minutes of the UTC day at which a burst starts. None / "" = :30 of every odd UTC hour; "none" = no bursts."""
    if text is None or text == "": return [h * 60 + 30 for h in range(1, 24, 2)]
    if text == "none": return []
    return [int(x[:2]) * 60 + int(x[3:5]) for x in text.split(",") if x]


def in_burst(t0, block_s, bursts):
    """Does the block [t0, t0 + block_s) overlap a burst? Same rule as rotation_read.in_burst."""
    return any(((t % 86400) // 60 - b) % 1440 < BURST_MIN for t in range(int(t0), int(t0) + block_s, 300) for b in bursts)


def balance(blocks, names, block_s, bursts, champion, burst_effect=0.065):
    """Phase table of a schedule. Per arm: blocks, blocks inside a burst, blocks per quarter of the hour. Per challenger:
    `bias_all` = expected false lift (points) of "challenger minus mean of its champion neighbours" when a burst moves
    team-minus-reference by `burst_effect` and nothing else differs; `pairs_same_state` = challenger blocks that keep at
    least one champion neighbour in the same burst state (the primary pairing of rotation_read.py), out of `blocks`."""
    rows = [(t0, names[k], in_burst(t0, block_s, bursts)) for t0, k in blocks]
    per = {}
    for n in dict.fromkeys(names):
        mine = [r for r in rows if r[1] == n]
        q = [0, 0, 0, 0]
        for t0, _, _ in mine: q[(t0 % 3600) // 900] += 1
        per[n] = dict(blocks=len(mine), burst=sum(r[2] for r in mine), quarters=q)
    for n in dict.fromkeys(names):
        if n == champion: continue
        d, same, tot = [], 0, 0
        for j, (t0, m, b) in enumerate(rows):
            if m != n: continue
            nb = [rows[i] for i in (j - 1, j + 1) if 0 <= i < len(rows) and rows[i][1] == champion]
            if not nb: continue
            tot += 1; same += any(x[2] == b for x in nb)
            d.append(burst_effect * (b - sum(x[2] for x in nb) / len(nb)))
        per[n].update(pairs=tot, pairs_same_state=same, bias_all=round(sum(d) / len(d), 4) if d else None)
    return per


def print_balance(per, champion):
    print("brazo    bloques  en ráfaga  por cuarto (:00 :15 :30 :45)  parejas mismo estado  sesgo esperado sin emparejar por estado")
    for n, r in per.items():
        extra = "" if n == champion else f"  {r['pairs_same_state']}/{r['pairs']:<18}  {r['bias_all']:+.3f} pt" if r.get("pairs") else "  sin vecino campeón"
        print(f"{n:<8} {r['blocks']:>7}  {r['burst']:>9}  {str(r['quarters']):<28}{extra}")


def main(argv=None, now=None):
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=("check", "run"))
    p.add_argument("--plan", default="r3,cx3,r3,og1")
    p.add_argument("--block-min", type=float, default=15)
    p.add_argument("--until", required=True, help='fin, fecha y hora UTC absoluta "YYYY-MM-DD HH:MM"')
    p.add_argument("--start", help='inicio opcional, "YYYY-MM-DD HH:MM" UTC en múltiplo de 5 minutos (por defecto, el siguiente)')
    p.add_argument("--freeze", default=FREEZE_UTC, help="congelado: ningún fin puede caer después (UTC absoluta)")
    p.add_argument("--epoch", default="", help="nombre de la época (un plan nuevo = una época nueva, se lee aparte)")
    p.add_argument("--safe", default="r3")
    p.add_argument("--champion", help="brazo campeón para la tabla de fase (por defecto, el primero del plan)")
    p.add_argument("--bursts", help='inicios de ráfaga UTC "23:30,01:30" | "none" (por defecto :30 de las horas impares)')
    p.add_argument("--burst-effect", type=float, default=0.065)
    p.add_argument("--min-on-time", type=float, default=99.0)
    p.add_argument("--min-served", type=float, default=90.0, help="%% mínimo de peticiones del bloque con etiqueta del brazo previsto")
    p.add_argument("--guard-after-min", type=float, default=10, help="minutos sin guardia al empezar")
    p.add_argument("--data-dir", default=str(HERE / "data"))
    a = p.parse_args(argv)
    names = [n.strip() for n in a.plan.split(",") if n.strip()]
    plan = load_plan(names)
    safe = load_plan([a.safe])[0][1]
    now = time.time() if now is None else now
    block_s = int(round(a.block_min * 60))
    try:
        start, until = plan_window(now, parse_utc(a.until), parse_utc(a.freeze), block_s, parse_utc(a.start) if a.start else None)
    except ValueError as e:
        raise SystemExit(f"policy_rotator: {e}")
    blocks = schedule(start, len(plan), block_s, until)
    champion = a.champion or names[0]
    epoch = a.epoch or "e" + time.strftime("%d%H%M", time.gmtime(start))
    labels = read_labels(a.data_dir)
    exp = [expected_labels(conf, labels) for _, conf in plan]
    if a.cmd == "check":
        for t0, k in blocks: print(time.strftime("%H:%M", time.gmtime(t0)), plan[k][0])
        print(f"época {epoch}: {len(blocks)} bloques de {a.block_min:g} min, de {fmt(blocks[0][0])} a {fmt(blocks[-1][0] + block_s)} UTC; al acabar queda {a.safe}")
        print_balance(balance(blocks, names, block_s, parse_bursts(a.bursts), champion, a.burst_effect), champion)
        print("etiquetas:", "códigos públicos de data/labels.json" if labels[0] is not None else "internas (no hay data/labels.json)")
        print(f'lectura: python rotation_read.py --start "{fmt(blocks[0][0])}" --block-min {a.block_min:g} --seq {",".join(names)} --until "{fmt(blocks[-1][0] + block_s)}" --champion {champion}')
        return 0
    stop = {"why": None}
    for sig in (signal.SIGINT, signal.SIGTERM): signal.signal(sig, lambda *_: stop.update(why="señal"))
    log_change(a.data_dir, f"rotator: época {epoch}, plan {','.join(names)}, bloques de {a.block_min:g} min, de {fmt(blocks[0][0])} a {fmt(blocks[-1][0] + block_s)} UTC")
    trips, started, pending = 0, now, []

    def settle(force=False):
        """Verify the finished blocks whose leaderboard window is complete (75 s after their end)."""
        for item in list(pending):
            t0, name, e = item
            if not force and time.time() < t0 + block_s + 75: continue
            pending.remove(item)
            rec = dict(epoch=epoch, **verify_block(t0, block_s, name, e, a.min_served))
            with open(Path(a.data_dir) / "rotation_blocks.jsonl", "a") as f: f.write(json.dumps(rec) + "\n")
            if not rec["verified"]:
                log_change(a.data_dir, f"rotator: bloque {name} de {rec['start']} SIN VERIFICAR ({rec.get('error') or str(rec.get('share')) + ' % del brazo previsto'}); no leerlo")

    for t0, k in blocks:
        while time.time() < t0 and not stop["why"]: time.sleep(min(1.0, max(0.05, t0 - time.time())))
        if stop["why"] or time.time() >= until: break        # a suspended machine never starts a block after the deadline
        name, conf = plan[k]
        write_policy(conf, a.data_dir); log_change(a.data_dir, f"rotator: bloque {name} ({a.block_min:g} min, época {epoch})")
        last_poll, seen = 0.0, None
        while time.time() < t0 + block_s and not stop["why"]:
            time.sleep(1.0)
            if time.time() - last_poll < 60: continue
            last_poll = time.time()
            settle()
            if seen is not True and last_poll >= t0 + 90:
                seen = loaded(last_poll, t0, exp[k])
                if seen is False and last_poll >= t0 + 180:
                    log_change(a.data_dir, f"rotator: ALERTA, {int(last_poll - t0)} s de bloque y ninguna petición con etiqueta de {name}: el writer no parece haberlo cargado")
            if last_poll - started < a.guard_after_min * 60: continue
            try: why = guard_trips(guard_reading(fetch_state(time.time())), a.min_on_time)
            except Exception as e: why = None; print("guardia: lectura fallida", type(e).__name__, flush=True)
            trips = trips + 1 if why else 0
            if trips >= 2: stop["why"] = f"guardia: {why}"
        if time.time() >= t0 + block_s: pending.append((t0, name, exp[k]))      # only whole blocks are verified and read
    write_policy(safe, a.data_dir); log_change(a.data_dir, f"rotator: fin de la época {epoch} ({stop['why'] or 'hora límite'}), queda {a.safe}")
    if pending and stop["why"] != "señal": time.sleep(max(0.0, min(80.0, pending[-1][0] + block_s + 75 - time.time())))
    settle(force=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
