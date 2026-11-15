"""Read-only watchdog for the live writer (T-063). Never writes anything, never starts a recommender.

Reads `<TEAM_ID>.feedback` only (plus the server clock) and prints a verdict: OK / WARN / CRITICAL.

    python3 tools/watchdog.py --once            # human-readable, exit code 0 / 1 / 2
    python3 tools/watchdog.py --once --json     # one JSON document
    python3 tools/watchdog.py --watch 20        # loop, one verdict line every 20 s (Ctrl-C to stop)

Run it on a machine that is NOT the writer host (see HANDOFF.md: anything else on that machine costs requests).

What each alarm family is allowed to say:
  * fast alarms (heartbeat, missing / invalid / guard share, latency) come from validity, deadline and process
    health; they react within 1-2 minutes and may be CRITICAL;
  * the conversion alarm compares binomial (Wilson) intervals and needs a minimum sample that a 5-minute window can
    never reach (about 215 purchases per hour = 18 per 5 minutes); below that sample it only reports numbers.

All thresholds live in THRESHOLDS and every decision is a pure function of the metrics dict, so tests need no network.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OK, WARN, CRITICAL = 'OK', 'WARN', 'CRITICAL'
RANK = {OK: 0, WARN: 1, CRITICAL: 2}

THRESHOLDS = dict(
    # Heartbeat, seconds between the server clock and the newest feedback row. Measured 15 Nov 07:20 UTC over 130 s:
    # the newest team-served row is 1.0-2.1 s behind now() (feedback ts = request ts + ~4.24 s, written ~1.3 s later).
    hb_team_warn_s=10.0, hb_team_crit_s=20.0, hb_any_warn_s=20.0,
    # Shares of requests. Baseline since 03:00 UTC: missing 2-10 of 10,800 per hour (<0.1%), guard 12-27 per hour.
    missing_warn=0.01, missing_minute=0.05, invalid_warn=0.005, invalid_minute=0.02,
    guard_warn=0.02, guard_minute=0.20, consecutive=2, min_minute_rows=60,
    # Latency of team-served answers, ms. Baseline p95 1.9-2.0 s, p99 2.3-2.4 s; organizer deadline 3,000 ms.
    p95_warn_ms=2400.0, p99_warn_ms=2700.0, p99_crit_ms=2900.0,
    # Stream volume: ~180 requests per minute.
    rpm_warn=120.0,
    # Conversion: two-sided z for the Wilson intervals, and the relative drop the minimum sample is sized for.
    conv_z=2.576, conv_power_z=0.842, conv_drop=0.5, conv_floor_requests=2000, conv_min_baseline_purchases=100,
)


def wilson(k, n, z=1.96):
    """Wilson score interval for a binomial proportion: (low, high). n == 0 -> (0, 1)."""
    if n <= 0:
        return 0.0, 1.0
    p, z2 = k / n, z * z
    centre, half = p + z2 / (2 * n), z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return max(0.0, (centre - half) / (1 + z2 / n)), min(1.0, (centre + half) / (1 + z2 / n))


def min_conversion_sample(base_rate, th=THRESHOLDS):
    """Requests needed in the recent window before a conversion drop may be called at all: enough to tell a relative
    drop of th['conv_drop'] from the baseline rate at z = conv_z with power z = conv_power_z, and never fewer than
    th['conv_floor_requests']. At 2% and a 50% drop this is ~3,450 requests (19 minutes of stream)."""
    floor = int(th['conv_floor_requests'])
    if not 0 < base_rate < 1:
        return floor
    low = base_rate * (1 - th['conv_drop'])
    need = (th['conv_z'] + th['conv_power_z']) ** 2 * (base_rate * (1 - base_rate) + low * (1 - low)) / (base_rate - low) ** 2
    return max(floor, int(math.ceil(need)))


def conversion_check(k_recent, n_recent, k_base, n_base, th=THRESHOLDS):
    """Compare recent purchases/requests with the baseline. Returns a dict; 'rollback' is True only when the sample
    is large enough AND the recent upper bound is below the baseline lower bound. A short window never qualifies."""
    base_rate = k_base / n_base if n_base else 0.0
    need = min_conversion_sample(base_rate, th)
    lo_r, hi_r = wilson(k_recent, n_recent, th['conv_z'])
    lo_b, hi_b = wilson(k_base, n_base, th['conv_z'])
    enough = n_recent >= need and k_base >= th['conv_min_baseline_purchases']
    return dict(recent=dict(purchases=k_recent, requests=n_recent, rate=k_recent / n_recent if n_recent else None,
                            low=lo_r, high=hi_r),
                baseline=dict(purchases=k_base, requests=n_base, rate=base_rate if n_base else None, low=lo_b, high=hi_b),
                min_requests=need, min_baseline_purchases=int(th['conv_min_baseline_purchases']),
                enough_sample=bool(enough), rollback=bool(enough and hi_r < lo_b))


def consecutive_over(minutes, key, limit, k, min_rows):
    """True if the k most recent minute buckets (minutes[0] is the newest) all have share(key) > limit.
    A bucket with fewer than min_rows rows is not evidence either way and breaks the run."""
    if k <= 0 or len(minutes) < k:
        return False
    for m in minutes[:k]:
        if m.get('n', 0) < min_rows or m.get(key, 0) / m['n'] <= limit:
            return False
    return True


def share(part, total):
    return part / total if total else 0.0


def evaluate(metrics, th=THRESHOLDS):
    """metrics -> dict(level, reasons). Pure. Expected keys (all optional, a missing one raises no alarm of its own
    except the heartbeat, which is the process-health signal):
      hb_team_s, hb_any_s            seconds since the newest team-served / any feedback row (None = no row found)
      window                         dict(n, team, missing, invalid, guard, minutes) over the recent window
      minutes                        newest-first list of per-minute dicts(n, team, missing, invalid, guard)
      latency                        dict(p50, p95, p99) in ms over team-served rows of the recent window
      conversion                     output of conversion_check()
    """
    reasons = []

    def add(level, code, text):
        reasons.append(dict(level=level, code=code, text=text))

    hb_team, hb_any = metrics.get('hb_team_s'), metrics.get('hb_any_s')
    if hb_any is None or hb_any > th['hb_any_warn_s']:
        # No feedback at all (not even fallback rows): the feedback stream or our query is the problem. The writer
        # cannot be judged from here, so this is a WARN that says "look at the writer log", never a promote signal.
        add(WARN, 'feedback_stale', f"no feedback row of any kind for {_s(hb_any)}: feedback stream or query problem, "
                                    "writer state unknown (check the writer log)")
    elif hb_team is None or hb_team > th['hb_team_crit_s']:
        add(CRITICAL, 'writer_silent', f"no team-served row for {_s(hb_team)} while fallback rows keep arriving "
                                       f"(newest row {_s(hb_any)} ago)")
    elif hb_team > th['hb_team_warn_s']:
        add(WARN, 'writer_slow', f"no team-served row for {_s(hb_team)}")

    minutes, w = metrics.get('minutes') or [], metrics.get('window') or {}
    k, rows = int(th['consecutive']), th['min_minute_rows']
    for key, minute_limit, window_limit, label in (('missing', th['missing_minute'], th['missing_warn'], 'missing'),
                                                   ('invalid', th['invalid_minute'], th['invalid_warn'], 'invalid'),
                                                   ('guard', th['guard_minute'], th['guard_warn'], 'guard list')):
        if consecutive_over(minutes, key, minute_limit, k, rows):
            add(CRITICAL, key + '_sustained', f"{label} share over {minute_limit:.0%} for {k} consecutive minutes "
                + '(' + ', '.join(f"{share(m.get(key, 0), m['n']):.1%}" for m in minutes[:k]) + ', newest first)')
        elif w.get('n') and share(w.get(key, 0), w['n']) > window_limit:
            add(WARN, key + '_share', f"{label} share {share(w.get(key, 0), w['n']):.2%} of {w['n']} requests "
                                      f"in the last {w.get('minutes', '?')} min (limit {window_limit:.1%})")
        elif consecutive_over(minutes, key, minute_limit, 1, rows):
            add(WARN, key + '_minute', f"{label} share {share(minutes[0].get(key, 0), minutes[0]['n']):.1%} in the newest minute")

    lat = metrics.get('latency') or {}
    if lat.get('p99') is not None:
        if lat['p99'] >= th['p99_crit_ms']:
            add(CRITICAL, 'p99_deadline', f"served p99 {lat['p99']:.0f} ms, at the 3,000 ms deadline")
        elif lat['p99'] >= th['p99_warn_ms']:
            add(WARN, 'p99_high', f"served p99 {lat['p99']:.0f} ms (limit {th['p99_warn_ms']:.0f})")
        elif lat.get('p95') is not None and lat['p95'] >= th['p95_warn_ms']:
            add(WARN, 'p95_high', f"served p95 {lat['p95']:.0f} ms (limit {th['p95_warn_ms']:.0f})")

    if w.get('n') is not None and w.get('minutes'):
        rpm = w['n'] / w['minutes']
        if rpm < th['rpm_warn']:
            add(WARN, 'low_volume', f"{rpm:.0f} requests per minute in feedback (normal ~180): stream slow or feedback delayed")

    conv = metrics.get('conversion')
    if conv and conv.get('rollback'):
        r, b = conv['recent'], conv['baseline']
        add(WARN, 'conversion_drop', f"conversion {r['rate']:.2%} ({r['purchases']}/{r['requests']}, upper bound "
            f"{r['high']:.2%}) below the baseline interval ({b['rate']:.2%}, lower bound {b['low']:.2%}); sample is "
            f"sufficient (>= {conv['min_requests']} requests): consider rolling the policy back")

    level = max((r['level'] for r in reasons), key=RANK.get, default=OK)
    return dict(level=level, reasons=reasons)


def _s(seconds):
    return 'an unknown time (none found)' if seconds is None else f"{seconds:.1f} s"


def exit_code(level):
    return RANK.get(level, 1)


# ---------- data access (read-only SQL on /v1/query) ----------

def load_env():
    for path in (ROOT / '.env', ROOT / 'recsys' / '.env', ROOT.parent / '.env'):
        if path.exists():
            for raw in path.read_text(encoding='utf-8').splitlines():
                line = raw.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def make_query():
    import requests
    load_env()
    api = os.environ.get('RAWTREE_API_URL', 'https://api.rawtree.com').rstrip('/')
    headers = {'Authorization': f"Bearer {os.environ['RAWTREE_API_KEY']}"}

    def query(sql):
        if not sql.lstrip().upper().startswith(('SELECT', 'WITH')):
            raise PermissionError('watchdog is read-only')
        response = requests.post(f'{api}/v1/query', json={'sql': sql}, headers=headers, timeout=20)
        response.raise_for_status()
        return response.json()['data']
    return query


def parse_ts(text):
    return datetime.fromisoformat(str(text)[:23])


def sql_list(labels):
    return ', '.join("'" + str(x).replace("'", '') + "'" for x in labels) or "''"


def collect(query, team, window=5, baseline=45, conv_window=30, conv_baseline=90, guard_labels=('m0312d',), settle=8.0,
            th=THRESHOLDS):
    """Three read-only queries -> metrics dict for evaluate(). `settle` seconds are left out at the end of every
    window because the newest feedback rows are still being written (measured delay ~1-2 s, see THRESHOLDS)."""
    fb = f"{team}.feedback"
    hb = query(f"""SELECT toString(now64(3)) now, toString(max(ts::DateTime64(3))) any_ts,
        toString(maxIf(ts::DateTime64(3), served_by::String = 'team')) team_ts, count() n
        FROM {fb} WHERE ts::DateTime64(3) > now() - INTERVAL 30 MINUTE AND request_id::String != '__init__'""")[0]
    now = parse_ts(hb['now'])
    has_rows = int(hb['n']) > 0

    def lag(text):
        if not has_rows or not text or str(text).startswith('1970'):
            return None
        return max(0.0, (now - parse_ts(text)).total_seconds())
    end = now - timedelta(seconds=settle)
    end_sql = f"toDateTime64('{end.strftime('%Y-%m-%d %H:%M:%S.%f')[:23]}', 3)"
    span = int(max(window, baseline, conv_window + conv_baseline))
    guards = sql_list(guard_labels)
    rows = query(f"""SELECT intDiv(dateDiff('millisecond', ts::DateTime64(3), {end_sql}), 60000) b, count() n,
        countIf(served_by::String = 'team') team, countIf(fallback_reason::String = 'missing') missing,
        countIf(fallback_reason::String = 'invalid') invalid,
        countIf(served_by::String = 'team' AND model_version::String IN ({guards})) guard,
        countIf(purchased::String != '') purchases
        FROM {fb} WHERE ts::DateTime64(3) > {end_sql} - INTERVAL {span} MINUTE AND ts::DateTime64(3) <= {end_sql}
        AND request_id::String != '__init__' GROUP BY b ORDER BY b""")
    buckets = {int(r['b']): {k: int(r[k]) for k in ('n', 'team', 'missing', 'invalid', 'guard', 'purchases')} for r in rows}
    empty = dict(n=0, team=0, missing=0, invalid=0, guard=0, purchases=0)
    minutes = [dict(buckets.get(b, empty), age_min=b) for b in range(span)]

    def total(lo, hi):
        out = dict(empty)
        for m in minutes[lo:hi]:
            for k in out:
                out[k] += m[k]
        out['minutes'] = max(0, min(hi, span) - lo)
        return out
    w, base = total(0, window), total(window, max(window, baseline))
    conv_r, conv_b = total(0, conv_window), total(conv_window, conv_window + conv_baseline)
    versions = query(f"""SELECT if(ts::DateTime64(3) > {end_sql} - INTERVAL {int(window)} MINUTE, 'recent', 'baseline') seg,
        if(served_by::String = 'team', model_version::String, concat('(fallback:', fallback_reason::String, ')')) version,
        count() n, countIf(purchased::String != '') purchases,
        quantilesIf(0.5, 0.95, 0.99)(latency_ms::Float64, served_by::String = 'team') q
        FROM {fb} WHERE ts::DateTime64(3) > {end_sql} - INTERVAL {int(max(window, baseline))} MINUTE
        AND ts::DateTime64(3) <= {end_sql} AND request_id::String != '__init__'
        GROUP BY GROUPING SETS ((seg, version), (seg)) ORDER BY seg DESC, n DESC""")
    latency, by_version = {}, []
    for r in versions:
        q = [None if x is None or (isinstance(x, float) and math.isnan(x)) else float(x) for x in (r.get('q') or [None] * 3)]
        seg_minutes = window if r['seg'] == 'recent' else max(0, baseline - window)
        entry = dict(segment=r['seg'], version=r['version'] or '(all)', n=int(r['n']), purchases=int(r['purchases']),
                     rpm=round(int(r['n']) / seg_minutes, 1) if seg_minutes else None, p50=q[0], p95=q[1], p99=q[2])
        lo, hi = wilson(entry['purchases'], entry['n'])
        entry.update(conv=share(entry['purchases'], entry['n']), conv_low95=lo, conv_high95=hi)
        if not r['version']:
            latency[r['seg']] = dict(p50=q[0], p95=q[1], p99=q[2])
        else:
            by_version.append(entry)
    return dict(server_now=hb['now'], window_end=str(end)[:23], settle_s=settle,
                hb_team_s=lag(hb['team_ts']), hb_any_s=lag(hb['any_ts']),
                window=w, baseline=base, minutes=minutes[:max(window, 10)],
                latency=latency.get('recent') or {}, latency_baseline=latency.get('baseline') or {},
                by_version=by_version, guard_labels=list(guard_labels),
                conversion=conversion_check(conv_r['purchases'], conv_r['n'], conv_b['purchases'], conv_b['n'], th),
                conversion_windows=dict(recent_min=conv_window, baseline_min=conv_baseline))


def run_once(query, team, args, th=THRESHOLDS):
    try:
        metrics = collect(query, team, window=args.window, baseline=args.baseline, conv_window=args.conv_window,
                          conv_baseline=args.conv_baseline, guard_labels=args.guard_labels.split(','), settle=args.settle, th=th)
    except Exception as exc:      # network / query failure: not a verdict on the writer
        return dict(level=WARN, reasons=[dict(level=WARN, code='watchdog_query_failed',
                    text=f"watchdog could not read feedback ({type(exc).__name__}): writer state unknown")], metrics={})
    verdict = evaluate(metrics, th)
    verdict['metrics'] = metrics
    return verdict


def pct(x):
    return '-' if x is None else f"{100 * x:.2f}%"


def ms(x):
    return '-' if x is None else f"{x:.0f}"


def render(v, brief=False):
    m = v.get('metrics') or {}
    head = f"{m.get('server_now', datetime.now(timezone.utc).isoformat(sep=' ')[:19])} UTC  {v['level']}"
    if not m:
        return head + '  ' + '; '.join(r['text'] for r in v['reasons'])
    w, lat = m['window'], m['latency']
    line = (f"{head}  hb team {_s(m['hb_team_s'])} / any {_s(m['hb_any_s'])}  last {w['minutes']} min: n={w['n']} "
            f"({w['n'] / max(1, w['minutes']):.0f}/min) missing={w['missing']} invalid={w['invalid']} guard={w['guard']} "
            f"p50/p95/p99={ms(lat.get('p50'))}/{ms(lat.get('p95'))}/{ms(lat.get('p99'))} ms")
    out = [line] + [f"  {r['level']}: {r['text']}" for r in v['reasons']]
    if brief:
        return '\n'.join(out)
    b, lb = m['baseline'], m['latency_baseline']
    out.append(f"  baseline {b['minutes']} min before: n={b['n']} missing={b['missing']} ({pct(share(b['missing'], b['n']))}) "
               f"invalid={b['invalid']} guard={b['guard']} ({pct(share(b['guard'], b['n']))}) "
               f"p50/p95/p99={ms(lb.get('p50'))}/{ms(lb.get('p95'))}/{ms(lb.get('p99'))} ms")
    out.append('  per minute, newest first (n/missing/invalid/guard): '
               + '  '.join(f"{x['n']}/{x['missing']}/{x['invalid']}/{x['guard']}" for x in m['minutes'][:w['minutes']]))
    c, cw = m['conversion'], m['conversion_windows']
    r, bb = c['recent'], c['baseline']
    out.append(f"  conversion last {cw['recent_min']} min: {r['purchases']}/{r['requests']} = {pct(r['rate'])} "
               f"[{pct(r['low'])}, {pct(r['high'])}]  vs previous {cw['baseline_min']} min: {bb['purchases']}/{bb['requests']} "
               f"= {pct(bb['rate'])} [{pct(bb['low'])}, {pct(bb['high'])}]")
    out.append(f"  conversion alarm needs >= {c['min_requests']} requests in the recent window and >= "
               f"{c['min_baseline_purchases']} baseline purchases: "
               + ('sample sufficient' if c['enough_sample'] else 'sample NOT sufficient, numbers only, no rollback advice')
               + ('; ROLLBACK ADVISED' if c['rollback'] else ''))
    out.append('  by model_version (segment version n rpm conv [95% interval] p50/p95/p99 ms):')
    for e in m['by_version']:
        out.append(f"    {e['segment']:8s} {e['version']:22s} {e['n']:6d} {e['rpm'] if e['rpm'] is not None else '-':>6} "
                   f"{pct(e['conv'])} [{pct(e['conv_low95'])}, {pct(e['conv_high95'])}]  "
                   f"{ms(e['p50'])}/{ms(e['p95'])}/{ms(e['p99'])}")
    return '\n'.join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--once', action='store_true', help='one check and exit with 0 (OK) / 1 (WARN) / 2 (CRITICAL)')
    ap.add_argument('--watch', type=float, metavar='SECONDS', help='repeat every SECONDS until interrupted')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--window', type=int, default=5, help='recent window, minutes')
    ap.add_argument('--baseline', type=int, default=45, help='baseline reaches this many minutes back (the part before the window)')
    ap.add_argument('--conv-window', type=int, default=30, help='recent window of the conversion check, minutes')
    ap.add_argument('--conv-baseline', type=int, default=90, help='baseline of the conversion check: minutes before --conv-window')
    ap.add_argument('--guard-labels', default='m0312d', help='comma-separated public labels of the guard list')
    ap.add_argument('--settle', type=float, default=8.0, help='seconds left out at the end of the window (feedback delay)')
    ap.add_argument('--team', default=None)
    args = ap.parse_args(argv)
    query = make_query()
    team = args.team or os.environ['TEAM_ID']
    level = OK
    try:
        while True:
            v = run_once(query, team, args)
            level = v['level']
            print(json.dumps(v) if args.json else render(v, brief=bool(args.watch)), flush=True)
            if not args.watch:
                break
            time.sleep(max(1.0, args.watch))
    except KeyboardInterrupt:
        pass
    return exit_code(level)


if __name__ == '__main__':
    sys.exit(main())
