"""Metrics snapshots in RawTree: one compact JSON row per 15-minute window and segment in `<TEAM_ID>.scratch`.

    python tools/scratch_snapshot.py --hours 6            # insert the windows that are missing
    python tools/scratch_snapshot.py --hours 6 --dry-run  # compute and print, write nothing
    python tools/scratch_snapshot.py --read 5             # read back the latest rows

Off the serving path: nothing in `recsys/live.py` reads these rows. The script reads `<TEAM_ID>.feedback` and
`shop.requests` and writes ONLY to `<TEAM_ID>.scratch` (the table name is fixed below; any other target raises).

Rows (schemaless JSON; every row has kind, ts, window_start, window_end, segment):
  kind = "metrics_15m"       requests, on_time, on_time_share, fallback, latency_p50_ms, latency_p95_ms, purchases,
                             clicks and, if GUARD_LABEL is set in the environment, guard and guard_share
                             (segment = all | known_page | known_home | new_page | new_home)
  kind = "policy_versions"   versions = {public model_version code: requests served} for the window (segment = all).
                             The codes are the opaque public labels the leaderboard already shows.
Idempotent per (kind, window_start, segment): keys already in scratch are skipped, so it can be re-run or run from cron.
GUARD_LABEL is the public code of the generic guard list; it is not stored in the repository.
"""
from __future__ import annotations
import argparse, json, os, sys, time
from pathlib import Path

STEP = 900
TABLE = 'scratch'                      # the only table this script may write to
SEGMENTS = ('known_page', 'known_home', 'new_page', 'new_home')
FMT = '%Y-%m-%d %H:%M:%S'


def fmt(epoch): return time.strftime(FMT, time.gmtime(epoch))


def windows(now, hours, step=STEP, settle=120):
    """Complete [start, end) windows of the last `hours`, oldest first. A window counts as complete `settle` seconds
    after its end (feedback arrives a few seconds after the 3 s deadline)."""
    last_end = int(now - settle) // step * step
    first = last_end - int(hours * 3600) // step * step
    return [(a, a + step) for a in range(first, last_end, step)]


def segment(is_new, page):
    return ('new' if str(is_new).lower() in ('true', '1') else 'known') + ('_home' if page == 'home' else '_page')


def metrics_sql(team, a, b, guard_label=None):
    """One row per (window, segment) plus the 'all' rollup. Requests are joined by request_id for the segment."""
    g = f"countIf(f.model_version::String = '{guard_label}')" if guard_label else 'toInt64(-1)'
    if guard_label and not guard_label.replace('-', '').replace('_', '').isalnum(): raise ValueError('bad guard label')
    return f"""
SELECT toUnixTimestamp(toStartOfInterval(toDateTime(f.ts::String), INTERVAL {STEP} SECOND)) AS w,
       if(r.rid = '', 'unknown', concat(if(r.new IN ('true', '1'), 'new', 'known'), if(r.page = 'home', '_home', '_page'))) AS seg,
       count() AS requests, countIf(f.served_by::String = 'team') AS on_time,
       {g} AS guard,
       quantileIf(0.5)(f.latency_ms::Float64, f.served_by::String = 'team') AS p50,
       quantileIf(0.95)(f.latency_ms::Float64, f.served_by::String = 'team') AS p95,
       countIf(f.purchased::String != '') AS purchases, countIf(f.clicked::String != '') AS clicks
FROM {team}.feedback f
LEFT JOIN (SELECT request_id::String AS rid, any(is_new_user::String) AS new, any(`context.page`::String) AS page
           FROM shop.requests
           WHERE toDateTime(ts::String) >= toDateTime('{fmt(a - 60)}') AND toDateTime(ts::String) < toDateTime('{fmt(b + 60)}')
           GROUP BY rid) r ON r.rid = f.request_id::String
WHERE f.request_id::String != '__init__'
  AND toDateTime(f.ts::String) >= toDateTime('{fmt(a)}') AND toDateTime(f.ts::String) < toDateTime('{fmt(b)}')
GROUP BY w, seg WITH ROLLUP HAVING w != 0 ORDER BY w, seg"""


def versions_sql(team, a, b):
    return f"""
SELECT toUnixTimestamp(toStartOfInterval(toDateTime(ts::String), INTERVAL {STEP} SECOND)) AS w,
       model_version::String AS mv, count() AS n
FROM {team}.feedback
WHERE request_id::String != '__init__' AND served_by::String = 'team'
  AND toDateTime(ts::String) >= toDateTime('{fmt(a)}') AND toDateTime(ts::String) < toDateTime('{fmt(b)}')
GROUP BY w, mv ORDER BY w, n DESC"""


def build_rows(metric_rows, version_rows, now, source='tools/scratch_snapshot.py'):
    """Pure: query results (lists of dicts) -> scratch rows. Segment '' (the ROLLUP total) becomes 'all'."""
    out, ts = [], fmt(now)
    for m in metric_rows:
        w, n, ok = int(m['w']), int(m['requests']), int(m['on_time'])
        if n <= 0: continue
        row = dict(kind='metrics_15m', ts=ts, window_start=fmt(w), window_end=fmt(w + STEP), segment=m.get('seg') or 'all',
                   requests=n, on_time=ok, fallback=n - ok, on_time_share=round(ok / n, 5),
                   latency_p50_ms=_num(m.get('p50')), latency_p95_ms=_num(m.get('p95')),
                   purchases=int(m['purchases']), clicks=int(m['clicks']), source=source)
        if int(m.get('guard', -1)) >= 0:
            row.update(guard=int(m['guard']), guard_share=round(int(m['guard']) / n, 5))
        out.append(row)
    by_w = {}
    for v in version_rows: by_w.setdefault(int(v['w']), {})[str(v['mv'])] = int(v['n'])
    for w, versions in sorted(by_w.items()):
        out.append(dict(kind='policy_versions', ts=ts, window_start=fmt(w), window_end=fmt(w + STEP), segment='all',
                        requests=sum(versions.values()), n_versions=len(versions), versions=json.dumps(versions, sort_keys=True),
                        source=source))
    return out


def _num(x):
    try:
        x = float(x)
        return None if x != x else round(x, 1)
    except (TypeError, ValueError): return None


def key(row): return (str(row['kind']), str(row['window_start'])[:19], str(row['segment']))


def missing(rows, existing):
    """Pure: the rows whose (kind, window_start, segment) is not in `existing`; duplicates inside `rows` are dropped too."""
    seen, out = set(existing), []
    for r in rows:
        k = key(r)
        if k not in seen: seen.add(k); out.append(r)
    return out


# ---- network ----
def _env():
    root = Path(__file__).resolve().parent.parent
    for p in (root / '.env', root / 'recsys' / '.env'):
        if p.exists():
            for line in p.read_text().splitlines():
                k, _, v = line.partition('='); os.environ.setdefault(k.strip(), v.strip())
    return os.environ.get('RAWTREE_API_URL', 'https://api.rawtree.com').rstrip('/'), os.environ['TEAM_ID'], os.environ['RAWTREE_API_KEY']


def query(sql):
    import requests
    api, _, k = _env()
    r = requests.post(f'{api}/v1/query', json={'sql': sql}, headers={'Authorization': f'Bearer {k}'}, timeout=120)
    if r.status_code != 200: raise RuntimeError(r.text[:500])
    return r.json()['data']


def existing_keys(team, a):
    try:
        rows = query(f"SELECT kind::String AS kind, window_start::String AS window_start, segment::String AS segment FROM {team}.{TABLE} "
                     f"WHERE window_start::String >= '{fmt(a)}'")
    except RuntimeError as e:          # schemaless table before its first row: the columns do not exist yet
        if 'Unknown' in str(e) or 'identifier' in str(e) or 'Missing columns' in str(e): return set()
        raise
    return {key(r) for r in rows}


def insert(rows, table=TABLE):
    if table != 'scratch': raise PermissionError('scratch_snapshot writes only to <TEAM_ID>.scratch')
    import requests
    api, team, k = _env()
    for i in range(0, len(rows), 500):
        r = requests.post(f'{api}/v1/tables/{table}', params={'database': team}, json=rows[i:i + 500],
                          headers={'Authorization': f'Bearer {k}'}, timeout=60)
        r.raise_for_status()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--hours', type=float, default=6)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--read', type=int, default=0, help='only read back the latest N rows per kind')
    a = ap.parse_args(argv)
    _, team, _ = _env()
    if a.read:
        for kind in ('metrics_15m', 'policy_versions'):
            for r in query(f"SELECT * FROM {team}.{TABLE} WHERE kind::String = '{kind}' AND segment::String = 'all' ORDER BY window_start::String DESC LIMIT {a.read}"):
                print(json.dumps(r, sort_keys=True, default=str))
        return 0
    now = time.time(); ws = windows(now, a.hours)
    if not ws: return 0
    lo, hi = ws[0][0], ws[-1][1]
    rows = build_rows(query(metrics_sql(team, lo, hi, os.environ.get('GUARD_LABEL'))), query(versions_sql(team, lo, hi)), now)
    new = missing(rows, existing_keys(team, lo))
    print(json.dumps(dict(windows=len(ws), window_from=fmt(lo), window_to=fmt(hi), computed=len(rows), already=len(rows) - len(new), to_insert=len(new), dry_run=a.dry_run)))
    if a.dry_run:
        for r in new[:6]: print(json.dumps(r))
    elif new:
        insert(new)
    return 0


if __name__ == '__main__':
    sys.exit(main())
