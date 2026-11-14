"""Read-only T-021 training/validation download. NEVER queries a final-test row.

Keeps the league E-011 time boundaries; intentionally creates no test.json.
Run as python -m tools.content_data --help. No additional dependencies.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from tools.league_data import KEY, ROOT, sql
from tools.local_league import Catalog, check_period, digest, iso, save, sqltime, stamp

BOUNDARIES = ["2026-09-15T07:00:06.371+00:00", "2026-10-27T07:00:01.356+00:00",
              "2026-11-05T07:00:00.281+00:00"]
LIMITATION = ("UNRECONSTRUCTABLE HISTORY: organizer base catalogue has no field-level versions. "
              "Description/category/subcategory/brand/price/stock are assumed initial base state, "
              "but their historical correctness cannot be certified. Only creation timestamps and "
              "available timestamped full-state updates can be replayed. No current merged catalogue used.")


def prepare(directory, sample=20000, validation_sample=10000, organic_sample=200000, seed=20261114):
    if not KEY:
        raise RuntimeError("No RawTree read credentials in the existing environment/.env; configure locally, never commit secrets")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if (directory / "manifest.json").exists():
        raise ValueError("Immutable snapshot exists; reuse it, do not re-sample validation")
    legacy = ROOT / "data/local_eval/holdout.json"
    excluded = {r["request_id"] for r in json.loads(legacy.read_text())["requests"]} if legacy.exists() else set()
    plan = {"boundaries": BOUNDARIES, "train_sample": sample, "validation_sample": validation_sample,
            "organic_sample": organic_sample, "seed": seed, "excluded_ids_sha256": digest(sorted(excluded)),
            "excluded_count": len(excluded), "legacy_exclusions_available": legacy.exists()}
    plan_path = directory / "plan.json"
    if plan_path.exists() and json.loads(plan_path.read_text()) != plan:
        raise ValueError("Partial preparation plan changed")
    save(plan_path, plan)
    queries = []

    def cached(name, query):
        path = directory / name
        queries.append(query)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        print(f"Read-only download: {name}", flush=True)
        value = sql(query)
        save(path, value)
        return value

    base = cached("base_rows.json", "SELECT product_id::String AS product_id, category, subcategory, brand, price_eur, description, created_at, is_active FROM shop.catalog")
    updates = cached("update_rows.json", f"SELECT * FROM shop.catalog_updates WHERE ts::DateTime64(3) < '{sqltime(BOUNDARIES[2])}' ORDER BY ts::DateTime64(3), product_id::String")
    metadata = {"base": base, "updates": updates, "limitation": LIMITATION}
    save(directory / "catalog.json", metadata)
    snapshots = {}
    for j, (name, n) in enumerate((("train", sample), ("validation", validation_sample))):
        start, end = BOUNDARIES[j:j + 2]
        qstart, qend = sqltime(start), sqltime(end)
        query = f"""SELECT request_id::String AS request_id, ts::String AS ts,
            user_id, context, recent_views, shown, propensity, clicked, purchased
            FROM shop.history_sessions WHERE ts::DateTime64(3) >= '{qstart}'
            AND ts::DateTime64(3) < '{qend}'
            ORDER BY cityHash64(concat(request_id::String, '{seed}')), request_id::String LIMIT {n + len(excluded)}"""
        rows = cached(f"{name}_rows.json", query)
        rows = [r for r in rows if r["request_id"] not in excluded][:n]
        rows.sort(key=lambda r: (stamp(r["ts"]), r["request_id"]))
        check_period(rows, start, end)
        if not rows:
            raise ValueError(f"Empty {name} period")
        snapshots[name] = {"start": start, "end": end, "requests": rows}
    start, end = map(sqltime, BOUNDARIES[:2])
    events = cached("organic_rows.json", f"""SELECT ts::String AS ts, user_id::String AS user_id,
        product_id::String AS product_id, event_type::String AS event_type, price_eur
        FROM shop.history_events WHERE ts::DateTime64(3) >= '{start}' AND ts::DateTime64(3) < '{end}'
        ORDER BY cityHash64(concat(user_id::String, session_id::String, product_id::String,
        event_type::String, ts::String, '{seed}')), user_id::String, ts::String, product_id::String LIMIT {organic_sample}""")
    purchases = cached("popularity_rows.json", f"""SELECT product_id::String AS product_id, count() AS n
        FROM shop.history_events WHERE event_type = 'purchase' AND ts::DateTime64(3) >= '{start}'
        AND ts::DateTime64(3) < '{end}' GROUP BY product_id ORDER BY n DESC, product_id DESC LIMIT 10000""")
    train = snapshots["train"]
    train.update({"best": [r["product_id"] for r in purchases], "organic_events": events,
                  "catalog_updates": [r for r in updates if stamp(BOUNDARIES[0]) <= stamp(r["ts"]) < stamp(BOUNDARIES[1])],
                  "metadata_limitation": LIMITATION})
    # The standard league supplies this same initial as-of catalogue to fit().
    train["catalog"] = Catalog(metadata).at(iso(stamp(BOUNDARIES[0]) - timedelta(milliseconds=1)))
    if {r["request_id"] for r in train["requests"]} & {r["request_id"] for r in snapshots["validation"]["requests"]}:
        raise ValueError("Train/validation request overlap")
    for name, snapshot in snapshots.items():
        save(directory / f"{name}.json", snapshot)
    files = {f"{name}.json": digest(value) for name, value in snapshots.items()}
    files["catalog.json"] = digest(metadata)
    manifest = {"version": "content-t021-train-validation-only-v1", "boundaries": BOUNDARIES,
                "seed": seed, "files": files, "plan": plan, "queries": queries,
                "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                "organic_sampling": "Deterministic hash sample of training events; not exhaustive profiles, no inverse sampling weights",
                "final_test": "NOT DOWNLOADED, OPENED OR SCORED", "catalog_limitation": LIMITATION}
    save(directory / "manifest.json", manifest)
    print(json.dumps({"train_sessions": len(train["requests"]), "validation_sessions": len(snapshots["validation"]["requests"]),
                      "organic_events": len(events), "catalog_products": len(base), "manifest_sha256": digest(manifest)}, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cache", type=Path, default=ROOT / "data/local_eval/content_t021")
    p.add_argument("--sample", type=int, default=20000)
    p.add_argument("--validation-sample", type=int, default=10000)
    p.add_argument("--organic-sample", type=int, default=200000)
    p.add_argument("--seed", type=int, default=20261114)
    a = p.parse_args()
    if min(a.sample, a.validation_sample, a.organic_sample) < 1:
        p.error("Sample sizes must be positive")
    prepare(a.cache, a.sample, a.validation_sample, a.organic_sample, a.seed)


if __name__ == "__main__":
    main()
