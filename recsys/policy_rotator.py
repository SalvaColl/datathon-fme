"""policy_rotator — alterna políticas completas de lfm en bloques fijos (T-042).

    python policy_rotator.py check --plan r3,cx3,r3,og1 --block-min 20
    python policy_rotator.py run   --plan r3,cx3,r3,og1 --block-min 20 --until 07:00     # hora UTC

Cada nombre del plan es un fichero `policy.rot_<nombre>.json` junto a este script (una política entera, normalmente de
un solo brazo). `run` espera al siguiente múltiplo de 5 minutos UTC, copia el fichero a `data/policy.json` (escritura
atómica; el writer lo relee en caliente) y repite el plan en bucle hasta `--until`. Cada cambio queda en
`data/policy_changes.log` con hora UTC y motivo. Al terminar (hora límite, Ctrl-C, SIGTERM o guardia) deja la política
segura (`--safe`, por defecto r3).

Guardia: cada minuto lee el leaderboard público (ventana exacta de los últimos 15 minutos, sin clave). Si el on_time
del equipo queda por debajo de `--min-on-time` en dos lecturas seguidas, o la conversión del equipo cae por debajo del
baseline en dos lecturas seguidas, escribe la política segura y termina.

No importa live.py, no usa la API key y no escribe en submissions: solo `data/policy.json` y su log.
"""
from __future__ import annotations
import argparse, json, os, signal, sys, time, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE_URL = "https://datathon.rawtree.dev/api/state"
TEAM = "team_26"


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


def fetch_state(now):
    to = int(now) // 300 * 300
    with urllib.request.urlopen(f"{STATE_URL}?from={to - 900}&to={to}", timeout=10) as r: return json.loads(r.read())


def parse_until(text, now):
    hh, mm = (int(x) for x in text.split(":"))
    day = time.gmtime(now); t = int(now) - (day.tm_hour * 3600 + day.tm_min * 60 + day.tm_sec) + hh * 3600 + mm * 60
    return t if t > now else t + 86400


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=("check", "run"))
    p.add_argument("--plan", default="r3,cx3,r3,og1")
    p.add_argument("--block-min", type=float, default=20)
    p.add_argument("--until", default="07:00", help="hora UTC HH:MM")
    p.add_argument("--safe", default="r3")
    p.add_argument("--min-on-time", type=float, default=99.0)
    p.add_argument("--guard-after-min", type=float, default=10, help="minutos sin guardia al empezar")
    p.add_argument("--data-dir", default=str(HERE / "data"))
    a = p.parse_args(argv)
    plan = load_plan([n.strip() for n in a.plan.split(",") if n.strip()])
    safe = load_plan([a.safe])[0][1]
    now = time.time(); block_s = int(a.block_min * 60)
    if block_s % 300: raise SystemExit("--block-min debe ser múltiplo de 5")
    blocks = schedule(next_boundary(now), len(plan), block_s, parse_until(a.until, now))
    if a.cmd == "check":
        for t0, k in blocks[:8]: print(time.strftime("%H:%M", time.gmtime(t0)), plan[k][0])
        print(f"{len(blocks)} bloques de {a.block_min:g} min"); return 0
    stop = {"why": None}
    for sig in (signal.SIGINT, signal.SIGTERM): signal.signal(sig, lambda *_: stop.update(why="señal"))
    trips, started = 0, now
    for t0, k in blocks:
        while time.time() < t0 and not stop["why"]: time.sleep(min(1.0, max(0.05, t0 - time.time())))
        if stop["why"]: break
        name, conf = plan[k]
        write_policy(conf, a.data_dir); log_change(a.data_dir, f"rotator: bloque {name} ({a.block_min:g} min)")
        last_poll = 0.0
        while time.time() < t0 + block_s and not stop["why"]:
            time.sleep(1.0)
            if time.time() - last_poll < 60 or time.time() - started < a.guard_after_min * 60: continue
            last_poll = time.time()
            try: why = guard_trips(guard_reading(fetch_state(time.time())), a.min_on_time)
            except Exception as e: why = None; print("guardia: lectura fallida", type(e).__name__, flush=True)
            trips = trips + 1 if why else 0
            if trips >= 2: stop["why"] = f"guardia: {why}"
    write_policy(safe, a.data_dir); log_change(a.data_dir, f"rotator: fin ({stop['why'] or 'hora límite'}), queda {a.safe}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
