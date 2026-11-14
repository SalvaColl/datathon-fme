"""Read-only reliability evidence; never inserts submissions."""
import argparse
import json
import re
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.feedback_monitor import sql, TEAM


def collect(minutes):
    if not re.fullmatch(r'team_[A-Za-z0-9_]+', TEAM):
        raise ValueError('Invalid TEAM_ID')
    where = f"request_id::String != '__init__' AND ts::DateTime64(3) >= now() - INTERVAL {minutes} MINUTE"
    start = time.perf_counter()
    groups = sql(f"""SELECT toStartOfFiveMinutes(ts::DateTime64(3))::String bucket,
        served_by::String source, fallback_reason::String reason, count() n,
        quantileExact(0.5)(latency_ms::Float64) p50_ms,
        quantileExact(0.95)(latency_ms::Float64) p95_ms,
        quantileExact(0.99)(latency_ms::Float64) p99_ms
        FROM {TEAM}.feedback WHERE {where} GROUP BY bucket, source, reason ORDER BY bucket""")
    joins = sql(f"""SELECT f.served_by::String source, f.fallback_reason::String reason,
        count() n, countIf(s.attempts > 0) with_submission,
        countIf(s.attempts > 1) with_multiple_submissions
        FROM (SELECT * FROM {TEAM}.feedback WHERE {where}) f
        LEFT JOIN (SELECT request_id::String rid, count() attempts FROM {TEAM}.submissions GROUP BY rid) s
        ON f.request_id::String = s.rid GROUP BY source, reason""")
    # Do not count a joined feedback row once for each submission.
    versions = sql(f"""SELECT model_version::String version, count() submissions
        FROM {TEAM}.submissions WHERE request_id::String IN
        (SELECT request_id::String FROM shop.requests WHERE ts::DateTime64(3) >= now() - INTERVAL {minutes} MINUTE)
        GROUP BY version ORDER BY submissions DESC""")
    result = {'minutes': minutes, 'five_minute_groups': groups,
              'feedback_submission_coverage': joins, 'submitted_versions': versions,
              'query_total_seconds': time.perf_counter()-start,
              'limitations': 'Submission presence does not prove arrival before deadline; duplicates may be retries or multiple hosts. Version counts are submission counts, not attributed served rewards.'}
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--minutes', type=int, default=30)
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    if not 1 <= a.minutes <= 120:
        p.error('minutes must be between 1 and 120')
    result = collect(a.minutes)
    if a.output:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
